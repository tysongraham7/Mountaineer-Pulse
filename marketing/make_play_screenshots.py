"""
Google Play screenshot converter
================================
Play's phone slot has a hard rule the App Store doesn't: **aspect ratio may not exceed 2:1**.
The iPhone captures are 1284x2778 — a 2.164 ratio — so the files in ./store/ (1320x2868,
2.173) are rejected on upload. They are built for Apple's 6.9" slot and cannot be reused.

Fitting to WIDTH the way the App Store converter does would force a 176px vertical crop, and
on these captures the rows you'd lose are the status bar and the tab bar — the tab bar being
part of the app's identity, and the first thing a browsing user reads as "this is an app."

So this fits to HEIGHT instead and pads the sides. Nothing is cropped and nothing is
distorted. The pad extends each row's own edge pixel outward, which is invisible here because
the screenshots' left and right edges are already the app background (#060B16) for ~90% of
rows and a card edge (#0D1524) for the rest — extending a card row outward just reads as the
card reaching the canvas edge.

  python make_play_screenshots.py

Reads ./ , writes ./play/ as 01-*.png ... in submission order.
"""

import os

from PIL import Image

# 1080x2160 is exactly 2:1 — the ratio ceiling, which wastes the least horizontal space on
# a 2.164 source (41px of pad per side) while staying well inside Play's 320..3840px bounds.
TARGET_W, TARGET_H = 1080, 2160

# Same order as the App Store set: Play shows the first two or three in search results, so
# lead with the identity shot, then the feature no feed reader could imitate.
ORDER = [
    ("Home Page 1.png", "01-daily-briefing"),
    ("Pulse Chart.png", "02-pulse-chart"),
    ("Depth.png", "03-depth-chart"),
    ("Movement.png", "04-roster-movement"),
    ("Scores.png", "05-scores"),
    ("News.png", "06-news"),
]

OUT_DIR = "play"


def convert(src: str, dst: str) -> str:
    im = Image.open(src)
    if im.mode != "RGB":
        im = im.convert("RGB")  # flatten alpha; Play is fine with it but stores smaller

    # Fit inside the target box, preserving the source ratio. Whichever axis binds first
    # decides; for these captures it is always the height.
    scale = min(TARGET_W / im.width, TARGET_H / im.height)
    w, h = max(1, round(im.width * scale)), max(1, round(im.height * scale))
    im = im.resize((w, h), Image.LANCZOS)

    if (w, h) == (TARGET_W, TARGET_H):
        im.save(dst, "PNG")
        return f"scaled to {w}x{h}, exact"

    canvas = Image.new("RGB", (TARGET_W, TARGET_H))
    left, top = (TARGET_W - w) // 2, (TARGET_H - h) // 2
    canvas.paste(im, (left, top))

    # Extend the outermost column/row outward rather than filling flat, so card edges that
    # touch the frame stay continuous instead of stopping at a seam.
    if left:
        canvas.paste(im.crop((0, 0, 1, h)).resize((left, h)), (0, top))
        right = TARGET_W - w - left
        if right:
            canvas.paste(im.crop((w - 1, 0, w, h)).resize((right, h)), (left + w, top))
    if top:
        row = canvas.crop((0, top, TARGET_W, top + 1))
        canvas.paste(row.resize((TARGET_W, top)), (0, 0))
        bot = TARGET_H - h - top
        if bot:
            edge = canvas.crop((0, top + h - 1, TARGET_W, top + h))
            canvas.paste(edge.resize((TARGET_W, bot)), (0, TARGET_H - bot))

    canvas.save(dst, "PNG")
    pads = []
    if left:
        pads.append(f"{TARGET_W - w}px horizontal")
    if top:
        pads.append(f"{TARGET_H - h}px vertical")
    return f"scaled to {w}x{h}, padded " + " + ".join(pads)


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    for src, stem in ORDER:
        if not os.path.exists(src):
            print(f"  [skip] {src} not found")
            continue
        dst = os.path.join(OUT_DIR, f"{stem}.png")
        note = convert(src, dst)
        size = os.path.getsize(dst) / 1024
        print(f"  [OK] {stem}.png  {TARGET_W}x{TARGET_H}  {size:.0f} KB  - {note}")
    print(f"\nReady to upload from ./{OUT_DIR}/")


if __name__ == "__main__":
    main()
