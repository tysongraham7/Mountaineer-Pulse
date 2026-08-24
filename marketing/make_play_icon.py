"""
Google Play store icon (512x512)
================================
Play shows this on the listing and in search results. It is NOT the launcher icon that ships
inside the app — that one is built from the adaptive foreground/background at build time and
is masked to whatever shape the device uses. This is a flat square Play rounds itself.

Source is the same 1024px icon the App Store uses, so the two storefronts stay identical.

Two details Play cares about:
  * 32-bit PNG. The spec says so explicitly, so the output is RGBA even though the artwork is
    fully opaque — a 24-bit RGB file is the kind of thing that gets bounced at upload.
  * Fully opaque, edge to edge. Play applies its own corner rounding; a transparent margin
    would show as a shrunken icon floating inside the rounded square.

  python make_play_icon.py   ->  ./play/icon-512.png
"""

import os

from PIL import Image

SRC = "../mobile/assets/images/icon.png"
BACKDROP = (0, 40, 85)  # #002855, matching android.adaptiveIcon.backgroundColor in app.json

os.makedirs("play", exist_ok=True)
src = Image.open(SRC).convert("RGBA").resize((512, 512), Image.LANCZOS)

# Composite over the brand navy so any alpha in the source becomes opaque, then hand Play a
# 32-bit file: full alpha channel, no transparency.
out = Image.new("RGBA", (512, 512), (*BACKDROP, 255))
out.alpha_composite(src)

dst = os.path.join("play", "icon-512.png")
out.save(dst, "PNG")
kb = os.path.getsize(dst) / 1024
print(f"saved {dst}  {out.size}  {out.mode}  {kb:.0f} KB  (Play limit: 512x512, 32-bit, 1024 KB)")
