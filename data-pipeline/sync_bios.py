"""
Mountaineer Pulse - Official Player Bios: wvusports.com -> Supabase
==================================================================
Pulls each player's official bio from their wvusports.com roster page.

Why this matters more than it sounds: CFBD box scores can't describe an
offensive lineman -- the position records no countable stats, anywhere, ever.
The official bio does: "1,750 snaps over 33 career starts, has not allowed a
sack in his career." It also covers D2/JUCO arrivals and true freshmen that no
stats API carries, and sometimes names a previous school the portal feed missed.

The prose is WVU's writing, so every bio is stored with the URL it came from and
the app displays it under attribution with a link back.

Cadence: bios change a few times a year, not nightly. Only players missing a bio
or older than STALE_DAYS are fetched, so a normal run makes almost no requests.

Brittleness: the bio lives in the page's Nuxt hydration payload, not a stable
API -- same tradeoff sync_rosters.py takes. If WVU redesigns, this exits non-zero
rather than quietly blanking every bio.

Run:  python sync_bios.py [--force] [--limit N]
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv
from supabase import create_client

from sync_rosters import fetch

load_dotenv()

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120 Safari/537.36"}

# Same roster pages sync_rosters.py scrapes — one Sidearm layout across all three.
SPORTS = [
    ("football", "https://wvusports.com/sports/football/roster"),
    ("mbb", "https://wvusports.com/sports/mens-basketball/roster"),
    ("baseball", "https://wvusports.com/sports/baseball/roster"),
]
SITE = "https://wvusports.com"
STALE_DAYS = 30          # refresh a bio at most monthly
REQUEST_PAUSE = 0.6      # be a polite scraper
# Below this success rate on attempted fetches, assume the page changed shape.
MIN_SUCCESS_RATE = 0.5

# A bio is a JSON string of escaped HTML inside the hydration payload. Anchor on a
# length floor plus list markup so we don't match incidental strings.
BIO_STRING_RE = re.compile(r'"((?:[^"\\]|\\.){200,})"')
LINK_RE = re.compile(r'href="(/sports/[^"]+/roster/[a-z0-9.\-]+/(\d+))"')


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def parse_ts(stamp: str):
    """Parse a Postgres timestamptz, or None if it can't be read.

    Postgres emits however many fractional-second digits it has ('...:09.6702+00'),
    while datetime.fromisoformat before 3.11 accepts only 3 or 6 -- so the obvious
    parse works on the first run and throws on every run after it.
    """
    s = stamp.replace("Z", "+00:00")
    m = re.match(r"^(.*\.)(\d+)(.*)$", s)
    if m:
        s = m.group(1) + m.group(2)[:6].ljust(6, "0") + m.group(3)
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def html_to_text(fragment: str) -> str:
    """Flatten the bio's <h2>/<ul> markup into headed, bulleted plain text."""
    t = fragment
    t = re.sub(r"</h2\s*>", "\n", t, flags=re.I)
    t = re.sub(r"<li[^>]*>", "• ", t, flags=re.I)
    t = re.sub(r"</li\s*>", "\n", t, flags=re.I)
    t = re.sub(r"</(ul|ol|p|div)\s*>", "\n", t, flags=re.I)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = (t.replace("&nbsp;", " ").replace("&amp;", "&").replace("&quot;", '"')
          .replace("&#39;", "'").replace("&lt;", "<").replace("&gt;", ">"))
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in t.split("\n")]
    return "\n".join(ln for ln in lines if ln).strip()


def extract_bio(page: str) -> str | None:
    """Return the bio as plain text, or None if this page has no bio block."""
    best = None
    for m in BIO_STRING_RE.finditer(page):
        blob = m.group(1)
        if "\\u003Cli>" in blob and (best is None or len(blob) > len(best)):
            best = blob
    if not best:
        return None
    try:
        # json.loads resolves the \uXXXX escapes correctly; decoding by hand with
        # unicode_escape mangles anything non-ASCII into mojibake.
        fragment = json.loads(f'"{best}"')
    except json.JSONDecodeError:
        return None
    text = html_to_text(fragment)
    return text or None


