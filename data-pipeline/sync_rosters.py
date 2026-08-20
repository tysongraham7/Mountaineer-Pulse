"""
Mountaineer Pulse - Roster Pipeline: wvusports.com (official) -> Supabase
========================================================================
Scrapes the OFFICIAL WVU athletics site (Sidearm platform) for accurate,
current rosters across football, men's basketball, and baseball — including
photos, position, class, height/weight, and hometown.

Why not an API: ESPN/CFBD serve stale offseason rosters (departed seniors still
listed, signees missing, no baseball). The official site is hand-maintained and
correct. Tradeoff: scraping is brittle if they redesign — revisit if it breaks.

Run:  python sync_rosters.py
"""

import html as htmllib
import json
import os
import re
import sys
import time

import requests
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120 Safari/537.36"}
SEASON = 2026

SPORTS = [
    ("football", "https://wvusports.com/sports/football/roster"),
    ("mbb", "https://wvusports.com/sports/mens-basketball/roster"),
    ("baseball", "https://wvusports.com/sports/baseball/roster"),
]


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def strip_tags(s: str) -> str:
    return htmllib.unescape(re.sub(r"<[^>]+>", " ", s))


def parse_card(block: str) -> dict | None:
    m_link = re.search(r'href="/sports/[^"]+/roster/([a-z0-9.\-]+)/(\d+)"', block)
    m_aria = re.search(r'aria-label="([^"]+?) full bio"', block)
    if not m_link or not m_aria:
        return None
    pid = m_link.group(2)
    aria = htmllib.unescape(m_aria.group(1))
    name = re.sub(r"\s+jersey number\s+\d+\s*$", "", aria).strip()

    # Collapse visible text; fields appear as "Label value" in a fixed order:
    # Jersey Number, <name>, Position, Academic Year, Height, Weight, Hometown, Last School.
    text = re.sub(r"\s+", " ", strip_tags(block))

    def grab(pattern: str) -> str | None:
        m = re.search(pattern, text)
        return m.group(1).strip() if m else None

    jersey_raw = grab(r"Jersey Number (\d+)")
    jersey = int(jersey_raw) if jersey_raw else None
    position = grab(r"Position (.+?) (?:Academic Year|Height|Weight|Hometown|Last School|Full)")
    class_display = grab(r"Academic Year (.+?) (?:Height|Weight|Hometown|Last School|Full)")
    height_display = grab(r"Height (.+?) (?:Weight|Hometown|Last School|Full)")
    weight_raw = grab(r"Weight (\d+)")
    weight = int(weight_raw) if weight_raw else None
    hometown = grab(r"Hometown (.+?) (?:Last School|Full)")

    home_city = home_state = None
    if hometown:
        if "," in hometown:
            home_city, home_state = [x.strip() for x in hometown.split(",", 1)]
        else:
            home_city = hometown

    # Photo from the first webp srcset; bump the crop size for a crisp profile.
    photo = None
    mp = re.search(r'srcset="(https://images\.sidearmdev\.com/crop\?url=[^"]+?type=webp)"', block)
    if mp:
        photo = htmllib.unescape(mp.group(1))
        photo = re.sub(r"width=\d+", "width=300", photo)
        photo = re.sub(r"height=\d+", "height=300", photo)

    parts = name.split()
    return {
        "id": f"wvu_{pid}",
        "season": SEASON,
        "first_name": parts[0] if parts else name,
        "last_name": " ".join(parts[1:]) if len(parts) > 1 else "",
        "jersey": jersey,
        "position": position,
        "height": None,
        "weight": weight,
        "height_display": height_display,
        "class_display": class_display,
        "home_city": home_city,
        "home_state": home_state,
        "photo_url": photo,
    }


def fetch(url: str, attempts: int = 3) -> str:
    """GET with retries. wvusports.com intermittently takes well over 30s to answer, and a
    single timeout used to abort the whole sync — which, before the reordering above, meant
    an emptied roster table. Backs off between tries and raises only if all of them fail."""
    delay = 5.0
    last: Exception | None = None
    for i in range(1, attempts + 1):
        try:
            html = requests.get(url, headers=UA, timeout=60).text
            # A truncated body is the dangerous failure: these pages are ~4MB and a short
            # read returns without raising, then parses to zero players and looks like an
            # empty roster rather than a network problem. Insist the document is complete.
            if "</html>" not in html[-2000:]:
                raise requests.RequestException(
                    f"incomplete response ({len(html)} bytes, no closing </html>)")
            return html
        except requests.RequestException as e:
            last = e
            if i < attempts:
                print(f"    (fetch failed {type(e).__name__} — retry {i}/{attempts - 1} in {delay:.0f}s)")
                time.sleep(delay)
                delay *= 2
    raise last  # type: ignore[misc]


