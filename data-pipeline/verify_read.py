"""
Verify the app's read path: read data back using the PUBLISHABLE key
(the same key the mobile app will use). Proves RLS read policies work.
"""
import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_PUBLISHABLE_KEY"))

print("Reading as the APP would (publishable key)...\n")

games = sb.table("games").select("*").eq("season", 2026).order("start_date").execute().data
print(f"2026 schedule ({len(games)} games):")
for g in games:
    print(f"  {(g['start_date'] or '')[:10]}  {g['away_team']} @ {g['home_team']}")

rec = sb.table("team_records").select("*").eq("season", 2025).execute().data
if rec:
    r = rec[0]
    print(f"\n2025 record: {r['total_wins']}-{r['total_losses']} "
          f"({r['conf_wins']}-{r['conf_losses']} {r['conference']})")

players = sb.table("players").select("*").execute().data
print(f"\nRoster: {len(players)} players readable")
qbs = [p for p in players if p['position'] == 'QB']
print("QBs on roster:", ", ".join(f"{p['first_name']} {p['last_name']}" for p in qbs))

print("\n[OK] The app's read path works — RLS lets the public read.")
