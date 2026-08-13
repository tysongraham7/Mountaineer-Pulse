"""
Mountaineer Pulse - Apparel Artwork Generator
=============================================
Emits print-ready vector art for embroidery / screen printing, generated from the
SAME geometry the app ships, so the shirts can't drift from the product:

  * the ridge-pulse mark  -> the exact path from RidgeMark in ui.tsx
  * the wordmark          -> "MOUNTAINEER PULSE" set in Archivo 800 ExtraBold and
                             CONVERTED TO OUTLINES, so no vendor needs the font

Run:  python make_apparel_art.py      (writes .svg files next to this script)
"""

import os

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.misc.transform import Transform

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = os.path.join(
    HERE, "..", "..", "mobile", "node_modules", "@expo-google-fonts",
    "archivo", "800ExtraBold", "Archivo_800ExtraBold.ttf",
)

# --- Brand (constants/brand.ts) ------------------------------------------------
GOLD = "#EAAA00"   # WVU Old Gold ~ PMS 123 C
NAVY = "#002855"   # WVU Blue     ~ PMS 282 C
INK = "#0B1220"    # near-black navy, for light garments
WHITE = "#FFFFFF"  # pure white on a shirt, vs the app's off-white #EFF2F7

# --- The mark (RidgeMark, ui.tsx) ---------------------------------------------
# One open path, round caps and joins: no gradients, no fine detail, no closed
# counters. This is why it embroiders cleanly at chest size.
WAVE_D = "M1,12 L6,4 L9,9 L12,2 L14,12 L17,7 L23,7"
WAVE_SW = 2.4          # stroke width in the 24x14 viewBox = 10% of mark width
PAD = 1.0
# Path bounds x[1,23] y[2,12], grown by half the stroke (round caps add no more).
VB = (1 - WAVE_SW / 2 - PAD, 2 - WAVE_SW / 2 - PAD,
      22 + WAVE_SW + 2 * PAD, 10 + WAVE_SW + 2 * PAD)

# RN letterSpacing -0.3 at fontSize 17 => -0.3/17 em of tracking.
TRACKING_EM = -0.3 / 17


def svg_open(w_in: float, h_in: float, vb: tuple) -> str:
    """An SVG whose width/height are stated in INCHES — vendors open it at the
    physical size we intend, instead of guessing from a pixel count."""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{w_in:.4f}in" height="{h_in:.4f}in" '
        f'viewBox="{vb[0]:.4f} {vb[1]:.4f} {vb[2]:.4f} {vb[3]:.4f}">\n'
    )


def mark_svg(color: str, width_in: float) -> str:
    h_in = width_in * VB[3] / VB[2]
    return (
        svg_open(width_in, h_in, VB)
        + "  <!-- Mountaineer Pulse ridge mark. Single open path.\n"
          "       For embroidery/vinyl: Object > Path > Outline Stroke first. -->\n"
        f'  <path d="{WAVE_D}" fill="none" stroke="{color}" stroke-width="{WAVE_SW}"\n'
        '        stroke-linecap="round" stroke-linejoin="round"/>\n'
        "</svg>\n"
    )


def glyph_runs(text: str, upem: int, font: TTFont):
    """Yield (glyph_name, x_offset) laying `text` out on a baseline at x=0, and
    return the total advance — everything in font units."""
    cmap = font.getBestCmap()
    hmtx = font["hmtx"]
    track = TRACKING_EM * upem
    x = 0.0
    runs = []
    for ch in text:
        gname = cmap.get(ord(ch))
        if gname is None:
            raise SystemExit(f"font has no glyph for {ch!r}")
        runs.append((gname, x))
        x += hmtx[gname][0] + track
    return runs, x - track  # no trailing track after the last glyph


def wordmark_paths(font: TTFont, upem: int):
    """'MOUNTAINEER' and 'PULSE' as two outlined path strings (y-flipped into SVG
    space), plus the combined bounding box. Type is outlined so the color split
    survives without the vendor installing Archivo."""
    gs = font.getGlyphSet()
    runs, total_w = glyph_runs("MOUNTAINEER PULSE", upem, font)
    split = len("MOUNTAINEER ")

    bounds = BoundsPen(gs)
    parts = {"word1": [], "word2": []}
    for i, (gname, xoff) in enumerate(runs):
        key = "word1" if i < split else "word2"
        # Flip Y (font grows up, SVG grows down) and shift to the pen origin.
        t = Transform(1, 0, 0, -1, xoff, 0)
        pen = SVGPathPen(gs)
        gs[gname].draw(TransformPen(pen, t))
        d = pen.getCommands()
        if d:
            parts[key].append(d)
        gs[gname].draw(TransformPen(bounds, t))
    return parts, bounds.bounds, total_w


