"""
Mountaineer Pulse - Read in-app error / feedback reports
========================================================
Users can flag wrong data or send feedback from the app (You tab -> "Report a
data error"). Those land in the `error_reports` table, which the app itself
cannot read back (anon insert-only RLS). This script reads them with the secret
key and prints the unresolved ones so the founder can act.

  python read_reports.py            # show unresolved reports (newest first)
  python read_reports.py --all      # include resolved ones too
  python read_reports.py --resolve <id>   # mark one report resolved

Needs SUPABASE_URL + SUPABASE_SECRET_KEY in .env.
"""

import json
import os
import sys

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

# Windows consoles default to cp1252 and choke on the "·" separators below.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")

CATEGORY_LABEL = {
    "data": "Wrong data / stat",
    "bug": "Something's broken",
    "idea": "Feature idea",
    "other": "Other",
}


def main() -> None:
    if not SB_URL or not SB_KEY:
        print("[X] Missing SUPABASE_URL or SUPABASE_SECRET_KEY in .env")
        sys.exit(1)
    sb = create_client(SB_URL, SB_KEY)

    args = sys.argv[1:]
    if args and args[0] == "--resolve":
        if len(args) < 2:
            print("[X] Usage: python read_reports.py --resolve <report-id>")
            sys.exit(1)
        sb.table("error_reports").update({"resolved": True}).eq("id", args[1]).execute()
        print(f"[OK] Marked {args[1]} resolved.")
        return

    show_all = "--all" in args
    q = sb.table("error_reports").select("*").order("created_at", desc=True)
    if not show_all:
        q = q.eq("resolved", False)
    reports = q.execute().data or []

    if not reports:
        print("No reports." if show_all else "No open reports.")
        return

    label = "reports" if show_all else "open reports"
    print(f"\n{len(reports)} {label} (newest first)\n" + "=" * 60)
    for r in reports:
        cat = CATEGORY_LABEL.get(r.get("category"), r.get("category") or "—")
        when = (r.get("created_at") or "")[:16].replace("T", " ")
        flag = " [RESOLVED]" if r.get("resolved") else ""
        meta = " · ".join(
            x for x in (r.get("platform"), f"v{r['app_version']}" if r.get("app_version") else None) if x
        )
        print(f"\n[{cat}]{flag}  {when}   {meta}")
        ctx = r.get("context")
        if ctx:
            if isinstance(ctx, str):
                try:
                    ctx = json.loads(ctx)
                except ValueError:
                    ctx = None
            if isinstance(ctx, dict) and ctx:
                where = " · ".join(f"{k}={v}" for k, v in ctx.items() if v)
                if where:
                    print(f"  where: {where}")
        print(f"  {r.get('message', '').strip()}")
        print(f"  id: {r.get('id')}")
    print("\n" + "=" * 60)
    print("Resolve one with:  python read_reports.py --resolve <id>")


if __name__ == "__main__":
    main()
