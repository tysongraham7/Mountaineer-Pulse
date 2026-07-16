"""
One-off / idempotent schema migration for the news-driven Pulse feature.
Adds:
  * daily_sport_notes.pulse_delta  (signed Pulse move per note)
  * roster_moves.alert             (short amber player notice)
  * depth_chart.alert              (short amber player notice)
Then tells PostgREST to reload its schema cache so the REST API sees the new
columns immediately (otherwise upserts referencing them fail until it refreshes).

Needs SUPABASE_URL + SUPABASE_DB_PASSWORD in .env.
Run:  python migrate.py
"""

import os
import sys
from urllib.parse import urlparse

import psycopg2
from dotenv import load_dotenv

load_dotenv()

ALTERS = [
    "alter table daily_sport_notes add column if not exists pulse_delta int not null default 0;",
    "alter table roster_moves add column if not exists alert text;",
    "alter table depth_chart add column if not exists alert text;",
    "alter table daily_briefings add column if not exists sections jsonb;",
    # --- Push notifications: device push tokens ---
    """create table if not exists push_tokens (
        token       text primary key,
        platform    text,
        enabled     boolean not null default true,
        created_at  timestamptz not null default now(),
        updated_at  timestamptz not null default now()
    );""",
    "alter table push_tokens enable row level security;",
    # The client may register/update ONLY — it cannot read tokens (a leaked Expo push token
    # lets anyone notify that device). With RLS on and NO select policy, reads are denied to
    # everyone but the secret key (which bypasses RLS). Policies target `public` (not `anon`):
    # the sb_publishable_ key resolves to a role matched by `public` but not `anon`, so a
    # `to anon` policy would silently never apply and every insert would fail RLS.
    "drop policy if exists push_tokens_insert on push_tokens;",
    "create policy push_tokens_insert on push_tokens for insert to public with check (true);",
    "drop policy if exists push_tokens_update on push_tokens;",
    "create policy push_tokens_update on push_tokens for update to public using (true) with check (true);",
    # --- In-app error / feedback reports ---
    """create table if not exists error_reports (
        id           uuid primary key default gen_random_uuid(),
        category     text,
        message      text not null,
        context      jsonb,
        app_version  text,
        platform     text,
        resolved     boolean not null default false,
        created_at   timestamptz not null default now()
    );""",
    "alter table error_reports enable row level security;",
    # The client may submit reports ONLY — it cannot read them back (reports may contain other
    # users' words; nothing in the app lists them). No select policy => reads denied to all but
    # the secret key (read_reports.py). `to public` (not `to anon`) for the same reason as
    # push_tokens above: the sb_publishable_ key isn't matched by a `to anon` policy.
    "drop policy if exists error_reports_insert on error_reports;",
    "create policy error_reports_insert on error_reports for insert to public with check (true);",
]


def main() -> None:
    url = os.getenv("SUPABASE_URL")
    pw = os.getenv("SUPABASE_DB_PASSWORD")
    if not url or not pw:
        print("[X] Missing SUPABASE_URL or SUPABASE_DB_PASSWORD in .env")
        sys.exit(1)
    ref = urlparse(url).hostname.split(".")[0]  # gutsqtshsjjkbydjuojk

    # Try the direct DB host first, then the shared pooler (some networks need it).
    hosts = [
        (f"db.{ref}.supabase.co", 5432, "postgres"),
        (f"aws-0-us-east-1.pooler.supabase.com", 6543, f"postgres.{ref}"),
        (f"aws-0-us-east-2.pooler.supabase.com", 6543, f"postgres.{ref}"),
    ]
    conn = None
    for host, port, user in hosts:
        try:
            conn = psycopg2.connect(host=host, port=port, user=user, password=pw,
                                    dbname="postgres", sslmode="require", connect_timeout=10)
            print(f"[OK] connected via {host}:{port}")
            break
        except Exception as e:
            print(f"    ({host}:{port} failed: {str(e)[:80]})")
    if conn is None:
        print("[X] Could not connect to the database on any known host.")
        sys.exit(1)

    conn.autocommit = True
    with conn.cursor() as cur:
        for sql in ALTERS:
            cur.execute(sql)
            print(f"  applied: {sql}")
        cur.execute("notify pgrst, 'reload schema';")
        print("  reloaded PostgREST schema cache")
    conn.close()
    print("\n[OK] Migration complete.")


if __name__ == "__main__":
    main()
