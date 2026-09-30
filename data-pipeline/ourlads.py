"""
Mountaineer Pulse - Ourlads depth chart reader
==============================================
Reads WVU's football two-deep from Ourlads, the page the founder was copying into
depth_chart.json by hand. sync_depth.py uses it as the football base and layers the
curated overrides (injuries, notes, pinned rows) on top.

The page is one table per unit, one row per position, in Ourlads' own order:

    <tbody id="ctl00_phContent_dcTBody">   offense
    <tbody id="ctl00_phContent_dcTBody2">  defense
    <tbody id="ctl00_phContent_dcTBody3">  special teams
    <tbody id="ctl00_phContent_dcTBody4">  reserves (RES) -- mostly the injured

and each player cell reads "Hawkins Jr., Michael RS SO/TR". Empty depth slots are still
there as links with no text, and are skipped.

Run on its own to print what it reads:  python ourlads.py
"""

import html as htmllib
import re
import time

import requests

URL = "https://www.ourlads.com/ncaa-football-depth-charts/depth-chart/west-virginia/92499"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120 Safari/537.36"}

UNITS = {
    "ctl00_phContent_dcTBody": "Offense",
    "ctl00_phContent_dcTBody2": "Defense",
    "ctl00_phContent_dcTBody3": "Special Teams",
    "ctl00_phContent_dcTBody4": "Reserves",
}

# Ourlads' class codes, in the "R-So." style the roster and the app already use. The
# "/TR" transfer suffix is dropped: the app has never shown it, and Movement covers it.
CLASS = {"FR": "Fr.", "SO": "So.", "JR": "Jr.", "SR": "Sr.", "GR": "Gr."}

_TBODY = re.compile(r'<tbody id="(ctl00_phContent_dcTBody\d?)">(.*?)</tbody>', re.S)
_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_POS = re.compile(r"<td[^>]*>([^<]*)</td>")
_PLAYER = re.compile(r"<a [^>]*>([^<]*)</a>")
_UPDATED = re.compile(r"Updated:\s*([0-9/]+\s*[0-9:]+\s*[AP]M\s*ET)", re.I)
# "Hawkins Jr., Michael RS SO/TR" -> surname, given, class. The class is the trailing run
# of upper-case codes, so a given name like "DJ" or "KJ" is never mistaken for one.
_CELL = re.compile(r"^(?P<last>[^,]+),\s*(?P<first>.+?)\s+(?P<cls>(?:RS\s+)?(?:FR|SO|JR|SR|GR)(?:/TR)?)$")


def class_display(code: str) -> str | None:
    code = code.upper().replace("/TR", "").strip()
    rs = code.startswith("RS ")
    base = CLASS.get(code.removeprefix("RS ").strip())
    if not base:
        return None
    return f"R-{base}" if rs else base


def parse_cell(text: str) -> tuple[str, str | None] | None:
    """'Latimer II, Geimere SR/TR' -> ('Geimere Latimer II', 'Sr.'). None for an empty slot."""
    text = " ".join(htmllib.unescape(text).split())
    if not text:
        return None
    m = _CELL.match(text)
    if not m:
        # No recognizable class on the end -- still a player, just no class to show.
        last, _, first = text.partition(",")
        name = f"{first.strip()} {last.strip()}".strip()
        return (name, None) if name else None
    return f"{m['first'].strip()} {m['last'].strip()}", class_display(m["cls"])


def parse(page: str) -> dict:
    """{'updated': '09/26/2026 5:00PM ET' | None,
        'rows': [{'unit', 'position', 'row', 'rank', 'player_name', 'class_year'}, ...]}
    `row` is the position's order within its unit on Ourlads; `rank` is 1 for the starter."""
    rows = []
    for tbody_id, body in _TBODY.findall(page):
        unit = UNITS.get(tbody_id)
        if not unit:
            continue
        for i, tr in enumerate(_ROW.findall(body), start=1):
            pos_m = _POS.search(tr)
            if not pos_m:
                continue
            position = htmllib.unescape(pos_m.group(1)).strip()
            rank = 0
            for cell in _PLAYER.findall(tr):
                parsed = parse_cell(cell)
                if not parsed:
                    continue
                rank += 1
                rows.append({
                    "unit": unit,
                    "position": position,
                    "row": i,
                    "rank": rank,
                    "player_name": parsed[0],
                    "class_year": parsed[1],
                })
    upd = _UPDATED.search(page)
    return {"updated": upd.group(1) if upd else None, "rows": rows}


def fetch(url: str = URL, attempts: int = 3) -> str:
    """GET with retries, and insist on the whole document: a short read parses to an
    empty chart, which must look like a failure and not like WVU having no players."""
    delay = 5.0
    last: Exception | None = None
    for i in range(1, attempts + 1):
        try:
            r = requests.get(url, headers=UA, timeout=45)
            r.raise_for_status()
            if "</html>" not in r.text[-2000:]:
                raise requests.RequestException(f"incomplete response ({len(r.text)} bytes)")
            return r.text
        except requests.RequestException as e:
            last = e
            if i < attempts:
                print(f"    (Ourlads fetch failed {type(e).__name__} — retry {i}/{attempts - 1} in {delay:.0f}s)")
                time.sleep(delay)
                delay *= 2
    raise last  # type: ignore[misc]


def looks_complete(chart: dict) -> str | None:
    """Why this read can't be trusted as the whole chart, or None if it can. Guards the
    rebuild in sync_depth.py: a redesigned page that still returns 200 would otherwise
    replace the two-deep with nothing."""
    rows = chart["rows"]
    units = {r["unit"] for r in rows}
    starters = {r["position"] for r in rows if r["rank"] == 1}
    if not {"Offense", "Defense"} <= units:
        return f"missing a unit (got {sorted(units) or 'none'})"
    if "QB" not in starters:
        return "no QB row"
    if len([r for r in rows if r["unit"] != "Reserves"]) < 40:
        return f"only {len(rows)} players"
    return None


if __name__ == "__main__":
    chart = parse(fetch())
    print(f"Ourlads, updated {chart['updated']}: {len(chart['rows'])} players "
          f"({looks_complete(chart) or 'complete'})")
    for r in chart["rows"]:
        print(f"  {r['unit']:<13} {r['position']:<5} {r['rank']}  {r['player_name']}  {r['class_year'] or ''}")
