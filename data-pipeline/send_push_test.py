"""
Mountaineer Pulse - single-device push test
===========================================
send_push.py deliberately fans out to EVERY enabled token, which is right for the daily
briefing and wrong for testing: the app is live on iOS, so a "does Android work" test run
through it would ship the word "Test" to real users' lock screens.

This sends to exactly one device. By default it picks the most recently registered Android
token, which is almost always the phone you just installed on.

  python send_push_test.py                       # newest Android device
  python send_push_test.py --ios                 # newest iOS device
  python send_push_test.py --token ExponentPushToken[xxxx]
  python send_push_test.py --title "Hi" --body "There"

Prints the target and the Expo receipt so a silent failure is visible rather than assumed.
"""

import argparse
import sys

import requests
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

import os

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")
EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", help="exact Expo push token to target")
    ap.add_argument("--ios", action="store_true", help="newest iOS device instead of Android")
    ap.add_argument("--title", default="Mountaineer Pulse")
    ap.add_argument("--body", default="Android push is working. Let's go, Mountaineers!")
    ap.add_argument("--screen", help="deep-link target, e.g. pulse")
    a = ap.parse_args()

    token = a.token
    if not token:
        if not SB_URL or not SB_KEY:
            print("missing Supabase creds (.env)")
            return 1
        sb = create_client(SB_URL, SB_KEY)
        want = "ios" if a.ios else "android"
        rows = (
            sb.table("push_tokens")
            .select("token,platform,updated_at")
            .eq("enabled", True)
            .eq("platform", want)
            .order("updated_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
        if not rows:
            print(f"no enabled {want} device registered yet — open the app and turn alerts on first")
            return 1
        token = rows[0]["token"]
        print(f"target: newest {want} device, registered {rows[0]['updated_at']}")

    # Guard rail: one recipient, always. This script must never grow a loop.
    msg = {"to": token, "title": a.title, "body": a.body, "sound": "default"}
    if a.screen:
        msg["data"] = {"screen": a.screen}

    print(f"sending to 1 device: ...{token[-12:]}")
    resp = requests.post(EXPO_PUSH_URL, json=[msg], timeout=30,
                         headers={"Content-Type": "application/json"})
    receipt = (resp.json().get("data") or [{}])[0]
    status = receipt.get("status")
    print(f"receipt: {receipt}")
    if status == "ok":
        print("OK - accepted by Expo. If nothing appears on the device, the channel or the")
        print("     FCM V1 key is the problem, not the send.")
        return 0
    print("FAILED - see the error above")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
