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

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")
EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


def _enabled_tokens(sb) -> list[str]:
    rows = sb.table("push_tokens").select("token").eq("enabled", True).execute().data
    return [r["token"] for r in rows if (r.get("token") or "").startswith("ExponentPushToken")]


def send_push(title: str, body: str, data: dict | None = None) -> int:
    """Send one notification to every enabled device. Returns how many were accepted.
    Safe to call anytime: a no-op (returns 0) if creds or devices are missing."""
    if not SB_URL or not SB_KEY:
        print("  (push skipped: missing Supabase creds)")
        return 0
    sb = create_client(SB_URL, SB_KEY)
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
    t = sys.argv[1] if len(sys.argv) > 1 else "Mountaineer Pulse"
    b = sys.argv[2] if len(sys.argv) > 2 else "Push notifications are live. Let's go, Mountaineers!"
    send_push(t, b)
