"""
Mountaineer Pulse - What the AI actually costs
==============================================
Reads the api_usage table and answers "what am I spending, and on what".

Run:  python read_usage.py [days]     (default 14)
"""

import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")


def main() -> None:
    if not SB_URL or not SB_KEY:
        print("\n[X] Missing SUPABASE_URL or SUPABASE_SECRET_KEY in .env")
        sys.exit(1)
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 14
    sb = create_client(SB_URL, SB_KEY)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    rows = (sb.table("api_usage").select("*")
            .gte("created_at", since).order("created_at").execute().data or [])
    if not rows:
        print(f"No API usage recorded in the last {days} days.")
        return

    by_day: dict[str, float] = defaultdict(float)
    by_script: dict[str, dict] = defaultdict(lambda: {"calls": 0, "cost": 0.0, "in": 0, "out": 0,
                                                      "searches": 0, "unpriced": 0})
    for r in rows:
        day = r["created_at"][:10]
        cost = float(r["cost_usd"] or 0)
        by_day[day] += cost
        s = by_script[r["script"]]
        s["calls"] += 1
        s["cost"] += cost
        s["in"] += r["input_tokens"] + r["cache_read"] + r["cache_write"]
        s["out"] += r["output_tokens"]
        s["searches"] += r["web_searches"]
        if r["cost_usd"] is None:
            s["unpriced"] += 1

    print(f"\nCLAUDE API USAGE — last {days} days ({len(rows)} calls)\n" + "=" * 62)
    print(f"\n{'BY SCRIPT':<22}{'calls':>6}{'in tok':>11}{'out tok':>9}{'search':>8}{'cost':>10}")
    print("-" * 62)
    for name, s in sorted(by_script.items(), key=lambda kv: -kv[1]["cost"]):
        flag = f"  ({s['unpriced']} unpriced)" if s["unpriced"] else ""
        print(f"{name:<22}{s['calls']:>6}{s['in']:>11,}{s['out']:>9,}"
              f"{s['searches']:>8}{'$' + format(s['cost'], '.2f'):>10}{flag}")

    total = sum(by_day.values())
    active = len(by_day)
    print("-" * 62)
    print(f"{'TOTAL':<22}{len(rows):>6}{'':>11}{'':>9}{'':>8}{'$' + format(total, '.2f'):>10}")

    print(f"\n{'BY DAY':<22}{'cost':>10}")
    print("-" * 32)
    for day in sorted(by_day)[-14:]:
        bar = "#" * min(40, int(by_day[day] / 0.02)) if by_day[day] else ""
        print(f"{day:<22}{'$' + format(by_day[day], '.2f'):>10}  {bar}")

    if active:
        per_day = total / active
        print(f"\naverage over {active} active day(s): ${per_day:.2f}/day"
              f"  ->  ${per_day * 30:.2f}/month, ${per_day * 365:.0f}/year")
        print("(the landing page quotes a yearly figure — keep it honest against this number)")

    unpriced = sum(s["unpriced"] for s in by_script.values())
    if unpriced:
        models = sorted({r["model"] for r in rows if r["cost_usd"] is None})
        print(f"\n{unpriced} call(s) had no price on file: {', '.join(models)}")
        print("Add them to usage.PRICES or the totals above understate the real bill.")


if __name__ == "__main__":
    main()
