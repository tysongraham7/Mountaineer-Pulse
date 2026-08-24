"""
Mountaineer Pulse - Analytics dashboard
=======================================
A dashboard that only exists while you're looking at it.

    python dashboard.py            # opens http://127.0.0.1:8787 in your browser
    python dashboard.py --port 9000
    python dashboard.py --no-browser
    python dashboard.py --print    # dump the numbers as JSON and exit, no server

Nothing runs in the background and nothing is deployed. Start it when you want to look,
Ctrl-C when you're done. The page pulls straight from Supabase on load and on Refresh, so
what you see is as live as the last event that landed.

It binds to 127.0.0.1 on purpose. This process holds SUPABASE_SECRET_KEY, which reads every
table including error reports and push tokens, so the server must not be reachable from
anywhere but this machine -- not the local network, not a tunnel. If you ever want this on
your phone, the answer is a hosted read-only aggregate, never exposing this port.

Needs SUPABASE_URL + SUPABASE_SECRET_KEY in .env, same as the other scripts here.
"""

import argparse
import json
import os
import sys
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv
from supabase import create_client

import metrics

load_dotenv()

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                             # noqa: BLE001
    pass

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")
HERE = Path(__file__).parent
PAGE = HERE / "dashboard.html"

# Re-fetching the whole event table on every keystroke of the day-range selector would be
# rude to Supabase and slow to read. Raw events are cached this long; switching the window
# recomputes from the cache instantly, and Refresh always bypasses it.
CACHE_SECONDS = 45


class Store:
    """The cached copy of the event table, shared across request threads."""

    def __init__(self, sb):
        self.sb = sb
        self.lock = threading.Lock()
        self.events: list[dict] | None = None
        self.fetched_at: float = 0.0

    def get(self, fresh: bool = False) -> tuple[list[dict], float]:
        with self.lock:
            age = datetime.now().timestamp() - self.fetched_at
            if fresh or self.events is None or age > CACHE_SECONDS:
                self.events = metrics.fetch_events(self.sb)
                self.fetched_at = datetime.now().timestamp()
            return self.events, self.fetched_at


def build_handler(store: Store):
    class Handler(BaseHTTPRequestHandler):
        # The default logger prints a line per request, which drowns the one line that
        # matters (the URL to open) the moment the page starts polling.
        def log_message(self, *_args):
            pass

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            # This page is for one reader on one machine; caching it only ever serves a
            # stale number to someone who pressed Refresh precisely to avoid one.
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):                                     # noqa: N802
            url = urlparse(self.path)
            if url.path in ("/", "/index.html"):
                try:
                    self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
                except OSError:
                    self._send(500, b"dashboard.html is missing next to dashboard.py",
                               "text/plain; charset=utf-8")
                return

            if url.path == "/api/metrics":
                q = parse_qs(url.query)
                days = _clamp_days(q.get("days", ["30"])[0])
                fresh = q.get("fresh", ["0"])[0] == "1"
                try:
                    events, at = store.get(fresh=fresh)
                    data = metrics.compute(events, days=days)
                    data["fetched_at"] = datetime.fromtimestamp(at).isoformat()
                    body = json.dumps(data).encode("utf-8")
                except Exception as e:                        # noqa: BLE001
                    # Surfaced in the page rather than only in the terminal -- an expired
                    # key or a dropped connection should say so where you're looking.
                    body = json.dumps({
                        "error": f"{e.__class__.__name__}: {e}"
                    }).encode("utf-8")
                    self._send(500, body, "application/json")
                    return
                self._send(200, body, "application/json")
                return

            self._send(404, b"not found", "text/plain; charset=utf-8")

    return Handler


def _clamp_days(raw: str) -> int:
    """A hand-edited ?days= shouldn't be able to ask for a million-day window."""
    try:
        return max(1, min(365, int(raw)))
    except ValueError:
        return 30


def serve(port: int, open_browser: bool) -> None:
    sb = create_client(SB_URL, SB_KEY)
    store = Store(sb)

    # Fetch before opening the browser so the first paint has data in it rather than a
    # spinner, and so a bad key fails here -- in the terminal, with a readable message --
    # instead of as a red box in the page.
    print("  Loading events from Supabase...")
    events, _ = store.get(fresh=True)
    print(f"  {len(events):,} events loaded.")

    # Port already in use is the one failure that's routine (a dashboard left open in
    # another window), so it gets a real suggestion rather than a traceback.
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), build_handler(store))
    except OSError as e:
        print(f"\n[X] Can't bind to port {port} -- {e.strerror or e}."
              f"\n    Another dashboard may already be running. Try --port {port + 1}.")
        sys.exit(1)

    url = f"http://127.0.0.1:{port}"
    print(f"\n  Mountaineer Pulse analytics -> {url}")
    print("  Local only. Ctrl-C to stop.\n")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
        httpd.server_close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Local analytics dashboard for Mountaineer Pulse.")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--days", type=int, default=30, help="window for --print")
    ap.add_argument("--no-browser", action="store_true", help="don't open a browser window")
    ap.add_argument("--print", dest="dump", action="store_true",
                    help="print the metrics as JSON and exit (no server)")
    args = ap.parse_args()

    if not SB_URL or not SB_KEY:
        print("\n[X] Missing SUPABASE_URL or SUPABASE_SECRET_KEY in .env")
        sys.exit(1)

    if args.dump:
        sb = create_client(SB_URL, SB_KEY)
        data = metrics.compute(metrics.fetch_events(sb), days=_clamp_days(str(args.days)))
        print(json.dumps(data, indent=2, default=str))
        return

    serve(args.port, not args.no_browser)


if __name__ == "__main__":
    main()
