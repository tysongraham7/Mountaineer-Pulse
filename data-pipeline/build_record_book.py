"""
Mountaineer Pulse - Record Book builder
=======================================
Builds record_book.json: WVU's all-time top-10 lists (career, single season, single
game) for football, men's basketball and baseball. The Leaders tab shows them as the
Record Book, and sync_stat_archive.py brings them up to date every night by merging in
the seasons wvusports.com has published since (see merge_record_book there).

Sources, newest that can be read as text:
  football    Wikipedia, "West Virginia Mountaineers football statistical leaders",
              kept current from WVU's record book (the newest football record book
              PDF wvusports.com still serves is the 2013 edition, and current ones are
              Issuu flipbooks with no text to read).
  basketball  Wikipedia, "West Virginia Mountaineers men's basketball statistical
              leaders" (cross-checked against WVU's 2023-24 record book PDF).
  baseball    WVU's baseball record book PDF (records through the 2014 season); the
              stat archive starts in 2015, so the two meet with no gap.

This is run by hand when a source updates, not nightly: the lists are history, and the
nightly merge is what keeps them current. Review the diff of record_book.json before
committing -- a vandalised Wikipedia table would show up there first.

Needs `pdftotext` (poppler) on PATH for the baseball PDF.
Run:  python build_record_book.py
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "record_book.json")
UA = {"User-Agent": "MountaineerPulse/1.0 (record book builder; tysongraham7 at gmail)"}

WIKI = "https://en.wikipedia.org/w/index.php?title={}&action=raw"
FB_PAGE = "West_Virginia_Mountaineers_football_statistical_leaders"
MBB_PAGE = "West_Virginia_Mountaineers_men%27s_basketball_statistical_leaders"
BSB_PDF = "https://static.wvusports.com/custompages/content/files/general/baseball_records.pdf"

# The last season each source has counted. Everything after it comes from the stat archive
# each night, so these must move when a source is refreshed. Wikipedia's pages were last
# edited 2026-01-04 (football, after the 2025 season) and 2025-10-09 (basketball, after
# 2024-25, stored as 2025); the baseball book runs through 2014.
FB_THROUGH = 2025
MBB_THROUGH = 2025
BSB_THROUGH = 2014

# (wiki sub-heading) -> (key, title, group, fmt). Lists not named here are left out.
FB_LISTS = {
    "Passing yards": ("pass_yds", "Passing Yards", "Passing", "int"),
    "Passing touchdowns": ("pass_td", "Passing TD", "Passing", "int"),
    "Rushing yards": ("rush_yds", "Rushing Yards", "Rushing", "int"),
    "Rushing touchdowns": ("rush_td", "Rushing TD", "Rushing", "int"),
    "Receptions": ("rec", "Receptions", "Receiving", "int"),
    "Receiving yards": ("rec_yds", "Receiving Yards", "Receiving", "int"),
    "Receiving touchdowns": ("rec_td", "Receiving TD", "Receiving", "int"),
    "Total offense yards": ("total_off", "Total Offense", "Total Offense", "int"),
    "Touchdowns responsible for": ("td_resp", "Touchdowns Responsible For", "Total Offense", "int"),
    "All-purpose yardage": ("apy", "All-Purpose Yards", "Total Offense", "int"),
    "Tackles": ("tkl", "Tackles", "Defense", "int"),
    "Sacks": ("sacks", "Sacks", "Defense", "1"),
    "Interceptions": ("def_int", "Interceptions", "Defense", "int"),
    "Field goals made": ("fgm", "Field Goals", "Kicking", "int"),
    "Field goal percentage": ("fg_pct", "Field Goal %", "Kicking", "pct"),
}
MBB_LISTS = {
    "Scoring": ("pts", "Points", "Scoring", "int"),
    "Rebounds": ("reb", "Rebounds", "Rebounding", "int"),
    "Assists": ("ast", "Assists", "Playmaking", "int"),
    "Steals": ("stl", "Steals", "Defense", "int"),
    "Blocks": ("blk", "Blocks", "Defense", "int"),
}
# Baseball record book headings -> (key, title, group, fmt). Only the individual
# sections are read; the team records at the front reuse some of the same headings.
BSB_LISTS = {
    "BATTING AVERAGE": ("avg", "Batting Average", "Hitting", "avg"),
    "HITS": ("h", "Hits", "Hitting", "int"),
    "RUNS": ("r", "Runs", "Hitting", "int"),
    "RBI": ("rbi", "RBI", "Hitting", "int"),
    "DOUBLES": ("2b", "Doubles", "Power", "int"),
    "HOME RUNS": ("hr", "Home Runs", "Power", "int"),
    "TOTAL BASES": ("tb", "Total Bases", "Power", "int"),
    "STOLEN BASES": ("sb", "Stolen Bases", "Speed", "int"),
    "WALKS": ("bb", "Walks", "Hitting", "int"),
    "EARNED RUN AVERAGE": ("era", "ERA", "Pitching", "2"),
    "WINS": ("w", "Wins", "Pitching", "int"),
    "SAVES": ("sv", "Saves", "Pitching", "int"),
    "STRIKEOUTS": ("p_so", "Strikeouts", "Pitching", "int"),
    "INNINGS PITCHED": ("ip", "Innings", "Pitching", "ip"),
}


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def num(s: str) -> float | None:
    s = (s or "").replace(",", "").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Wikipedia tables
# ---------------------------------------------------------------------------

def wiki_clean(cell: str) -> str:
    cell = re.sub(r"<ref[^>]*/>", "", cell)
    cell = re.sub(r"<ref[^>]*>.*?</ref>", "", cell, flags=re.S)
    cell = re.sub(r"\{\{efn[^{}]*\}\}", "", cell)
    cell = re.sub(r"\{\{[^{}]*\}\}", "", cell)
    cell = re.sub(r"<br\s*/?>", " ", cell)
    cell = re.sub(r"<[^>]+>", "", cell)   # <abbr title="11,662 passing, 342 rushing">12,004</abbr>
    cell = re.sub(r"style=\"[^\"]*\"\s*\|", "", cell)
    cell = re.sub(r"\[\[[^|\]]*\|([^\]]*)\]\]", r"\1", cell)
    cell = re.sub(r"\[\[([^\]]*)\]\]", r"\1", cell)
    cell = re.sub(r"'''?", "", cell)
    return re.sub(r"\s+", " ", cell).strip()


def wiki_tables(text: str) -> list[dict]:
    """Every `{| ... |}` table, tagged with the heading above it and its caption."""
    out, section, sub, cur = [], None, None, None
    for line in text.split("\n"):
        m = re.match(r"^(=+)\s*(.*?)\s*=+\s*$", line)
        if m:
            if len(m.group(1)) == 2:
                section, sub = m.group(2), None
            else:
                sub = m.group(2)
        elif line.startswith("{|"):
            cur = {"list": sub or section, "caption": "", "rows": []}
        elif cur is None:
            continue
        elif line.startswith("|+"):
            cur["caption"] = wiki_clean(line[2:]).lower()
        elif line.startswith("|}"):
            out.append(cur)
            cur = None
        elif line.startswith("|") and not line.startswith("|-"):
            cur["rows"].append([wiki_clean(c) for c in line[1:].split("||")])
    return out


def wiki_lists(page: str, wanted: dict, sport: str) -> list[dict]:
    r = requests.get(WIKI.format(page), headers=UA, timeout=60)
    if r.status_code != 200:
        die(f"Wikipedia {page}: HTTP {r.status_code}")
    out = []
    for t in wiki_tables(r.text):
        spec = wanted.get(t["list"])
        if not spec:
            continue
        cap = t["caption"]
        scope = "career" if "career" in cap else "game" if "game" in cap else "season" if "season" in cap else None
        if not scope:
            continue
        key, title, group, fmt = spec
        entries = []
        for row in t["rows"]:
            if len(row) < 4:
                continue
            name, value = row[1], num(row[2])
            if not name or value is None:
                continue
            years = [int(y) for y in re.findall(r"\b(1[89]\d\d|20\d\d)\b", row[3])]
            if not years:
                continue
            e = {"name": name, "value": value}
            if scope == "career":
                # Basketball pages list a career as seasons ("2015-16 ... 2017-18");
                # store the years seasons END, like the rest of the app.
                e["seasons"] = [min(years), max(years)] if sport != "mbb" else _mbb_span(row[3])
            else:
                e["season"] = _mbb_end(row[3]) if sport == "mbb" else years[0]
                if scope == "game" and len(row) > 4:
                    e["opponent"] = row[4]
            entries.append(e)
        if entries:
            out.append({"key": key, "title": title, "group": group, "fmt": fmt,
                        "scope": scope, "entries": entries})
    return out


def _mbb_end(text: str) -> int:
    """'2009-10' -> 2010; '1960' -> 1960."""
    m = re.search(r"(\d{4})\s*[–-]\s*(\d{2,4})", text)
    if m:
        a, b = m.group(1), m.group(2)
        return int(a[:4 - len(b)] + b) if len(b) < 4 else int(b)
    return int(re.search(r"\d{4}", text).group(0))


def _mbb_span(text: str) -> list[int]:
    ends = []
    for m in re.finditer(r"(\d{4})(?:\s*[–-]\s*(\d{2,4}))?", text):
        ends.append(_mbb_end(m.group(0)))
    return [min(ends), max(ends)]


# ---------------------------------------------------------------------------
# Baseball record book PDF
# ---------------------------------------------------------------------------

# "1. Tyler Kuhn (2005-08)....324". Tolerates the book's own typos: a missing ")" and a
# broken career written "(2011-13, 14)".
ENTRY = re.compile(r"^(?:(\d+)\.\s*)?\*?(.+?)\s*\((\d{4})(?:-(\d{2,4}))?(?:,\s*(\d{2,4}))?\)?[.\s]*([\d.,]+)$")


def pdf_text(url: str) -> str:
    pdf = requests.get(url, headers=UA, timeout=120)
    if pdf.status_code != 200 or not pdf.content.startswith(b"%PDF"):
        die(f"baseball record book: HTTP {pdf.status_code}, not a PDF")
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "book.pdf")
        open(p, "wb").write(pdf.content)
        try:
            return subprocess.run(["pdftotext", "-raw", p, "-"], capture_output=True, check=True,
                                  text=True, encoding="utf-8", errors="replace").stdout
        except FileNotFoundError:
            die("pdftotext not found - install poppler-utils")


def baseball_lists(text: str) -> list[dict]:
    lines = [l.strip() for l in text.splitlines()]
    # A value the PDF wrapped onto its own line ("..............23") belongs to the line above.
    joined: list[str] = []
    for l in lines:
        if re.fullmatch(r"\.{2,}\s*[\d.,]+", l) and joined:
            joined[-1] += l
        else:
            joined.append(l)

    # Individual records start after the team hitting block; the first individual heading
    # is GAMES PLAYED.
    start = next(i for i, l in enumerate(joined) if l == "GAMES PLAYED")
    out: dict[tuple[str, str], dict] = {}
    heading, scope, pitching = None, None, False
    for l in joined[start:]:
        if l == "PITCHING RECORDS":
            pitching = True
        sub_head = l.startswith(("SEASON", "CAREER", "GAME", "TEAM", "INDIVIDUAL", "INDVIDUAL"))
        if l in BSB_LISTS or (re.fullmatch(r"[A-Z][A-Z .'/-]{3,}", l) and not sub_head):
            heading, scope = l, None
            # Hitters have a STRIKEOUTS list too (times struck out); only the pitchers' counts.
            if l == "STRIKEOUTS" and not pitching:
                heading = None
            continue
        if l.startswith("SEASON"):
            scope = "season"
            continue
        if l.startswith("CAREER"):
            scope = "career"
            continue
        if l.startswith(("GAME", "TEAM", "INDIVIDUAL", "INDVIDUAL")):
            scope = None
            continue
        if heading not in BSB_LISTS or scope is None:
            continue
        m = ENTRY.match(l)
        if not m:
            continue
        key, title, group, fmt = BSB_LISTS[heading]
        name = m.group(2).split(" (")[0].strip().rstrip(".")
        raw = m.group(6).rstrip(".")
        value = num(raw)
        if value is None:
            continue
        if fmt == "avg" and "." not in raw:
            value /= 1000   # ".439" loses its point to the dot leaders
        y0 = int(m.group(3))
        e = {"name": name, "value": value}
        if scope == "career":
            y1 = m.group(5) or m.group(4)
            end = y0 if not y1 else int(str(y0)[:4 - len(y1)] + y1) if len(y1) < 4 else int(y1)
            if end < y0:          # "1999-02" crosses a century
                end += 100
            e["seasons"] = [y0, end]
        else:
            e["season"] = y0
        lst = out.setdefault((key, scope), {"key": key, "title": title, "group": group,
                                            "fmt": fmt, "scope": scope, "entries": []})
        lst["entries"].append(e)
    return list(out.values())


# ---------------------------------------------------------------------------

def main() -> None:
    book = {
        "built": date.today().isoformat(),
        "football": {
            "source": "WVU football record book (via Wikipedia's statistical leaders)",
            "source_url": f"https://en.wikipedia.org/wiki/{FB_PAGE}",
            "through": FB_THROUGH,
            "lists": wiki_lists(FB_PAGE, FB_LISTS, "football"),
        },
        "mbb": {
            "source": "WVU men's basketball record book (via Wikipedia's statistical leaders)",
            "source_url": f"https://en.wikipedia.org/wiki/{MBB_PAGE}",
            "through": MBB_THROUGH,
            "lists": wiki_lists(MBB_PAGE, MBB_LISTS, "mbb"),
        },
        "baseball": {
            "source": "WVU baseball record book",
            "source_url": BSB_PDF,
            "through": BSB_THROUGH,
            "lists": baseball_lists(pdf_text(BSB_PDF)),
        },
    }
    for sport in ("football", "mbb", "baseball"):
        lists = book[sport]["lists"]
        print(f"{sport}: {len(lists)} lists")
        for l in lists:
            top = l["entries"][0]
            print(f"   {l['scope']:<7}{l['title']:<28}{len(l['entries']):>3} entries  "
                  f"#1 {top['name']} {top['value']:g}")
        if len(lists) < 10:
            die(f"{sport}: only {len(lists)} lists parsed - has the source's layout changed?")
        through = book[sport]["through"]
        late = [f"{l['title']} ({l['scope']}): {e['name']}" for l in lists for e in l["entries"]
                if max(e.get("seasons") or [e["season"]]) > through]
        if late:
            die(f"{sport}: entries after the stated through-season {through} - update it:\n  "
                + "\n  ".join(late))
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(book, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print(f"\n[OK] wrote {OUT}")


if __name__ == "__main__":
    main()
