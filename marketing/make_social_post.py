"""
Mountaineer Pulse - daily social still
======================================
Composites an iPhone screenshot into a 1080x1350 (4:5) Instagram post on the app's
navy ground, with a countdown headline above and the handle below.

4:5 because it is the tallest ratio the IG feed allows. A raw iPhone screenshot is
1284x2778 (~1:2.16), so cropping it straight to 4:5 throws away 40% of the screen --
padding the crop onto a canvas keeps the part that matters and leaves room for the
countdown, which the Pulse detail screen itself does not show.

Run:  python make_social_post.py --src social/IMG_9753.png --days 17 --out social/out.png
"""

import argparse
import os

from PIL import Image, ImageDraw, ImageFont

# App palette, straight from docs/index.html and the apparel marks.
BG = (6, 11, 22)
CARD = (13, 21, 36)
GOLD = (234, 170, 0)
INK = (239, 242, 247)
MUTED = (142, 154, 172)

W, H = 1080, 1350
MARGIN = 60
RADIUS = 28

FONT_DIRS = [r"C:\Windows\Fonts", "/usr/share/fonts", "/Library/Fonts"]
BOLD = ["segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"]
SEMI = ["segoeuisb.ttf", "seguisb.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"]
REG = ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"]


def font(names, size):
    for d in FONT_DIRS:
        for n in names:
            p = os.path.join(d, n)
            if os.path.exists(p):
                try:
                    return ImageFont.truetype(p, size)
                except OSError:
                    pass
    return ImageFont.load_default()


def rounded(img, radius):
    """Round the corners of an RGB image, returning RGBA."""
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, img.size[0], img.size[1]], radius, fill=255)
    out = img.convert("RGBA")
    out.putalpha(mask)
    return out


def build(src, days, opponent, date_label, crop, out):
    shot = Image.open(src).convert("RGB")

    # Crop to the hero band: selector tabs through the chart's date axis. Skips the
    # status bar (battery/time date the shot) and the home indicator, which on this
    # capture sits on top of the second briefing headline.
    top, bottom = crop
    top = max(0, min(top, shot.height - 2))
    bottom = max(top + 2, min(bottom, shot.height))
    shot = shot.crop((0, top, shot.width, bottom))

    inner_w = W - MARGIN * 2
    scale = inner_w / shot.width
    shot = shot.resize((inner_w, int(shot.height * scale)), Image.LANCZOS)
    shot = rounded(shot, RADIUS)

    canvas = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(canvas)

    f_days = font(BOLD, 96)
    f_kick = font(SEMI, 34)
    f_opp = font(REG, 31)
    f_hand = font(SEMI, 28)
    f_note = font(REG, 26)

    # --- headline -------------------------------------------------------------
    y = 74
    d.text((MARGIN, y), f"{days} DAYS", font=f_days, fill=GOLD)
    tw = d.textlength(f"{days} DAYS", font=f_days)
    d.text((MARGIN + tw + 22, y + 44), "TO KICKOFF", font=f_kick, fill=INK)
    y += 118
    d.text((MARGIN, y), f"{opponent}  \u00b7  {date_label}", font=f_opp, fill=MUTED)

    # --- screenshot -----------------------------------------------------------
    # The app ground and the canvas are the same navy, so the crop would bleed into
    # the page without an edge. A hairline gives it a frame.
    img_y = 300
    canvas.paste(shot, (MARGIN, img_y), shot)
    d.rounded_rectangle(
        [MARGIN, img_y, MARGIN + shot.width - 1, img_y + shot.height - 1],
        RADIUS, outline=(38, 52, 74), width=2)

    # --- footer ---------------------------------------------------------------
    fy = img_y + shot.height + 34
    if fy + 80 > H:
        fy = H - 96
    d.text((MARGIN, fy), "MOUNTAINEER PULSE", font=f_hand, fill=GOLD)
    d.text((MARGIN, fy + 40), "Free on the App Store  \u00b7  @mtnpulseapp", font=f_note, fill=MUTED)

    canvas.save(out, "PNG")
    print(f"wrote {out}  ({W}x{H})  screenshot band {top}-{bottom} scaled to {shot.height}px")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--days", type=int, required=True)
    ap.add_argument("--opponent", default="COASTAL CAROLINA")
    ap.add_argument("--date-label", default="SEPT 5")
    ap.add_argument("--crop-top", type=int, default=470)
    ap.add_argument("--crop-bottom", type=int, default=1545)
    a = ap.parse_args()
    build(a.src, a.days, a.opponent, a.date_label, (a.crop_top, a.crop_bottom), a.out)
