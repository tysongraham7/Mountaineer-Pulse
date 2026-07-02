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
import os
import re
import sys

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


def scrape(url: str) -> list[dict]:
    html = requests.get(url, headers=UA, timeout=30).text
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

    sb.table("players").delete().neq("id", "___none___").execute()

    for sport_id, url in SPORTS:
        players = scrape(url)
        for p in players:
            p["sport_id"] = sport_id
        if players:
            sb.table("players").upsert(players).execute()
        withphoto = sum(1 for p in players if p["photo_url"])
        withtown = sum(1 for p in players if p["home_city"])
        print(f"  {sport_id:<9} {len(players)} players ({withphoto} photos, {withtown} hometowns)")

    print("\n[OK] Official rosters scraped to Supabase.")


if __name__ == "__main__":
    main()
