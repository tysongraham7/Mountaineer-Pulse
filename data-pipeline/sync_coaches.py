"""
Mountaineer Pulse - Coaching Staff: wvusports.com -> Supabase
=============================================================
Scrapes the official coaches page for football, men's basketball and baseball,
then each coach's own bio page, and writes name/title/photo/bio plus two things
the roster pipeline has no equivalent of: where a coach has been, and what he
won there.

Why this is worth scraping rather than writing by hand: WVU authors each coach
page as free HTML, and inside it are three hand-built tables that happen to be
exactly the answer to the two questions fans ask about a hire --

  "Personal Information"  hometown, degrees, playing career
  "Coaching History"      every stop, with years and role
  School | Record | ...   win-loss at each stop, ending in a career total

The tables are consistent across all three sports because they come from the
same internal template, so parsing them is far more reliable than reading a
career record out of prose. Where a coach has no record table -- an analyst, a
position coach, a baseball head coach whose page skips it -- the fields simply
come back empty and the app shows what exists.

Deliberately not stored: the staff directory's email addresses and phone
numbers. Public on the page, useless in a fan app, and a work phone number
pushed to strangers is a different thing from a win-loss record.

Brittleness: the coach object lives in the page's Nuxt hydration payload, the
same tradeoff sync_rosters.py and sync_bios.py already take. If WVU redesigns,
this exits non-zero rather than quietly emptying the staff list.

Cadence: staffs change a few times a year. The three list pages are read every
run; a coach's own page is only refetched when he's new or his row is older
than STALE_DAYS, so a normal night makes three requests.

Run:  python sync_coaches.py [--force] [--limit N] [--dry-run]
"""

import html as htmllib
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv
from supabase import create_client

# Both already exist for the roster scrape, and both solve a problem this file has too:
# fetch() insists on a complete document (a truncated 1MB page parses to zero coaches and
# looks like an empty staff), and parse_ts() works around Postgres emitting however many
# fractional-second digits it happens to have. Imported rather than copied so a fix to
# either keeps applying here.
from sync_bios import parse_ts
from sync_rosters import fetch

load_dotenv()

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")

SITE = "https://wvusports.com"
SPORTS = [
    ("football", "/sports/football/coaches"),
    ("mbb", "/sports/mens-basketball/coaches"),
    ("baseball", "/sports/baseball/coaches"),
]
STALE_DAYS = 30
REQUEST_PAUSE = 0.6
# Below this success rate on attempted bio fetches, assume the page changed shape rather
# than writing a staff full of blanks over a good one.
MIN_SUCCESS_RATE = 0.5

NUXT_RE = re.compile(
    r'<script type="application/json"[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', re.S)
