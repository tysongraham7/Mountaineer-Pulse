"""
Mountaineer Pulse - Game Themes: wvusports.com -> Supabase
==========================================================
The promo attached to each home game — "All White for 5 (Wear WHITE)", "Gold Rush
(Wear GOLD)", "Stripe the Stadium", "Coal Rush (Wear BLACK)".

Worth having because it's the one piece of game-day information a fan has to ACT
on, and they have to know it before they leave the house. Everything else in a
preview can be read in the stadium; what color to wear cannot.

Scraped rather than typed. WVU publishes it on the schedule page's promotion
field, so it's real, it updates when they change it, and nobody has to remember
to enter next week's. The shape varies -- sometimes a bare string, sometimes an
object with a name -- and it mixes the theme with unrelated billing ("2026 Home
Opener", a sponsor logo), so parse() below keeps the part a fan would act on and
drops the rest.

Home games only. An away game's "promotion" belongs to the other school's
marketing department, not to anyone reading this app.

Brittleness: the same Nuxt hydration payload sync_rosters.py and sync_coaches.py
read. If WVU redesigns, this writes nothing rather than writing nonsense.

Run:  python sync_game_themes.py [--dry-run]
"""

import html as htmllib
import json
import os
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from supabase import create_client

from sync_rosters import fetch

load_dotenv()

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")

SCHEDULES = [
    ("football", "https://wvusports.com/sports/football/schedule"),
    ("mbb", "https://wvusports.com/sports/mens-basketball/schedule"),
]
EASTERN = ZoneInfo("America/New_York")
NUXT_RE = re.compile(
    r'<script type="application/json"[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', re.S)

# Billing that isn't a theme. These ride along in the same slash-separated string as the
# real one ("All White for 5 (Wear WHITE) / Pat White Number Retirement / 2026 Home
# Opener"), and none of them tells anyone what to wear or what the day is about.
NOISE = re.compile(
    r"^(20\d\d\s+)?(big 12\s+)?(home opener|season opener|conference opener|"
    r"family day|kids day|youth day)$", re.I)


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def payload(html: str):
    m = NUXT_RE.search(html)
    if not m:
        return None
    flat = json.loads(htmllib.unescape(m.group(1)))

    def resolve(idx, depth=0):
        if depth > 16 or not isinstance(idx, int) or not (0 <= idx < len(flat)):
            return idx
        node = flat[idx]
        if isinstance(node, list):
            return [resolve(i, depth + 1) for i in node]
        if isinstance(node, dict):
            return {k: resolve(v, depth + 1) for k, v in node.items()}
        return node

    events = {}
    for i, node in enumerate(flat):
        if isinstance(node, dict) and "opponent" in node and "promotion" in node:
            e = resolve(i)
            if e.get("id") is not None:
                events[e["id"]] = e
    return list(events.values())


def parse(promotion) -> str | None:
    """The wearable part of a promotion, or None.

    A string like "Gold Rush (Wear GOLD) / Big 12 Home Opener" carries the theme first and
    scheduling trivia after; an object carries a sponsor's day under `name`. Split on the
    slash, drop the noise, and keep what's left in the order WVU wrote it.
    """
    if isinstance(promotion, dict):
        promotion = promotion.get("name")
    if not isinstance(promotion, str):
        return None
    parts = [p.strip() for p in promotion.split("/")]
    kept = [p for p in parts if p and not NOISE.match(p)]
    return " · ".join(kept) or None


def eastern_day(iso: str | None) -> str | None:
    """The Eastern calendar date, which is the join key to `games` — a 7pm kickoff is the
    next day in UTC, and both feeds would then disagree about which day the game is."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:  # the site's local field is already Eastern
        return dt.date().isoformat()
    return dt.astimezone(EASTERN).date().isoformat()


def main() -> None:
    dry = "--dry-run" in sys.argv
    if not SB_URL or not SB_KEY:
        die("Missing SUPABASE_URL or SUPABASE_SECRET_KEY in .env")
    sb = create_client(SB_URL, SB_KEY)

    total = 0
    for sport, url in SCHEDULES:
        try:
            events = payload(fetch(url))
        except Exception as e:  # noqa: BLE001 — a themeless app is fine, a crashed sync isn't
            print(f"  [!] {sport}: {str(e)[:70]} — skipping")
            continue
        if not events:
            print(f"  [!] {sport}: no events parsed — leaving existing themes alone")
            continue

        # Home games only: locationIndicator 'H' (or the snake_case twin on the other shape).
        themes: dict[str, str] = {}
        for e in events:
            where = e.get("locationIndicator") or e.get("location_indicator")
            if where and str(where).upper() != "H":
                continue
            day = eastern_day(e.get("date") or e.get("dateUtc"))
            theme = parse(e.get("promotion"))
            if day and theme:
                themes[day] = theme

        rows = (sb.table("games").select("id,start_date,is_wvu_home,theme")
                .eq("sport_id", sport).eq("is_wvu_home", True).execute().data or [])
        updates = 0
        for g in rows:
            day = eastern_day(g.get("start_date"))
            theme = themes.get(day or "")
            if theme == (g.get("theme") or None):
                continue
            print(f"    {day}  {theme or '(cleared)'}")
            if not dry:
                sb.table("games").update({"theme": theme}).eq("id", g["id"]).execute()
            updates += 1
        print(f"  {sport:<9} {len(themes)} themes on the page, {updates} game rows changed")
        total += updates

    print(f"\n[OK] Game themes synced ({total} changed){' [dry run]' if dry else ''}.")


if __name__ == "__main__":
    main()
