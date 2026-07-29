"""
App Store screenshot converter
==============================
iPhone screen captures come out at that device's native size (a 6.7" phone gives 1284x2778),
but App Store Connect wants the 6.9" slot: 1320x2868. Those are slightly different aspect
ratios (2.1636 vs 2.1727), so a plain resize would either squash the image or crop content.

Instead: scale to the target WIDTH, then pad the few missing rows top and bottom by stretching
the image's own edge rows. On a dark UI whose top is the status bar and bottom is the tab bar,
the pad is invisible — and nothing gets cropped or distorted.

Also flattens alpha: App Store Connect rejects screenshots with an alpha channel.

  python make_store_screenshots.py

Reads ./ , writes ./store/ as 01-*.png ... in submission order.
"""

import os

from PIL import Image

TARGET_W, TARGET_H = 1320, 2868  # iPhone 6.9" display

# Submission order. The first one or two are what show in App Store search results, so lead
# with the identity shot, then the feature no feed reader could imitate.
ORDER = [
    ("Home Page 1.png", "01-daily-briefing"),
    ("Pulse Chart.png", "02-pulse-chart"),
    ("Depth.png", "03-depth-chart"),
    ("Movement.png", "04-roster-movement"),
    ("Scores.png", "05-scores"),
    ("News.png", "06-news"),
]

OUT_DIR = "store"


def convert(src: str, dst: str) -> str:
    im = Image.open(src)
    if im.mode != "RGB":
        im = im.convert("RGB")  # drop alpha — App Store Connect rejects it

    if im.size == (TARGET_W, TARGET_H):
        im.save(dst, "PNG")
        return "already exact"

    # Scale to the target width, preserving the source aspect ratio.
    h = round(im.height * TARGET_W / im.width)
    im = im.resize((TARGET_W, h), Image.LANCZOS)

    if h == TARGET_H:
        im.save(dst, "PNG")
        return f"scaled to {TARGET_W}x{h}"

    if h > TARGET_H:
        # Source is taller than the slot — trim equally from top and bottom.
        top = (h - TARGET_H) // 2
        im = im.crop((0, top, TARGET_W, top + TARGET_H))
        im.save(dst, "PNG")
        return f"scaled then trimmed {h - TARGET_H}px"

    # Source is shorter — pad, extending the edge rows so the seam is invisible.
    pad = TARGET_H - h
    top = pad // 2
    canvas = Image.new("RGB", (TARGET_W, TARGET_H))
    canvas.paste(im, (0, top))
    if top:
        canvas.paste(im.crop((0, 0, TARGET_W, 1)).resize((TARGET_W, top)), (0, 0))
    bottom = pad - top
    if bottom:
        edge = im.crop((0, h - 1, TARGET_W, h)).resize((TARGET_W, bottom))
        canvas.paste(edge, (0, TARGET_H - bottom))
    canvas.save(dst, "PNG")
    return f"scaled to {TARGET_W}x{h}, padded {pad}px (top {top} / bottom {bottom})"


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    for src, stem in ORDER:
        if not os.path.exists(src):
            print(f"  [skip] {src} not found")
            continue
        dst = os.path.join(OUT_DIR, f"{stem}.png")
        note = convert(src, dst)
        size = os.path.getsize(dst) / 1024
        print(f"  [OK] {stem}.png  {TARGET_W}x{TARGET_H}  {size:.0f} KB  — {note}")
    print(f"\nReady to upload from ./{OUT_DIR}/")


if __name__ == "__main__":
    main()