ROW_RE = re.compile(r"(?is)<tr\b.*?</tr>")
CELL_RE = re.compile(r"(?is)<t[dh]\b[^>]*>(.*?)</t[dh]>")
TABLE_RE = re.compile(r"(?is)<table\b.*?</table>")
COACH_HREF_RE = re.compile(r'href="(/sports/[^"]+/coaches/[a-z0-9.\-]+/(\d+))"')
# WVU's own page writes Hodge's career winning percentage as "213-62 (775)". Everywhere
# else on the site it's "(.775)", so this is a typo in their HTML, not a different stat.
PCT_TYPO_RE = re.compile(r"\((\d{3})\)")


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def text_of(fragment: str) -> str:
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", fragment)
    t = re.sub(r"(?i)<br[^>]*>", " ", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = htmllib.unescape(t).replace("\xa0", " ")
    return re.sub(r"\s+", " ", t).strip()


def prose_of(bio_html: str) -> str:
    """The bio with its tables removed, as paragraphs. The tables are pulled out into
    columns of their own, and left in they'd read as a wall of numbers on a phone."""
    t = TABLE_RE.sub(" ", bio_html)
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", t)
    t = re.sub(r"(?i)<(br|/p|/div|/li|/h\d)[^>]*>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = htmllib.unescape(t).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in t.split("\n")]
    # "The Rodriguez File" is the heading over the tables we just removed, and a bare
    # "Follow @RealCoachRod" is the social link. Neither means anything on its own.
    drop = re.compile(r"^(follow\s*@|the .+ file$)", re.I)
    keep = [ln for ln in lines if len(ln) > 1 and not drop.match(ln)]
    return "\n".join(keep).strip()


def tables_of(bio_html: str) -> list[list[list[str]]]:
    out = []
    for tm in TABLE_RE.finditer(bio_html):
        rows = []
        for rm in ROW_RE.finditer(tm.group(0)):
            cells = [text_of(cm.group(1)) for cm in CELL_RE.finditer(rm.group(0))]
            cells = [c for c in cells if c]
            if cells:
                rows.append(cells)
        if rows:
            out.append(rows)
    return out


def fix_pct(value: str) -> str:
    return PCT_TYPO_RE.sub(r"(.\1)", value or "")


def parse_bio_tables(bio_html: str) -> dict:
    """Pull the three known tables out of a coach bio into flat fields."""
    personal: dict[str, str] = {}
    history: list[dict] = []
    career: list[dict] = []
    career_record: str | None = None

    for rows in tables_of(bio_html):
        head = [c.lower() for c in rows[0]]
        first = head[0] if head else ""

        if first.startswith("personal information"):
            for r in rows[1:]:
                if len(r) >= 2:
                    personal[r[0].rstrip(":").strip().lower()] = r[1]

        elif first.startswith("coaching history"):
            for r in rows[1:]:
                if len(r) < 2:
                    continue
                # "Glenville State - Head Coach"; the dash is theirs, and a role can itself
                # contain slashes ("Offensive Coordinator/Quarterbacks Coach").
                school, _, role = r[1].partition(" - ")
                history.append({
                    "years": r[0],
                    "school": school.strip(" -"),
                    "role": role.strip(" -") or None,
                })

        elif first == "school" and "record" in head:
            for r in rows[1:]:
                row = {"school": r[0],
                       "record": fix_pct(r[1]) if len(r) > 1 else None,
                       "conf": fix_pct(r[2]) if len(r) > 2 else None,
                       "notes": r[3] if len(r) > 3 else None}
                if re.search(r"\btotals?\b", r[0], re.I):
                    career_record = row["record"]
                else:
                    career.append(row)

        elif first == "year" and "record" in head:
            # Year-by-year. Only used when there's no school-by-school table -- basketball
            # head coaches get this one instead, with a "<School> Totals" row per stop.
            for r in rows[1:]:
                if not re.search(r"\btotals?\b", r[0], re.I):
                    continue
                label = re.sub(r"\s*\btotals?\b\s*$", "", r[0], flags=re.I).strip()
                rec = fix_pct(r[1]) if len(r) > 1 else None
                if label.lower() in ("career", ""):
                    career_record = career_record or rec
                else:
                    career.append({"school": label, "record": rec,
                                   "conf": fix_pct(r[2]) if len(r) > 2 else None,
                                   "notes": None})

    return {
        "hometown": personal.get("hometown"),
        "education": personal.get("education"),
        "playing_career": personal.get("playing career"),
        "history": history,
        "career": career,
        "career_record": career_record,
    }


def record_from_prose(prose: str) -> str | None:
    """Fallback for a coach with no record table. Only a sentence that says outright this
    is the career head-coaching mark counts -- a bio is full of other people's records,
    single-season lines and 'his teams went' asides, and picking one of those and calling
    it a career record would be worse than showing nothing."""
    m = re.search(
        r"compiled a (?:career )?record of (\d+-\d+(?:-\d+)?)\s*(\([.\d]+\))?"
        r"[^.]{0,60}\bas a head coach\b",
        prose, re.I)
    if not m:
        m = re.search(
            r"\bis (\d+-\d+(?:-\d+)?)\s*(\([.\d]+\))?[^.]{0,40}\bas a head coach\b",
            prose, re.I)
    if not m:
        return None
    return fix_pct(" ".join(p for p in m.groups() if p))


def first_year_at_wvu(history: list[dict]) -> str | None:
    """The start year of the most recent West Virginia stint. 'Present' in the years cell
    is how the page marks the current job, but Sabins' page writes his as '2025-', so the
    test is the school, not the word."""
    for row in reversed(history):
        if "west virginia" in (row.get("school") or "").lower():
            m = re.match(r"(\d{4})", row.get("years") or "")
            if m:
                return m.group(1)
    return None


def headshot(absolute_url: str | None) -> str | None:
    """Same Sidearm crop the roster photos use, so a coach and a player render alike."""
    if not absolute_url:
        return None
    from urllib.parse import quote
    return ("https://images.sidearmdev.com/crop?url=" + quote(absolute_url, safe="") +
            "&width=300&height=300&gravity=north&type=webp")


def coach_object(page_html: str) -> dict | None:
    """Resolve the Nuxt hydration payload and return the page's coach record.

    The payload is devalue-flattened: a flat array where a container's values are indices
    into that same array. One level of indirection only -- a number stored AT an index is a
    literal, not another reference, and following it further lands on unrelated nodes."""
    m = NUXT_RE.search(page_html)
    if not m:
        return None
    flat = json.loads(htmllib.unescape(m.group(1)))

    def resolve(idx, depth=0):
        if depth > 14 or not isinstance(idx, int) or not (0 <= idx < len(flat)):
            return idx
        node = flat[idx]
        if isinstance(node, list):
            return [resolve(i, depth + 1) for i in node]
        if isinstance(node, dict):
            return {k: resolve(v, depth + 1) for k, v in node.items()}
        return node

    for i, node in enumerate(flat):
        if isinstance(node, dict) and "isHeadCoach" in node and "displayFields" in node:
            return resolve(i)
    return None


def list_staff(list_url: str) -> list[dict]:
    """The staff table: name, title and bio link, in the order the page prints them.

    That order is the org chart -- head coach, coordinators, position coaches, analysts --
    so it's stored and used for sorting instead of anything we'd invent."""
    html = fetch(list_url)
    staff: list[dict] = []
    seen: set[str] = set()
    for rm in ROW_RE.finditer(html):
        row = rm.group(0)
        hm = COACH_HREF_RE.search(row)
        if not hm:
            continue
        cid = hm.group(2)
        if cid in seen:
            continue
        cells = [text_of(cm.group(1)) for cm in CELL_RE.finditer(row)]
        if not cells or not cells[0]:
            continue
        seen.add(cid)
        staff.append({
            "coach_id": cid,
            "href": hm.group(1),
            "name": cells[0],
            "title": cells[1] if len(cells) > 1 else None,
            "sort_order": len(staff),
        })
    return staff


def build_row(sport_id: str, entry: dict) -> dict | None:
    page = fetch(SITE + entry["href"])
    obj = coach_object(page)
    if not obj:
        return None

    bio_html = obj.get("bio") or ""
    parsed = parse_bio_tables(bio_html)
    prose = prose_of(bio_html)
    title = (obj.get("title") or entry.get("title") or "").strip()

    name = entry["name"]
    first = (obj.get("firstName") or "").strip()
    last = (obj.get("lastName") or "").strip()
    if not first and not last:
        parts = name.split()
        first, last = (parts[0] if parts else name), " ".join(parts[1:])

    career_record = parsed["career_record"] or record_from_prose(prose)

    return {
        "id": f"wvu_{entry['coach_id']}",
        "sport_id": sport_id,
        "first_name": first,
        "last_name": last,
        "title": title or None,
        "is_head": title.lower() == "head coach",
        "sort_order": entry["sort_order"],
        "photo_url": headshot((obj.get("image") or {}).get("absoluteUrl")),
        "hometown": parsed["hometown"],
        "education": parsed["education"],
        "playing_career": parsed["playing_career"],
        "career_record": career_record,
        "first_year": first_year_at_wvu(parsed["history"]),
        "career": parsed["career"] or None,
        "history": parsed["history"] or None,
        "bio": prose or None,
        "bio_url": SITE + entry["href"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    force = "--force" in sys.argv
    dry = "--dry-run" in sys.argv
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    if not SB_URL or not SB_KEY:
        die("Missing SUPABASE_URL or SUPABASE_SECRET_KEY in .env")
    sb = create_client(SB_URL, SB_KEY)

    existing = {r["id"]: r for r in
                sb.table("coaches").select("id,sport_id,updated_at").execute().data}
    cutoff = datetime.now(timezone.utc) - timedelta(days=STALE_DAYS)

    attempted = succeeded = 0
    for sport_id, path in SPORTS:
        print(f"\n{sport_id}: reading staff list...")
        try:
            staff = list_staff(SITE + path)
        except requests.RequestException as e:
            print(f"  [!] could not read the list page ({str(e)[:60]}) — leaving {sport_id} alone")
            continue
        if not staff:
            print(f"  [!] no coaches parsed — leaving {sport_id} alone rather than emptying it")
            continue
        print(f"  {len(staff)} on the staff page")

        # Two lists, not one: PostgREST rejects a batch whose objects don't all carry the
        # same keys, and a title-only refresh is deliberately a different shape from a
        # freshly-scraped row.
        rows: list[dict] = []
        touch: list[dict] = []
        keep_ids = {f"wvu_{s['coach_id']}" for s in staff}
        for entry in staff:
            cid = f"wvu_{entry['coach_id']}"
            prev = existing.get(cid)
            seen_at = parse_ts(prev["updated_at"]) if prev else None
            fresh = bool(seen_at and not force and seen_at > cutoff)
            if fresh:
                # Still refresh the cheap fields from the list page: a promotion changes a
                # title long before anyone rewrites the bio behind it.
                touch.append({"id": cid, "sport_id": sport_id, "title": entry["title"],
                              "is_head": (entry["title"] or "").lower() == "head coach",
                              "sort_order": entry["sort_order"]})
                continue
            if limit is not None and attempted >= limit:
                continue

            attempted += 1
            try:
                row = build_row(sport_id, entry)
            except requests.RequestException as e:
                print(f"    [!] {entry['name']}: {str(e)[:60]}")
                continue
            if not row:
                print(f"    [!] {entry['name']}: no coach payload on the page")
                continue
            succeeded += 1
            rows.append(row)
            bits = []
            if row["career_record"]:
                bits.append(row["career_record"])
            if row["history"]:
                bits.append(f"{len(row['history'])} stops")
            print(f"    {row['first_name']} {row['last_name']} — {row['title']}"
                  + (f" ({', '.join(bits)})" if bits else ""))
            time.sleep(REQUEST_PAUSE)

        if dry:
            print(f"  [dry-run] would write {len(rows)} rows and refresh "
                  f"{len(touch)} titles for {sport_id}")
            continue

        if rows:
            sb.table("coaches").upsert(rows).execute()
        if touch:
            sb.table("coaches").upsert(touch).execute()
        # Anyone we have on file for this sport who isn't on the page any more has left.
        gone = [cid for cid, r in existing.items()
                if r["sport_id"] == sport_id and cid not in keep_ids]
        if gone:
            sb.table("coaches").delete().in_("id", gone).execute()
            print(f"  removed {len(gone)} no longer on staff")
        print(f"  wrote {len(rows)} rows, refreshed {len(touch)} titles")

    if attempted and succeeded / attempted < MIN_SUCCESS_RATE:
        die(f"Only {succeeded}/{attempted} bio pages parsed — the page shape probably changed.")

    print(f"\n[OK] Coaching staffs synced ({succeeded}/{attempted} bio pages fetched).")


if __name__ == "__main__":
    main()
