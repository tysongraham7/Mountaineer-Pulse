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
    # A move that's already reflected by a curated daily note carries pulse_neutral=true so the
    # Pulse math counts the event ONCE (via the note) instead of double-counting it here too.
    "alter table roster_moves add column if not exists pulse_neutral boolean not null default false;",
    "alter table depth_chart add column if not exists alert text;",
    "alter table daily_briefings add column if not exists sections jsonb;",
    # --- Official player bios (scraped from wvusports.com) ---
    # bio_url is stored, not derived: the app must link back to the source, since the
    # prose is WVU's writing and we display it under attribution.
    # --- Claude API usage, so the daily cost is measured rather than guessed ---
    """create table if not exists api_usage (
        id            bigserial primary key,
        script        text not null,        -- which pipeline step made the call
        model         text not null,
        input_tokens  int  not null default 0,
        output_tokens int  not null default 0,
        cache_read    int  not null default 0,
        cache_write   int  not null default 0,
        web_searches  int  not null default 0,
        cost_usd      numeric(10,5),        -- null when the model has no price on file
        created_at    timestamptz not null default now()
    );""",
    "create index if not exists api_usage_created_idx on api_usage (created_at desc);",
    # api_usage is internal cost telemetry — the app never reads it, only the pipeline writes
    # it (with the secret key, which bypasses RLS) and read_usage.py reads it. It shipped
    # without RLS, and Supabase grants anon full DML on public tables by default, so the
    # publishable key inside every install could read the spend or TRUNCATE the table.
    # RLS on with NO policy is the correct shape here: same pattern as error_reports reads.
    "alter table api_usage enable row level security;",
    "alter table players add column if not exists bio text;",
    "alter table players add column if not exists bio_url text;",
    "alter table players add column if not exists bio_fetched_at timestamptz;",
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
    # `notified` = has this report already triggered an email alert? Set true after a successful
    # send (notify_reports.py) so each report emails exactly once. Client can't set it (insert-only).
    "alter table error_reports add column if not exists notified boolean not null default false;",
    # Random per-install reporter id, used ONLY to rate-limit. Deliberately a different id from
    # analytics_events.anon_id so a report can't be joined to that install's browsing history.
    "alter table error_reports add column if not exists anon_id text;",
    "create index if not exists error_reports_created_idx on error_reports (created_at desc);",
    "create index if not exists error_reports_anon_idx on error_reports (anon_id, created_at desc);",
    # Size/shape guards. The app already caps message length, but the app is not the only thing
    # that can reach this table — the publishable key ships inside every install, so anyone can
    # POST here directly. Enforce it where it can't be bypassed.
    """do $$ begin
        if not exists (select 1 from pg_constraint where conname = 'error_reports_message_len') then
            alter table error_reports add constraint error_reports_message_len
                check (char_length(message) between 1 and 2000);
        end if;
        if not exists (select 1 from pg_constraint where conname = 'error_reports_category_ok') then
            alter table error_reports add constraint error_reports_category_ok
                check (category is null or category in ('data','bug','idea','other'));
        end if;
    end $$;""",
    # Rate limit, enforced in the INSERT policy itself.
    #   * security definer  -> the function reads error_reports as the owner, so it isn't blocked
    #                          by this same RLS policy (and can't recurse into it).
    #   * stable            -> evaluated against the statement snapshot, so the row being inserted
    #                          isn't counted; the Nth insert in the window is the one refused.
    #   * global cap        -> the only limit that survives someone randomizing their anon_id.
    """create or replace function public.error_reports_allowed(p_anon text)
    returns boolean
    language sql
    stable
    security definer
    set search_path = public, pg_temp
    as $$
        select (
            select count(*) from public.error_reports
            where created_at > now() - interval '1 hour'
        ) < 300
        and (
            p_anon is null
            or (
                select count(*) from public.error_reports
                where anon_id = p_anon and created_at > now() - interval '1 hour'
            ) < 5
        );
    $$;""",
    # The client may submit reports ONLY — it cannot read them back (reports may contain other
    # users' words; nothing in the app lists them). No select policy => reads denied to all but
    # the secret key (read_reports.py). `to public` (not `to anon`) for the same reason as
    # push_tokens above: the sb_publishable_ key isn't matched by a `to anon` policy.
    # Kill switch if this is ever abused: alter the policy to `with check (false)` to freeze
    # all inbound reports without touching the app.
    "drop policy if exists error_reports_insert on error_reports;",
    """create policy error_reports_insert on error_reports for insert to public
       with check (public.error_reports_allowed(anon_id));""",
    # --- Anonymous, privacy-first usage analytics ---
    # Random per-install id (NOT a device id, no PII), so we can count daily-active users,
    # push opens, and which tabs get used — without identifying anyone. Insert-only for the
    # client (same model as error_reports/push_tokens): the app writes events but can never
    # read them back; the founder reads aggregates server-side via read_analytics.py.
    """create table if not exists analytics_events (
        id          bigint generated always as identity primary key,
        anon_id     text not null,
        event       text not null,        -- 'app_open' | 'screen_view' | 'push_open'
        screen      text,                 -- route/tab for screen_view
        platform    text,
        app_version text,
        created_at  timestamptz not null default now()
    );""",
    "create index if not exists analytics_events_created_idx on analytics_events (created_at desc);",
    "create index if not exists analytics_events_anon_idx on analytics_events (anon_id);",
    "alter table analytics_events enable row level security;",
    "drop policy if exists analytics_insert on analytics_events;",
    "create policy analytics_insert on analytics_events for insert to public with check (true);",
    # --- Breaking-news push (notify_news.py) ---
    # When this headline was pushed to devices. NULL = never pushed. This is the ONLY thing
    # stopping a repeating scan from re-alerting the same story every run, and it doubles as
    # the daily-cap counter (count today's non-null rows), so no separate push log is needed.
    "alter table news_items add column if not exists notified_at timestamptz;",
    "create index if not exists news_items_notified_idx on news_items (notified_at desc);",
    # check_unlanded_alerts.py: one "the app didn't catch up" nag per pushed alert.
    "alter table news_items add column if not exists unlanded_flagged_at timestamptz;",
    # notify_news.py: in-app context for a pushed story, so tapping an alert doesn't dead-end.
    "alter table news_items add column if not exists summary text;",
    "alter table news_items add column if not exists summary_section text;",
    "alter table news_items add column if not exists summary_headline text;",
    # notify_games.py: one kickoff reminder and one final score per game, never repeated.
    "alter table games add column if not exists notified_kickoff_at timestamptz;",
    "alter table games add column if not exists notified_final_at timestamptz;",
    # --- Game-day scouting report (generate_matchup.py) ---
    # One row per upcoming game. Keyed by game_id so a regenerated preview overwrites rather
    # than accumulating, and so it disappears naturally if a game is ever removed.
    """create table if not exists matchups (
        game_id      bigint primary key,
        sport_id     text references sports(id),
        kickoff      timestamptz,
        opponent     text,
        sections     jsonb,                 -- structured report the app renders
        content      text,                  -- plain-text fallback for older clients
        generated_at timestamptz not null default now()
    );""",
    "create index if not exists matchups_kickoff_idx on matchups (kickoff);",
    "alter table matchups enable row level security;",
    "drop policy if exists \"public read matchups\" on matchups;",
    "create policy \"public read matchups\" on matchups for select using (true);",
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
