"""
App Store "hero panel" screenshots — ESPN-style
===============================================
Instead of shipping a raw device capture, each App Store slot becomes a designed panel:

    - full-bleed brand color background
    - a big bold-italic all-caps headline at the top
    - a hairline rule running edge to edge THROUGH the headline (knocked out around the
      text) and a second rule lower down. Because both rules sit at the same y on every
      panel and bleed off both sides, they line up as the user swipes — the six panels
      read as one continuous strip rather than six unrelated images.
    - the real capture in a device frame, bleeding off the bottom edge

Headline face is Archivo 900 Black Italic, the same family the app ships (mobile/src/
constants/brand.ts Font.black), so the store page and the app read as one brand.

  python make_hero_screenshots.py            # gold panels (default)
  python make_hero_screenshots.py --theme navy
  python make_hero_screenshots.py --theme alternating

Reads ./ , writes ./store-hero/ as 01-*.png ... in submission order. Output is
1320x2868 (iPhone 6.9" slot), RGB — App Store Connect rejects an alpha channel.
"""

import argparse
import os

from PIL import Image, ImageDraw, ImageFont

W, H = 1320, 2868  # iPhone 6.9" display slot

FONT = os.path.join(
    "..", "mobile", "node_modules", "@expo-google-fonts", "archivo",
    "900Black_Italic", "Archivo_900Black_Italic.ttf",
)

# --- palette -----------------------------------------------------------------
# WVU Old Gold / WVU Blue, straight from the app's design tokens.
GOLD, NAVY, WHITE = "#EAAA00", "#002855", "#FFFFFF"

THEMES = {
    # bg,   headline text,  rule color
    "gold": (GOLD, NAVY, NAVY),
    "navy": (NAVY, GOLD, GOLD),
}

# --- layout ------------------------------------------------------------------
PAD_X = 76           # side margin for the headline
HEAD_MAX = 124       # starting font size; shrinks to fit
LEADING = 0.95       # line height as a fraction of font size
RULE_W = 6           # rule stroke weight
RULE_GAP = 30        # clear space between the headline and the rule that flanks it
RULE1_Y = 372        # first rule — FIXED, so it lines up panel to panel while swiping.
                     # The headline block is centered on it, whether it runs 2 lines or 3.
RULE2_Y = 2285       # second rule — drawn behind the device
PHONE_W = 1096       # outer width of the device frame
PHONE_TOP = 742
BEZEL = 15           # frame thickness
RADIUS_OUT = 104
SS = 4               # supersample factor for the frame's rounded corners

# Submission order. The first one or two are what show in App Store search results, so
# lead with the identity shot, then the feature no feed reader could imitate.
PANELS = [
    ("Home Page 1.png", "01-daily-briefing", ["YOUR MOUNTAINEERS,", "BRIEFED EVERY", "MORNING"]),
    ("Pulse Chart.png", "02-pulse-chart", ["THE PULSE OF", "THE PROGRAM"]),
    ("Depth.png", "03-depth-chart", ["THE DEPTH CHART,", "ALWAYS CURRENT"]),
    ("Movement.png", "04-roster-movement", ["EVERY ROSTER MOVE,", "THE DAY IT HAPPENS"]),
    ("Scores.png", "05-scores", ["SCORES, SCHEDULE,", "KICKOFF CLOCK"]),
    ("News.png", "06-news", ["EVERY WVU HEADLINE", "IN ONE PLACE"]),
]

OUT_DIR = "store-hero"


def fit_font(all_lines, max_w):
    """One size for the whole set — the largest at which EVERY headline still clears the
    right-hand rule. Sizing each panel independently would leave them visibly mismatched."""
    size = HEAD_MAX
    while size > 40:
        f = ImageFont.truetype(FONT, size)
        if max(f.getbbox(t)[2] - f.getbbox(t)[0] for t in all_lines) <= max_w:
            return f, size
        size -= 2
    return ImageFont.truetype(FONT, size), size


def rounded_mask(size, radius):
    """Anti-aliased rounded-rect mask — PIL's rounded_rectangle alone leaves jaggies."""
    w, h = size
    m = Image.new("L", (w * SS, h * SS), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), radius * SS, fill=255)
    return m.resize((w, h), Image.LANCZOS)


def build(src, lines, theme, font, size):
    bg, ink, rule = THEMES[theme]
    canvas = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(canvas)

    # ---- headline, centered on the fixed rule ----
    step = round(size * LEADING)
    cap = font.getbbox("H")[3] - font.getbbox("H")[1]
    widest = max(font.getbbox(t)[2] - font.getbbox(t)[0] for t in lines)
    block_h = step * (len(lines) - 1) + cap
    y = RULE1_Y - block_h // 2

    for text in lines:
        # getbbox carries the glyphs' own left side bearing; subtract it so every line
        # starts on the same optical margin despite the italic slant.
        d.text((PAD_X - font.getbbox(text)[0], y - font.getbbox(text)[1]), text, font=font, fill=ink)
        y += step

    # ---- rule 1: through the headline, knocked out around the text ----
    r = (RULE1_Y - RULE_W // 2, RULE1_Y - RULE_W // 2 + RULE_W)
    d.rectangle((0, r[0], PAD_X - RULE_GAP, r[1]), fill=rule)
    d.rectangle((PAD_X + widest + RULE_GAP, r[0], W, r[1]), fill=rule)

    # ---- rule 2: full bleed, drawn now so the device frame covers its middle ----
    d.rectangle((0, RULE2_Y, W, RULE2_Y + RULE_W), fill=rule)

    # ---- device ----
    shot = Image.open(src).convert("RGB")
    inner_w = PHONE_W - 2 * BEZEL
    inner_h = round(shot.height * inner_w / shot.width)
    shot = shot.resize((inner_w, inner_h), Image.LANCZOS)
    shot.putalpha(rounded_mask(shot.size, RADIUS_OUT - BEZEL))

    frame_h = inner_h + 2 * BEZEL
    frame = Image.new("RGBA", (PHONE_W, frame_h), (0, 0, 0, 0))
    frame.paste(Image.new("RGBA", (PHONE_W, frame_h), (11, 12, 15, 255)),
                (0, 0), rounded_mask((PHONE_W, frame_h), RADIUS_OUT))
    frame.paste(shot, (BEZEL, BEZEL), shot)

    canvas.paste(frame, ((W - PHONE_W) // 2, PHONE_TOP), frame)
    return canvas  # already RGB — no alpha for App Store Connect to reject


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--theme", default="gold", choices=["gold", "navy", "alternating"])
    args = ap.parse_args()

    # Leave room on the right for the rule to re-emerge past the longest line.
    font, size = fit_font([l for _, _, ls in PANELS for l in ls], W - 2 * PAD_X - 96)

    os.makedirs(OUT_DIR, exist_ok=True)
    for i, (src, stem, lines) in enumerate(PANELS):
        if not os.path.exists(src):
            print(f"  [skip] {src} not found")
            continue
        theme = ["gold", "navy"][i % 2] if args.theme == "alternating" else args.theme
        dst = os.path.join(OUT_DIR, f"{stem}.png")
        build(src, lines, theme, font, size).save(dst, "PNG")
        print(f"  [OK] {stem}.png  {W}x{H}  {os.path.getsize(dst)/1024:.0f} KB  ({theme})")
    print(f"\nReady to upload from ./{OUT_DIR}/")


if __name__ == "__main__":
    main()