def scrape(url: str) -> list[dict]:
    html = fetch(url)
    starts = [m.start() for m in re.finditer(r'class="[^"]*s-person-card--list', html)]
    players, seen = [], set()
    for i, start in enumerate(starts):
        block = html[start: starts[i + 1] if i + 1 < len(starts) else start + 6000]
        p = parse_card(block)
        if p and p["id"] not in seen:
            seen.add(p["id"])
            players.append(p)
    return players


def main() -> None:
    if not SB_URL or not SB_KEY:
        die("Missing SUPABASE_URL or SUPABASE_SECRET_KEY in .env")
    sb = create_client(SB_URL, SB_KEY)

    # The rebuild below wipes the row, and bios live on it -- written by sync_bios.py, not
    # scraped here. Losing them nightly would mean re-fetching 175 pages from wvusports.com
    # every run instead of the handful that actually changed, which is both slow and rude.
    # Carry them across the rebuild; a player who drops off the roster loses his with the row.
    kept = {
        r["id"]: r
        for r in (sb.table("players").select("id,bio,bio_url,bio_fetched_at")
                  .execute().data or [])
        if r.get("bio")
    }

    # Scrape EVERYTHING before touching the table. This used to delete first and scrape
    # after, so a single slow response from wvusports.com left the app with an empty roster:
    # on 2026-08-19 a read timeout on the baseball page wiped all 48 baseball players and
    # left them gone. A failed scrape must cost nothing.
    scraped: list[tuple[str, list]] = []
    for sport_id, url in SPORTS:
        players = scrape(url)
        if not players:
            die(f"{sport_id}: scrape returned no players — refusing to rebuild the roster "
                f"(existing rows left untouched).")
        for p in players:
            p["sport_id"] = sport_id
        scraped.append((sport_id, players))

    # Every page answered, so it is safe to swap.
    sb.table("players").delete().neq("id", "___none___").execute()

    carried = 0
    for sport_id, players in scraped:
        for p in players:
            prev = kept.get(p["id"])
            if prev:
                p["bio"] = prev["bio"]
                p["bio_url"] = prev["bio_url"]
                p["bio_fetched_at"] = prev["bio_fetched_at"]
                carried += 1
        sb.table("players").upsert(players).execute()
        withphoto = sum(1 for p in players if p["photo_url"])
        withtown = sum(1 for p in players if p["home_city"])
        print(f"  {sport_id:<9} {len(players)} players ({withphoto} photos, {withtown} hometowns)")

    # Curated additions, applied AFTER the rebuild so they survive the wipe. For players the
    # official roster page has dropped but who are on the team — Brenen Lorient won his
    # eligibility back in court while wvusports.com still showed last season's roster, so the
    # scrape could not see him and he appeared with no photo, bio or stats. Remove an entry
    # here once the official page catches up and the scrape takes over.
    add_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "roster_additions.json")
    try:
        with open(add_path, encoding="utf-8") as f:
            additions = [{k: v for k, v in a.items() if not k.startswith("_")}
                         for a in json.load(f)]
    except (OSError, ValueError):
        additions = []
    if additions:
        # Don't fight the scrape: if the official page now lists them, its row wins.
        have = {r["id"] for r in (sb.table("players").select("id").execute().data or [])}
        fresh = [a for a in additions if a.get("id") not in have]
        if fresh:
            sb.table("players").upsert(fresh).execute()
        print(f"  curated additions: {len(fresh)} added, {len(additions) - len(fresh)} "
              f"already on the official roster")

    # The mirror of additions: players wvusports.com STILL lists who have actually left.
    # The official page lags a departure by days — Evans Barning Jr. was reported gone on
    # 2026-08-19 and was still on the page that night — so without this the scrape puts a
    # departed player back on the roster every single run, contradicting the Movement tab.
    # Matched on NAME, not id: a scraped id is only stable while the page keeps listing him,
    # and the whole point here is that the page will eventually drop him. Delete an entry
    # once the official page catches up; a stale entry is harmless (it matches nobody).
    rm_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "roster_removals.json")
    try:
        with open(rm_path, encoding="utf-8") as f:
            removals = json.load(f)
    except (OSError, ValueError):
        removals = []
    gone = 0
    for r in removals:
        sport, name = r.get("sport_id"), (r.get("player_name") or "").strip()
        if not sport or not name:
            continue
        first, _, last = name.partition(" ")
        hit = (sb.table("players").select("id,first_name,last_name")
               .eq("sport_id", sport).eq("first_name", first).execute().data or [])
        for row in hit:
            if f'{row["first_name"]} {row["last_name"]}'.strip().lower() == name.lower():
                sb.table("players").delete().eq("id", row["id"]).execute()
                gone += 1
    if removals:
        print(f"  curated removals: {gone} of {len(removals)} still on the official page")

    print(f"  bios carried across the rebuild: {carried}/{len(kept)}")
    print("\n[OK] Official rosters scraped to Supabase.")


if __name__ == "__main__":
    main()
