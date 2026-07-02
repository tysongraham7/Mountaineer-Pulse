"""
Mountaineer Pulse - ESPN Source Spike (Basketball + Baseball)
=============================================================
Prove ESPN's unofficial JSON endpoints return WVU men's basketball and
baseball schedules/scores. WVU's ESPN team id is 277 across all sports.

Run:  python espn_spike.py
"""

import requests

TEAM_ID = "277"  # West Virginia Mountaineers

SPORTS = [
    ("mbb", "basketball/mens-college-basketball", "Men's Basketball"),
    ("baseball", "baseball/college-baseball", "Baseball"),
]

BASE = "https://site.api.espn.com/apis/site/v2/sports"


def fetch_schedule(path: str) -> dict:
    url = f"{BASE}/{path}/teams/{TEAM_ID}/schedule"
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    return r.json()


def main() -> None:
    for sport_id, path, label in SPORTS:
        print("\n" + "=" * 64)
        print(f"  {label}  (ESPN team 277)")
        print("=" * 64)
        data = fetch_schedule(path)

        season = data.get("season", {})
        print(f"Season: {season.get('year')} ({season.get('displayName', '')})")
        events = data.get("events", [])
        print(f"Events returned: {len(events)}\n")

        shown = 0
        for ev in events:
            comp = (ev.get("competitions") or [{}])[0]
            competitors = comp.get("competitors", [])
            status = (comp.get("status") or {}).get("type", {})
            completed = status.get("completed", False)

            home = away = None
            for c in competitors:
                side = c.get("homeAway")
                name = (c.get("team") or {}).get("displayName", "?")
                score = (c.get("score") or {})
                pts = score.get("value") if isinstance(score, dict) else score
                winner = c.get("winner")
                if side == "home":
                    home = (name, pts, winner)
                else:
                    away = (name, pts, winner)

            date = (ev.get("date") or "")[:10]
            if completed and home and away:
                aw = "W" if away[2] else ("L" if away[2] is False else "")
                print(f"  {date}  {away[0]} {away[1]} @ {home[0]} {home[1]}  [{status.get('description','')}]")
            elif home and away:
                print(f"  {date}  {away[0]} @ {home[0]}  (upcoming)")
            shown += 1
            if shown >= 8:
                print(f"  ... ({len(events) - shown} more)")
                break

    print("\n[OK] ESPN endpoints work for basketball + baseball.")


if __name__ == "__main__":
    main()
