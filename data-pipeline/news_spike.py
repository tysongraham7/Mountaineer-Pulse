"""
Mountaineer Pulse - News Source Spike
=====================================
Prove we can pull current WVU sports headlines from Google News RSS
(headline + source + link + timestamp), which we link OUT to.

Run:  python news_spike.py
"""

import html
import xml.etree.ElementTree as ET
import requests

# Google News RSS search feed. Broad WVU sports query.
QUERY = '"West Virginia" Mountaineers (football OR basketball OR baseball)'
URL = (
    "https://news.google.com/rss/search"
    f"?q={requests.utils.quote(QUERY)}&hl=en-US&gl=US&ceid=US:en"
)


def main() -> None:
    resp = requests.get(URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)

    items = root.findall(".//item")
    print(f"Pulled {len(items)} WVU headlines from Google News RSS\n")
    print("=" * 70)

    for item in items[:12]:
        title = html.unescape(item.findtext("title") or "")
        link = item.findtext("link") or ""
        pub = item.findtext("pubDate") or ""
        source_el = item.find("source")
        source = source_el.text if source_el is not None else "?"
        # Google News titles are usually "Headline - Source"; keep clean headline.
        clean = title.rsplit(" - ", 1)[0] if title.endswith(source or "") else title
        print(f"\n[{source}]  {pub[:16]}")
        print(f"  {clean}")
        print(f"  {link[:90]}...")

    print("\n" + "=" * 70)
    print("[OK] News source works — real WVU headlines, with source + link.")


if __name__ == "__main__":
    main()
