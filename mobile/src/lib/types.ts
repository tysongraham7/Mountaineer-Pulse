export type Game = {
  id: number;
  sport_id: string;
  season: number;
  week: number | null;
  season_type: string | null;
  start_date: string | null;
  home_team: string;
  away_team: string;
  home_points: number | null;
  away_points: number | null;
  venue: string | null;
  status: string | null;
  is_wvu_home: boolean | null;
};

export type Player = {
  id: string;
  sport_id: string;
  season: number | null;
  first_name: string | null;
  last_name: string | null;
  jersey: number | null;
  position: string | null;
  height: number | null;
  weight: number | null;
  height_display: string | null;
  class_display: string | null;
  home_city: string | null;
  home_state: string | null;
  photo_url: string | null;
};

export type DepthEntry = {
  id: string;
  sport_id: string;
  season: number | null;
  unit: string | null;
  position: string;
  pos_order: number | null;
  rank: number;
  player_name: string;
  class_year: string | null;
  status: string | null; // active | questionable | doubtful | out
  note: string | null;
  alert: string | null; // short amber notice (e.g. drafted, likely to leave)
};

export type RosterMove = {
  id: string;
  sport_id: string | null;
  player_name: string;
  position: string | null;
  class_year: string | null;
  direction: string; // 'in' | 'out'
  category: string | null; // 'transfer' | 'recruit' | 'graduation' | 'draft'
  status: string | null;
  other_school: string | null;
  move_date: string | null;
  source_name: string | null;
  source_url: string | null;
  notes: string | null;
  impact: string | null; // 'high' = marquee
  alert: string | null; // short amber notice (e.g. drafted, likely to leave)
};

// Per-sport daily briefing (research-backed). `sections` is the structured form;
// `content` is a plain-text fallback for older clients.
export type BriefingItem = { topic: string; body: string };
export type BriefingSection = { sport: string; items: BriefingItem[] };
export type BriefingSections = { intro: string; sections: BriefingSection[] };
export type Briefing = {
  date: string;
  content: string;
  sections: BriefingSections | null;
};

export type PlayerStat = {
  id: string;
  player_id: string;
  season: number;
  sport_id: string | null;
  player_name: string | null;
  position: string | null;
  category: string;
  stat_type: string;
  stat: string | null;
  team: string | null;
};

export type TeamRecord = {
  id: number;
  sport_id: string;
  season: number;
  team: string;
  total_wins: number | null;
  total_losses: number | null;
  conference: string | null;
  conf_wins: number | null;
  conf_losses: number | null;
};
