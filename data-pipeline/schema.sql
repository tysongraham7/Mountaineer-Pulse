-- Mountaineer Pulse - Database Schema (M1: Football core)
-- Run this ONCE in the Supabase SQL Editor (Dashboard -> SQL Editor -> New query).
-- It is safe to re-run: every table uses "if not exists".
--
-- Design notes:
--  * M1 keeps team names denormalized as text on games/records for simplicity.
--    We can normalize into a teams table later without breaking the app.
--  * sport_id is text ('football','mbb','baseball') so adding sports later = just
--    new rows, no schema change.

-- ---------------------------------------------------------------------------
-- sports: the catalog of sports the app supports
-- ---------------------------------------------------------------------------
create table if not exists sports (
  id            text primary key,          -- 'football', 'mbb', 'baseball'
  name          text not null,
  season_active boolean default true,
  sort_order    int default 0
);

insert into sports (id, name, sort_order) values
  ('football', 'Football', 1),
  ('mbb',      'Men''s Basketball', 2),
  ('baseball', 'Baseball', 3)
on conflict (id) do nothing;

-- ---------------------------------------------------------------------------
-- games: schedule + scores
-- ---------------------------------------------------------------------------
create table if not exists games (
  id           bigint primary key,         -- CFBD game id
  sport_id     text not null default 'football' references sports(id),
  season       int not null,
  week         int,
  season_type  text,
  start_date   timestamptz,
  home_team    text not null,
  away_team    text not null,
  home_points  int,
  away_points  int,
  venue        text,
  status       text,                       -- 'scheduled' | 'final'
  is_wvu_home  boolean,
  updated_at   timestamptz default now()
);

create index if not exists games_sport_season_idx on games (sport_id, season);
create index if not exists games_start_idx on games (start_date);

-- ---------------------------------------------------------------------------
-- players: roster
-- ---------------------------------------------------------------------------
create table if not exists players (
  id          text primary key,            -- CFBD athlete id
  sport_id    text not null default 'football' references sports(id),
  season      int,
  first_name  text,
  last_name   text,
  jersey      int,
  position    text,
  height      int,                         -- inches
  weight      int,                         -- lbs
  class_year  int,                         -- 1..4ish
  home_city   text,
  home_state  text,
  photo_url      text,                      -- headshot (ESPN)
  height_display text,                      -- e.g. 6' 4"
  class_display  text,                      -- e.g. Junior
  updated_at  timestamptz default now()
);

create index if not exists players_sport_season_idx on players (sport_id, season);

-- ---------------------------------------------------------------------------
-- team_records: season record (feeds standings + Mountaineer Pulse)
-- ---------------------------------------------------------------------------
create table if not exists team_records (
  id           bigserial primary key,
  sport_id     text not null default 'football' references sports(id),
  season       int not null,
  team         text not null,
  total_wins   int,
  total_losses int,
  conference   text,
  conf_wins    int,
  conf_losses  int,
  updated_at   timestamptz default now(),
  unique (sport_id, season, team)
);

-- ---------------------------------------------------------------------------
-- Row Level Security: public READ-ONLY access (writes require the secret key,
-- which bypasses RLS). This is public sports data, no private user info.
-- Re-running create policy will error if the policy already exists; that's safe
-- to ignore, or drop first.
-- ---------------------------------------------------------------------------
alter table sports       enable row level security;
alter table games        enable row level security;
alter table players      enable row level security;
alter table team_records enable row level security;

create policy "public read sports"  on sports       for select using (true);
create policy "public read games"   on games        for select using (true);
create policy "public read players" on players       for select using (true);
create policy "public read records" on team_records  for select using (true);

-- ---------------------------------------------------------------------------
-- news_items: aggregated headlines (we store headline + source + link only,
-- and link OUT to the origin — we never copy article bodies).
-- ---------------------------------------------------------------------------
create table if not exists news_items (
  id           text primary key,          -- stable hash of source + headline
  sport_id     text references sports(id),-- classified sport, or null = general
  headline     text not null,
  source_name  text,
  url          text not null,
  published_at timestamptz,
  created_at   timestamptz default now()
);

create index if not exists news_published_idx on news_items (published_at desc);

alter table news_items enable row level security;
create policy "public read news" on news_items for select using (true);

-- ---------------------------------------------------------------------------
-- Mountaineer Pulse: per-sport snapshot (score + trend + AI explanation) and
-- the overall WVU athletics score. Numbers are computed by a deterministic
-- formula; the explanation text is the AI layer.
-- ---------------------------------------------------------------------------
create table if not exists pulse_snapshots (
  id          bigserial primary key,
  sport_id    text references sports(id),
  date        date not null,
  score       int,                       -- 0..100
  trend       text,                      -- 'up' | 'down' | 'neutral'
  ranking     int,                       -- national rank if available, else null
  explanation text,
  drivers     jsonb,                      -- transparent list of what's moving the score
  updated_at  timestamptz default now(),
  unique (sport_id, date)
);

