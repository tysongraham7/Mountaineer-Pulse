"""Generate the Mountaineer Pulse X header (1500x500) as a ready-to-upload PNG."""
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1500, 500
GOLD = (234, 170, 0)
WHITE = (235, 242, 250)
MUTED = (140, 161, 188)

F = "C:/Windows/Fonts/{}"
f_word = ImageFont.truetype(F.format("seguibl.ttf"), 78)   # Segoe UI Black
f_tag = ImageFont.truetype(F.format("segoeui.ttf"), 31)
f_badge = ImageFont.truetype(F.format("segoeuib.ttf"), 23)

# --- base navy gradient (top lighter -> bottom near-black navy) ---
base = Image.new("RGB", (W, H))
top, bot = (12, 26, 46), (5, 9, 15)
px = base.load()
for y in range(H):
    t = y / (H - 1)
    r = int(top[0] * (1 - t) + bot[0] * t)
    g = int(top[1] * (1 - t) + bot[1] * t)
    b = int(top[2] * (1 - t) + bot[2] * t)
    for x in range(W):
        px[x, y] = (r, g, b)
base = base.convert("RGBA")

# --- soft gold glow, top-right ---
glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
ImageDraw.Draw(glow).ellipse([W - 520, -260, W + 240, 340], fill=(234, 170, 0, 70))
glow = glow.filter(ImageFilter.GaussianBlur(170))
base = Image.alpha_composite(base, glow)

# --- pulse/ridge waveform (echoes the app icon), with glow ---
pts = [(470, 158), (548, 158), (584, 116), (620, 158), (656, 92), (696, 158),
       (732, 64), (768, 190), (804, 130), (840, 158), (1030, 158)]
line_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
ImageDraw.Draw(line_layer).line(pts, fill=(234, 170, 0, 255), width=11, joint="curve")
base = Image.alpha_composite(base, line_layer.filter(ImageFilter.GaussianBlur(14)))
base = Image.alpha_composite(base, line_layer)  # crisp line on top of its glow

d = ImageDraw.Draw(base)

def centered(text, font, y, fill):
    w = d.textlength(text, font=font)
    d.text(((W - w) / 2, y), text, font=font, fill=fill)
    return w

# --- wordmark: MOUNTAINEER (white) + PULSE (gold), centered as a unit ---
w1 = d.textlength("MOUNTAINEER ", font=f_word)
w2 = d.textlength("PULSE", font=f_word)
start = (W - (w1 + w2)) / 2
wy = 232
d.text((start, wy), "MOUNTAINEER ", font=f_word, fill=WHITE)
d.text((start + w1, wy), "PULSE", font=f_word, fill=GOLD)

# --- tagline ---
centered("The daily pulse of WVU sports", f_tag, 340, MUTED)

# --- "NOW IN BETA · IPHONE" pill, centered ---
btxt = "NOW IN BETA   ·   IPHONE"
bw = d.textlength(btxt, font=f_badge)
padx, padyt = 26, 12
bx0 = (W - (bw + padx * 2)) / 2
by0 = 386
d.rounded_rectangle([bx0, by0, bx0 + bw + padx * 2, by0 + 48], radius=24, fill=GOLD)
d.text((bx0 + padx, by0 + padyt), btxt, font=f_badge, fill=(9, 16, 30))

out = r"C:/Users/Tyson/AppData/Local/Temp/claude/d--Claude-App-Practice-WVU-Sports-Hub/bb48a0f8-f1d1-4ed4-97dc-28d6f9700e1f/scratchpad/x-header.png"
base.convert("RGB").save(out, "PNG")
print("saved", out, base.size)
