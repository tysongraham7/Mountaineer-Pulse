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
    # The client (anon key) may register/update ONLY — it cannot read tokens (a leaked Expo
    # push token lets anyone notify that device). The backend reads them with the secret key,
    # which bypasses RLS.
    "drop policy if exists push_tokens_insert on push_tokens;",
    "create policy push_tokens_insert on push_tokens for insert to anon with check (true);",
    "drop policy if exists push_tokens_update on push_tokens;",
    "create policy push_tokens_update on push_tokens for update to anon using (true) with check (true);",
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
