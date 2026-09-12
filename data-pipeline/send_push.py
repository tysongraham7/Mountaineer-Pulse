"""
Mountaineer Pulse - Push Notifications sender
=============================================
Sends notifications to every registered device via the Expo Push API. Device push
tokens are stored in the `push_tokens` table (written by the app; read here with the
SECRET key, which bypasses RLS). Import send_push() from the pipeline to notify on
notable events (e.g. the daily briefing). Tokens Expo reports as unregistered are
auto-disabled so we stop sending to dead devices.

Run directly to send a test:  python send_push.py "Title" "Body"
"""

import os
import sys

import requests
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

# Titles/bodies carry emoji (e.g. the briefing's 🏔️); keep Windows' cp1252
# console from crashing on the status print after a send already went out.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")
EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"

# GLOBAL KILL SWITCH. True = no notification leaves this process, whatever calls it.
#
# Off again now that the thing it was protecting against is fixed properly. It went on after
# two bad alerts out of the three ever sent — a duplicate about Evans Barning Jr., then a
# SOCCER result announced as a basketball win — and it stays here because a push cannot be
# unsent and one switch beats disabling four workflows in a hurry.
#
# What changed: breaking news no longer sends itself. notify_news.py writes to pending_alerts
# and emails the proposed text; approve_alert.py is the only path to a phone, and it runs when
# a person taps Run workflow. So the judgment that produced both bad alerts can no longer
# reach anyone on its own.
#
# Still automatic, deliberately:
#   game day  - notify_games.py has no model in it at all, only rows from the games table,
#               so there is nothing for it to invent. It has to be live for Sept 5.
#   briefing  - a daily digest with a templated title; it has never misfired, and it is now
#               skipped entirely on days when nothing happened.
PUSH_PAUSED = False


def _enabled_tokens(sb) -> list[str]:
    rows = sb.table("push_tokens").select("token").eq("enabled", True).execute().data
    return [r["token"] for r in rows if (r.get("token") or "").startswith("ExponentPushToken")]


def send_push(title: str, body: str, data: dict | None = None,
              tokens: list[str] | None = None) -> int:
    """Send one notification to every enabled device. Returns how many were accepted.
    Safe to call anytime: a no-op (returns 0) if creds or devices are missing.

    `tokens` narrows the audience to those devices — watch_game.py uses it to send a
    touchdown only to people who asked for every score. Omitted, everyone enabled gets it."""
    if PUSH_PAUSED:
        # Loud, and prints what WOULD have gone out, so a paused run is still reviewable in
        # the Actions log — that is how you find out whether the judgment is improving.
        print(f"  PUSH PAUSED — nothing sent. Would have been:\n    {title}\n    {body}")
        return 0
    if not SB_URL or not SB_KEY:
        print("  (push skipped: missing Supabase creds)")
        return 0
    sb = create_client(SB_URL, SB_KEY)
    if tokens is None:
        tokens = _enabled_tokens(sb)
    if not tokens:
        print("  (push skipped: no registered devices)")
        return 0

    base = {"title": title, "body": body, "sound": "default"}
    if data:
        base["data"] = data
    messages = [{"to": t, **base} for t in tokens]

    sent = 0
    for i in range(0, len(messages), 100):  # Expo accepts up to 100 per request
        batch = messages[i:i + 100]
        try:
            resp = requests.post(EXPO_PUSH_URL, json=batch, timeout=30,
                                 headers={"Content-Type": "application/json"})
            receipts = resp.json().get("data", [])
            for msg, r in zip(batch, receipts):
                if r.get("status") == "ok":
                    sent += 1
                elif r.get("details", {}).get("error") == "DeviceNotRegistered":
                    sb.table("push_tokens").update({"enabled": False}).eq("token", msg["to"]).execute()
        except Exception as e:
            print(f"  (push batch failed: {str(e)[:120]})")
    print(f"  push -> {sent}/{len(tokens)} devices: {title}")
    return sent


if __name__ == "__main__":
    # python send_push.py "Title" "Body" [screen]
    # `screen` deep-links the tap target (e.g. "pulse"), matching what the daily
    # briefing sends. Omit it and the notification just opens the app.
    t = sys.argv[1] if len(sys.argv) > 1 else "Mountaineer Pulse"
    b = sys.argv[2] if len(sys.argv) > 2 else "Push notifications are live. Let's go, Mountaineers!"
    screen = sys.argv[3] if len(sys.argv) > 3 else None
    send_push(t, b, data={"screen": screen} if screen else None)
