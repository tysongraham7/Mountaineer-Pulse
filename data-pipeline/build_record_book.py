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
# The 2023-24 basketball record book (records through 2022-23). wvusports.com/documents/... is a
# viewer page; this is the file behind it.
MBB_PDF = ("https://s3.us-east-2.amazonaws.com/sidearm.nextgen.sites/wvuni.sidearmsports.com"
           "/documents/2024/1/14/23-24_Record_Book.pdf")
MBB_PDF_SOURCE = "WVU men's basketball record book (2023-24 edition)"
MBB_PDF_THROUGH = 2023

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
# Basketball record book PDF: the lists Wikipedia doesn't carry
# ---------------------------------------------------------------------------

# Table title in the 2023-24 book (after "Career " / "Season ") -> list. The book's
# "Season 3-Point Field Goals" / "Attempted" title wraps, so the attempts list matches on
# its first line.
MBB_PDF_LISTS = {
    "Scoring Average": ("ppg", "Points / Game", "Scoring", "1"),
    "Field Goals Made": ("fgm", "Field Goals Made", "Scoring", "int"),
    "Free Throws Made": ("ftm", "Free Throws Made", "Scoring", "int"),
    "3-Point Field Goals Made": ("tpm", "3-Pointers Made", "3-Pointers", "int"),
    "3-Point Field Goals": ("tpa", "3-Point Attempts", "3-Pointers", "int"),
    "3-Point Field Goal": ("tp_pct", "3PT %", "3-Pointers", "pct"),
    "Field Goal Percentage": ("fg_pct", "FG %", "Shooting %", "pct"),
    "Free Throw Percentage": ("ft_pct", "FT %", "Shooting %", "pct"),
    "Rebound Average": ("rpg", "Rebounds / Game", "Rebounding", "1"),
    "Offensive Rebounds": ("oreb", "Offensive Rebounds", "Rebounding", "int"),
    "Assist Average": ("apg", "Assists / Game", "Playmaking", "1"),
    "Steal Average": ("spg", "Steals / Game", "Defense", "1"),
    "Minutes Played": ("min", "Minutes", "Playing Time", "int"),
    "Games Started": ("gs", "Games Started", "Playing Time", "int"),
    "Games Played": ("gp", "Games Played", "Playing Time", "int"),
}
YEARS = re.compile(r"^(\d{4})(?:-(\d{2}))?$")


def mbb_pdf_lists(text: str) -> list[dict]:
    """Rows read 'Name [GP] [made/att] value year(s)': the stat is the last number before
    the year. Each page also carries photo captions and sidebar tables in the text flow, so
    a list ends at the first row that isn't a well-formed entry, has the wrong kind of year
    (a single season in a career list), or breaks the list's descending order."""
    out = []
    cur, scope, prev = None, None, None
    for raw in text.splitlines():
        # "Robinson546/1,034" -> "Robinson 546/1,034". Letters only: a "." before a digit is
        # a decimal point (".663", "24.8").
        line = re.sub(r"([A-Za-z'])(\d)", r"\1 \2", raw.strip())
        m = re.match(r"^(Career|Season) (.+)$", line)
        if m and m.group(2) in MBB_PDF_LISTS:
            key, title, group, fmt = MBB_PDF_LISTS[m.group(2)]
            scope = m.group(1).lower()
            cur = {"key": key, "title": title, "group": group, "fmt": fmt, "scope": scope, "entries": []}
            out.append(cur)
            prev = None
            continue
        if cur is None or not line or line.upper().startswith(("PLAYER", "(MIN", "ATTEMPTED", "PERCENTAGE")):
            continue
        if line.isupper() and not re.search(r"\d", line):
            continue   # a photo caption ("JEVON CARTER") lands mid-list in the text flow
        if re.fullmatch(r"\[\s*\d+\s*\]", line) or line.replace(" ", "") == "RECORDBOOK":
            continue   # page number and running head: a list can carry over to the next page
        toks = line.split()
        y = YEARS.match(toks[-1]) if toks else None
        nums_at = next((i for i, t in enumerate(toks) if re.match(r"^[\d.,/]+$", t)), None)
        if not y or nums_at is None or nums_at == 0 or nums_at >= len(toks) - 1:
            if cur["entries"]:
                cur = None   # the list is over; whatever follows belongs to something else
            continue
        if scope == "season" and y.group(2):
            cur = None          # a career span inside a season list: a sidebar, not this list
            continue
        value = num(toks[-2].split("/")[-1])
        if value is None:
            continue
        if cur["fmt"] == "pct":
            # From made/attempted when the row has it: the printed rate has typos (Taz
            # Sherman's 89/102 is printed .783; it's .873).
            made_att = next((t for t in toks if re.fullmatch(r"[\d,]+/[\d,]+", t)), None)
            if made_att:
                a, b = (num(x) for x in made_att.split("/"))
                value = round(100 * a / b, 1) if a is not None and b else value
            else:
                value = round(value * 100, 1) if value < 1 else value
        if prev is not None and value > prev + 1e-9:
            cur = None
            continue
        prev = value
        name = " ".join(toks[:nums_at])
        start = int(y.group(1))
        if scope == "career":
            # One-season careers are printed as a single year (Jonathan Hargett, 2002).
            end = int(y.group(1)[:2] + y.group(2)) if y.group(2) else start
            if end < start:
                end += 100
            cur["entries"].append({"name": name, "value": value, "seasons": [start, end]})
        else:
            cur["entries"].append({"name": name, "value": value, "season": start})
    return [l for l in out if len(l["entries"]) >= 5]


def mbb_lists() -> list[dict]:
    """Wikipedia's lists (points, rebounds, assists, steals, blocks -- current through
    2024-25), then every other list from WVU's 2023-24 book, each tagged with its own source
    and through-season so the nightly merge and the app's footnote treat it correctly."""
    lists = wiki_lists(MBB_PAGE, MBB_LISTS, "mbb")
    have = {(l["key"], l["scope"]) for l in lists}
    for l in mbb_pdf_lists(pdf_text(MBB_PDF)):
        if (l["key"], l["scope"]) not in have:
            lists.append({**l, "source": MBB_PDF_SOURCE, "through": MBB_PDF_THROUGH})
    # The book prints Mike Boyd's steals career as "1994-94"; his other lists say 1991-94.
    # A one-year span inside a wider one the same player has elsewhere takes the wider one.
    spans: dict[str, list[int]] = {}
    for l in lists:
        for e in l["entries"]:
            if "seasons" in e:
                a, b = spans.get(e["name"], e["seasons"])
                spans[e["name"]] = [min(a, e["seasons"][0]), max(b, e["seasons"][1])]
    for l in lists:
        for e in l["entries"]:
            s = e.get("seasons")
            if s and s[0] == s[1] and spans[e["name"]][0] <= s[0] <= spans[e["name"]][1]:
                e["seasons"] = list(spans[e["name"]])
    return lists


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
            "lists": mbb_lists(),
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
                if max(e.get("seasons") or [e["season"]]) > l.get("through", through)]
        if late:
            die(f"{sport}: entries after the stated through-season {through} - update it:\n  "
                + "\n  ".join(late))
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(book, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print(f"\n[OK] wrote {OUT}")


if __name__ == "__main__":
    main()
