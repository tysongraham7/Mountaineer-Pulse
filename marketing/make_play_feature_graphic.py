"""
Google Play feature graphic (1024x500)
======================================
Play requires this asset and there is no App Store equivalent, so nothing in this repo
covers it. It sits at the top of the store listing and is the first thing a browsing user
sees — above the screenshots, above the description.

Design is deliberately the x-header treatment (navy gradient, gold glow, the ridge waveform
that echoes the app icon, MOUNTAINEER in white + PULSE in gold) so the listing, the site, and
the social profiles read as one brand rather than three. It is re-laid-out rather than scaled:
the header is 1500x500, and squeezing 1500px of composition into 1024 would crowd it.

Two deliberate departures from the x-header:
  * No "NOW IN BETA - IPHONE" pill. On an Android listing that badge is wrong twice over.
  * Nothing important within ~90px of center-bottom. If a promo video is ever added to the
    listing, Play overlays a play button on this graphic's center, and Play also crops the
    edges on some surfaces. Text stays inside the safe middle.

  python make_play_feature_graphic.py   ->  ./play/feature-graphic.png
"""

import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1024, 500
GOLD = (234, 170, 0)
WHITE = (235, 242, 250)
MUTED = (140, 161, 188)
INK = (9, 16, 30)

F = "C:/Windows/Fonts/{}"
f_word = ImageFont.truetype(F.format("seguibl.ttf"), 62)   # Segoe UI Black
f_tag = ImageFont.truetype(F.format("segoeui.ttf"), 26)
f_badge = ImageFont.truetype(F.format("segoeuib.ttf"), 19)

# --- base navy gradient (top lighter -> bottom near-black navy) ---
base = Image.new("RGB", (W, H))
top, bot = (12, 26, 46), (5, 9, 15)
px = base.load()
for y in range(H):
    t = y / (H - 1)
    row = tuple(int(top[i] * (1 - t) + bot[i] * t) for i in range(3))
    for x in range(W):
        px[x, y] = row
base = base.convert("RGBA")

# --- soft gold glow, top-right ---
glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
ImageDraw.Draw(glow).ellipse([W - 420, -240, W + 200, 300], fill=(234, 170, 0, 72))
glow = glow.filter(ImageFilter.GaussianBlur(150))
base = Image.alpha_composite(base, glow)

# --- pulse/ridge waveform, centered above the wordmark ---
# Normalized (x 0..1, y as offset from the baseline) so the shape is independent of canvas
# size; the x-header uses the same silhouette at a different scale.
RIDGE = [(0.000, 0), (0.139, 0), (0.204, -42), (0.268, 0), (0.332, -66), (0.404, 0),
         (0.468, -94), (0.532, 32), (0.596, -28), (0.661, 0), (1.000, 0)]
SPAN, BASELINE, AMP = 430, 132, 0.74
x0 = (W - SPAN) / 2
pts = [(x0 + fx * SPAN, BASELINE + fy * AMP) for fx, fy in RIDGE]
line = Image.new("RGBA", (W, H), (0, 0, 0, 0))
ImageDraw.Draw(line).line(pts, fill=(*GOLD, 255), width=9, joint="curve")
base = Image.alpha_composite(base, line.filter(ImageFilter.GaussianBlur(12)))
base = Image.alpha_composite(base, line)  # crisp stroke over its own glow

d = ImageDraw.Draw(base)

# --- wordmark: MOUNTAINEER (white) + PULSE (gold), centered as a unit ---
w1 = d.textlength("MOUNTAINEER ", font=f_word)
w2 = d.textlength("PULSE", font=f_word)
start = (W - (w1 + w2)) / 2
wy = 218
d.text((start, wy), "MOUNTAINEER ", font=f_word, fill=WHITE)
d.text((start + w1, wy), "PULSE", font=f_word, fill=GOLD)


def centered(text, font, y, fill):
    d.text(((W - d.textlength(text, font=font)) / 2, y), text, font=font, fill=fill)


# --- tagline ---
centered("The daily pulse of WVU sports", f_tag, 306, MUTED)

# --- sports pill (what the app actually covers, in the app's gold) ---
btxt = "FOOTBALL   ·   BASKETBALL   ·   BASEBALL"  # middot, matching the x-header
bw = d.textlength(btxt, font=f_badge)
padx = 22
bx0 = (W - (bw + padx * 2)) / 2
by0 = 372
d.rounded_rectangle([bx0, by0, bx0 + bw + padx * 2, by0 + 42], radius=21, fill=GOLD)
d.text((bx0 + padx, by0 + 10), btxt, font=f_badge, fill=INK)

os.makedirs("play", exist_ok=True)
out = os.path.join("play", "feature-graphic.png")
base.convert("RGB").save(out, "PNG")
print("saved", out, (W, H))
