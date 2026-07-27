"""
Mountaineer Pulse - Email sender (Resend)
=========================================
One place to send a plain-text alert email, used by notify_reports.py and check_stale_facts.py.
Uses Resend (https://resend.com) — a single API key, no SMTP / 2-Step / app passwords.

Env:
  RESEND_API_KEY   - your Resend API key (re_...)               [required to send]
  REPORT_ALERT_TO  - who to email                               [required to send]
  RESEND_FROM      - sender; defaults to Resend's shared address [optional]

Free-tier note: without a verified domain, Resend only sends FROM onboarding@resend.dev and
only TO the email your Resend account is registered under — which is exactly the "email myself
alerts" case here. To send from your own domain / to other addresses, verify a domain in Resend
and set RESEND_FROM.

Env is read at call time (after load_dotenv), so importing this module early is safe.
"""

import os

import requests

DEFAULT_FROM = "Mountaineer Pulse <onboarding@resend.dev>"


def _config() -> tuple[str | None, str, str | None]:
    return (
        os.getenv("RESEND_API_KEY"),
        os.getenv("RESEND_FROM") or DEFAULT_FROM,
        os.getenv("REPORT_ALERT_TO"),
    )


def email_configured() -> bool:
    """True if we have what we need to send. Callers check this for a graceful skip."""
    key, _, to = _config()
    return bool(key and to)


def send_email(subject: str, body: str) -> None:
    """Send a plain-text email via Resend. Raises on failure (caller decides how to handle)."""
    key, sender, to = _config()
    if not key or not to:
        raise RuntimeError("email not configured (RESEND_API_KEY / REPORT_ALERT_TO)")
    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"from": sender, "to": [to], "subject": subject, "text": body},
        timeout=30,
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"Resend API {resp.status_code}: {resp.text[:200]}")