def build_wordmark(font, upem, colors, width_in, note):
    parts, bb, _ = wordmark_paths(font, upem)
    x0, y0, x1, y1 = bb
    pad = upem * 0.04
    vb = (x0 - pad, y0 - pad, (x1 - x0) + 2 * pad, (y1 - y0) + 2 * pad)
    h_in = width_in * vb[3] / vb[2]
    out = svg_open(width_in, h_in, vb) + f"  <!-- {note} -->\n"
    for key, color in (("word1", colors[0]), ("word2", colors[1])):
        out += f'  <g fill="{color}" fill-rule="nonzero">\n'
        for d in parts[key]:
            out += f'    <path d="{d}"/>\n'
        out += "  </g>\n"
    return out + "</svg>\n", vb


def build_lockup(font, upem, mark_color, colors, width_in, note):
    """Mark stacked above the wordmark, centered — the gameday full-front layout."""
    parts, bb, _ = wordmark_paths(font, upem)
    x0, y0, x1, y1 = bb
    word_w, word_h = x1 - x0, y1 - y0

    # Scale the 24x14 mark to 38% of the wordmark width, sit it above with a gap.
    mark_w = word_w * 0.38
    scale = mark_w / VB[2]
    mark_h = VB[3] * scale
    gap = word_h * 0.55

    pad = upem * 0.05
    total_w = max(word_w, mark_w)
    vb = (-total_w / 2 - pad, -pad, total_w + 2 * pad, mark_h + gap + word_h + 2 * pad)
    h_in = width_in * vb[3] / vb[2]

    out = svg_open(width_in, h_in, vb) + f"  <!-- {note} -->\n"
    # Mark: translate to centered top, scale, then shift the viewBox origin out.
    out += (
        f'  <g transform="translate({-mark_w / 2:.4f},0) scale({scale:.6f}) '
        f'translate({-VB[0]:.4f},{-VB[1]:.4f})">\n'
        f'    <path d="{WAVE_D}" fill="none" stroke="{mark_color}" stroke-width="{WAVE_SW}"\n'
        '          stroke-linecap="round" stroke-linejoin="round"/>\n'
        "  </g>\n"
    )
    # Wordmark: baseline sits at mark_h + gap + (distance from bbox top to baseline).
    ty = mark_h + gap - y0
    out += f'  <g transform="translate({-word_w / 2 - x0:.4f},{ty:.4f})">\n'
    for key, color in (("word1", colors[0]), ("word2", colors[1])):
        out += f'    <g fill="{color}" fill-rule="nonzero">\n'
        for d in parts[key]:
            out += f'      <path d="{d}"/>\n'
        out += "    </g>\n"
    return out + "  </g>\n</svg>\n"


def write(name: str, body: str) -> None:
    path = os.path.join(HERE, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    print(f"  {name}")


def main() -> None:
    if not os.path.exists(FONT):
        raise SystemExit(f"Archivo ExtraBold not found at {FONT}\n"
                         "Run `npm install` in mobile/ first.")
    font = TTFont(FONT)
    upem = font["head"].unitsPerEm

    print("Mountaineer Pulse apparel art ->")

    # --- Mark alone. 3.5in = the standard left-chest embroidery width. ---
    write("mp-mark-1color-black.svg", mark_svg("#000000", 3.5))
    write("mp-mark-gold.svg", mark_svg(GOLD, 3.5))
    write("mp-mark-white.svg", mark_svg(WHITE, 3.5))

    # --- Wordmark alone, outlined. ---
    wm_2c, _ = build_wordmark(
        font, upem, (WHITE, GOLD), 11.0,
        "Wordmark, 2 colors: MOUNTAINEER white + PULSE gold. Type outlined (Archivo 800 ExtraBold).")
    write("mp-wordmark-2color.svg", wm_2c)
    wm_1c, _ = build_wordmark(
        font, upem, ("#000000", "#000000"), 11.0,
        "Wordmark, 1 color black. Type outlined — recolor to any single thread/ink.")
    write("mp-wordmark-1color-black.svg", wm_1c)

    # --- Stacked lockup. 11in = full-front screen print width. ---
    write("mp-lockup-2color.svg", build_lockup(
        font, upem, GOLD, (WHITE, GOLD), 11.0,
        "Full-front lockup, 2 colors (gold + white) for dark garments."))
    write("mp-lockup-1color-black.svg", build_lockup(
        font, upem, "#000000", ("#000000", "#000000"), 11.0,
        "Full-front lockup, 1 color black — for light garments and for embroidery digitizing."))
    write("mp-lockup-1color-white.svg", build_lockup(
        font, upem, WHITE, (WHITE, WHITE), 11.0,
        "Full-front lockup, 1 color white — for dark garments."))

    print(f"\n[OK] Brand: gold {GOLD} (~PMS 123 C), navy {NAVY} (~PMS 282 C), ink {INK}")


if __name__ == "__main__":
    main()