create table if not exists pulse_overall (
  date       date primary key,
  score      int,
  summary    text,
  updated_at timestamptz default now()
);

alter table pulse_snapshots enable row level security;
alter table pulse_overall   enable row level security;
create policy "public read pulse"   on pulse_snapshots for select using (true);
create policy "public read overall" on pulse_overall   for select using (true);

-- ---------------------------------------------------------------------------
-- daily_briefings: the "3 biggest WVU stories in the last 24h", written by AI
-- from the news feed + Pulse. One per day.
-- ---------------------------------------------------------------------------
create table if not exists daily_briefings (
  id           bigserial primary key,
  date         date not null unique,
  content      text not null,
  generated_at timestamptz default now()
);

alter table daily_briefings enable row level security;
create policy "public read briefings" on daily_briefings for select using (true);

-- ---------------------------------------------------------------------------
-- daily_sport_notes: one grounded, AI-written news line of the day PER SPORT,
-- from that sport's classified news + the day's general WVU headlines.
-- sync_sport_notes.py writes these. The Pulse chart shows the note on that sport's
-- point for the day; `hype` marks BIG news (award/commit/ranking/win) that is the
-- ONLY kind allowed to bump the Pulse score (routine notes show but don't move it).
-- ---------------------------------------------------------------------------
create table if not exists daily_sport_notes (
  id         text primary key,            -- sport|date
  sport_id   text references sports(id),
  date       date not null,
  note       text not null,
  hype       boolean not null default false,  -- true = big news, feeds the Pulse bump
  created_at timestamptz default now()
);

create index if not exists daily_sport_notes_idx on daily_sport_notes (sport_id, date);

alter table daily_sport_notes enable row level security;
create policy "public read sport notes" on daily_sport_notes for select using (true);

-- ---------------------------------------------------------------------------
-- roster_moves: confirmed transfer portal entries (out) and commitments (in).
-- Curated (no free portal API). Feeds the Movement tab and the offseason Pulse.
-- ---------------------------------------------------------------------------
create table if not exists roster_moves (
  id           text primary key,          -- stable hash of player + direction
  sport_id     text references sports(id),
  player_name  text not null,
  position     text,
  class_year   text,
  direction    text not null,             -- 'in' | 'out'
  category     text default 'transfer',   -- 'transfer' | 'recruit' | 'graduation' | 'draft'
  status       text,                      -- 'entered' | 'committed' | 'confirmed' | 'signed' | 'drafted'
  other_school text,                      -- previous school (in) or next (out)
  move_date    date,
  source_name  text,
  source_url   text,
  notes        text,
  impact       text,                      -- 'high' = marquee add (5-star/high-major), weighs more in the Pulse
  created_at   timestamptz default now()
);

alter table roster_moves enable row level security;
create policy "public read moves" on roster_moves for select using (true);

-- ---------------------------------------------------------------------------
-- depth_chart: curated projected lineup by position. Absorbs injuries (status)
-- and departures/replacements. No official college source exists — founder
-- maintains data-pipeline/depth_chart.json from beat-writer projections.
-- ---------------------------------------------------------------------------
create table if not exists depth_chart (
  id          text primary key,          -- hash of sport + season + position + player
  sport_id    text references sports(id),
  season      int,                        -- e.g. 2027 (projected) or 2026; null = seasonless
  unit        text,                       -- Offense | Defense | Special Teams (football)
  position    text not null,              -- QB, RB, WR, ...
  pos_order   int default 0,              -- sort order for positions
  rank        int not null,              -- 1 = starter, 2 = backup, ...
  player_name text not null,
  class_year  text,
  status      text default 'active',      -- active | questionable | doubtful | out
  note        text,
  updated_at  timestamptz default now()
);

alter table depth_chart enable row level security;
create policy "public read depth" on depth_chart for select using (true);

-- ---------------------------------------------------------------------------
-- player_stats: per-season stat lines (long format) from CFBD. Prior seasons
-- populate now; the current season fills in once games are played. Keyed by
-- CFBD athlete id (= players.id), so a player's profile joins straight to it.
-- Not a FK to players -- we keep stat lines for players who have since left.
-- ---------------------------------------------------------------------------
create table if not exists player_stats (
  id          text primary key,           -- player_id|season|category|stat_type
  player_id   text not null,              -- CFBD athlete id (matches players.id)
  season      int not null,
  sport_id    text default 'football' references sports(id),
  player_name text,
  position    text,
  category    text not null,              -- passing | rushing | receiving | defensive | ...
  stat_type   text not null,             -- YDS | TD | INT | TOT | ...
  stat        text,                       -- value as reported by CFBD
  team        text default 'West Virginia', -- school stats were earned at (prev school for incoming transfers)
  updated_at  timestamptz default now()
);

create index if not exists player_stats_player_idx on player_stats (player_id, season);

alter table player_stats enable row level security;
create policy "public read player stats" on player_stats for select using (true);