def bio_urls(roster_url: str) -> dict[str, str]:
    """player id (as on the site) -> absolute bio URL, read off the roster page."""
    # Same retrying fetch as everywhere else here: this one page failing used to abort the
    # whole bio sync before a single player was looked at.
    page = fetch(roster_url)
    urls = {pid: SITE + path for path, pid in LINK_RE.findall(page)}
    if not urls:
        die(f"no player links found on {roster_url} -- the markup changed")
    return urls


def sync_sport(sb, sport: str, roster_url: str, force: bool, limit: int | None) -> None:
    players = sb.table("players").select(
        "id,first_name,last_name,bio,bio_fetched_at").eq("sport_id", sport).execute().data or []

    cutoff = datetime.now(timezone.utc) - timedelta(days=STALE_DAYS)

    def needs_fetch(p: dict) -> bool:
        if force or not p.get("bio"):
            return True
        stamp = p.get("bio_fetched_at")
        if not stamp:
            return True
        when = parse_ts(stamp)
        return when is None or when < cutoff  # unreadable stamp -> refetch

    todo = [p for p in players if needs_fetch(p)]
    if limit:
        todo = todo[:limit]
    print(f"\n{sport}: {len(players)} players -- {len(todo)} need a bio fetch")
    if not todo:
        print("   all current")
        return

    urls = bio_urls(roster_url)

    updated, no_bio, no_link, failed = 0, [], [], []
    for i, p in enumerate(todo, 1):
        name = f"{p.get('first_name') or ''} {p.get('last_name') or ''}".strip()
        site_id = p["id"].replace("wvu_", "")
        url = urls.get(site_id)
        if not url:
            no_link.append(name)
            continue
        try:
            # Retries with backoff: a single 30s timeout used to drop the player silently,
            # and 12 were lost that way in one run on 2026-08-19.
            page = fetch(url)
        except requests.RequestException as e:
            failed.append(f"{name} ({e.__class__.__name__})")
            continue
        bio = extract_bio(page)
        if not bio:
            # A real state, not an error: freshmen sometimes have an empty bio.
            no_bio.append(name)
            continue
        # Only ever write a bio we actually got. A blank extraction must never
        # overwrite good prose already in the database.
        sb.table("players").update({
            "bio": bio,
            "bio_url": url,
            "bio_fetched_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", p["id"]).execute()
        updated += 1
        if i % 20 == 0:
            print(f"   ...{i}/{len(todo)}")
        time.sleep(REQUEST_PAUSE)

    attempted = len(todo) - len(no_link)
    print(f"   {updated} bios written")
    if no_bio:
        print(f"   {len(no_bio)} page(s) had no bio yet: {', '.join(no_bio[:12])}"
              f"{' ...' if len(no_bio) > 12 else ''}")
    if no_link:
        print(f"   {len(no_link)} not linked from the roster page: {', '.join(no_link[:12])}")
    if failed:
        print(f"   {len(failed)} fetch failure(s): {', '.join(failed[:12])}")

    # A collapse in the success rate means the page shape changed. Say so loudly --
    # a silent no-op would leave stale bios looking current.
    if attempted and (updated + len(no_bio)) / attempted < MIN_SUCCESS_RATE:
        die(f"only {updated}/{attempted} {sport} bios extracted -- wvusports.com markup "
            f"likely changed; sync_bios.py needs updating")


def main() -> None:
    if not SB_URL or not SB_KEY:
        die("Missing SUPABASE_URL or SUPABASE_SECRET_KEY in .env")
    force = "--force" in sys.argv
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    only = None
    if "--sport" in sys.argv:
        only = sys.argv[sys.argv.index("--sport") + 1]

    sb = create_client(SB_URL, SB_KEY)
    for sport, roster_url in SPORTS:
        if only and sport != only:
            continue
        sync_sport(sb, sport, roster_url, force, limit)

    print("\n[OK] Player bios synced to Supabase.")


if __name__ == "__main__":
    main()
