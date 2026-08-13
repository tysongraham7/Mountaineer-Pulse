# Mountaineer Pulse — Apparel Spec

Everything a shop needs, in one page. Forward this with the `.svg` files.
Regenerate the art any time with `python make_apparel_art.py`.

---

## Files

| File | Use |
|---|---|
| `mp-mark-1color-black.svg` | Left-chest embroidery. Recolor to any thread. |
| `mp-mark-gold.svg` / `mp-mark-white.svg` | Mark alone, brand colors. |
| `mp-wordmark-2color.svg` | Wordmark only, white + gold. |
| `mp-wordmark-1color-black.svg` | Wordmark only, single color. |
| `mp-lockup-2color.svg` | Full-front, dark garments (gold + white). |
| `mp-lockup-1color-white.svg` | Full-front, dark garments, one color. |
| `mp-lockup-1color-black.svg` | Full-front, light garments; also the embroidery digitizing master. |

True vector. Type is **already converted to outlines** (Archivo 800 ExtraBold) — no
font needed on your end. Widths/heights are stated in **inches**, not pixels, so the
file opens at its intended physical size.

**Before embroidery or vinyl:** the mark is one open path with a round-capped stroke.
Run *Object → Path → Outline Stroke* first.

---

## Colors

| Name | Hex | Pantone (approx.) |
|---|---|---|
| Old Gold | `#EAAA00` | PMS 123 C |
| Navy | `#002855` | PMS 282 C |
| Ink (near-black navy) | `#0B1220` | — |
| White | `#FFFFFF` | — |

Match thread and ink to the hex. Confirm the Pantone against a physical book — the
values above are close but were not proofed on press.

**The gold is the one to watch.** `#EAAA00` is a saturated yellow-orange near the edge
of the CMYK gamut, so process methods (DTF, DTG) tend to render it duller and greener
than intended. Two requirements:

1. **On dark garments, lay a white underbase under the gold.** Printed straight onto
   navy or black it goes muddy. This is not optional.
2. **If the gold has to be exact, print it as a spot color** — screen print or puff
   mixed to PMS 123 C — rather than process. Spot is the only method that reproduces it
   reliably. If we're on DTF, send a printed strike-off before the full run.

Navy `#002855` and white are well inside gamut and reproduce fine either way.

### Colorways

| Garment | Body | Art | File |
|---|---|---|---|
| Boxy crop tee (gameday) | Black or navy | Gold + white lockup | `mp-lockup-2color.svg` |
| Boxy crop tee (alt) | Natural / cream | Navy, one color | `mp-lockup-1color-black.svg`, recolored to `#002855` |
| Workout tee | Black | White, one color | `mp-lockup-1color-white.svg` |
| Golf polo | Navy | Gold, left chest | `mp-mark-1color-black.svg`, stitched in gold |

**No gold garments.** Blank "gold" colorways vary enormously between mills — Old Gold,
Vegas Gold and Daisy are all different, and none reliably match PMS 123 C. Garment dye
can't be controlled; ink and thread can. Keep the bodies dark or neutral and let the
gold live in the print.

---

## Placement

**Left chest (polo, and any tee that isn't getting a full front)**
- Width **3.25"**
- Centered ~**7.5"** down from the shoulder/neck seam
- On a polo, align the left edge with the placket edge

**Full front, standard-fit tee**
- Width **11"**
- Top of print **3"** below the collar seam

**Full front, oversized / boxy tee**
- Width **12.5"**
- Top of print **4.5"** below the collar seam

That last row matters. An oversized body is wider and longer, so a standard 11" print
placed 3" down reads as small and rides too high. Scaling up and dropping it is what
makes it look intentional rather than like a normal print on a big shirt.

**Full front, boxy "cropped" tee** — wide body, hem at the belt line rather than past
the hips. Not a midriff crop.
- Width **12.5"** (same as above — the body is just as wide)
- Top of print **4.0"** below the collar seam
- Stacked lockup is fine here; no need to switch to the wordmark

Reference lengths, high point of shoulder to hem, size L:

| Cut | Length | Sits |
|---|---|---|
| Standard | 29–30" | Below the waistband |
| Long / tall streetwear | 31–33" | Well past the hips |
| **Boxy "cropped"** | **26–27"** | **At the belt line** |
| True crop top | 20–23" | Above the navel |

Only 3–4" comes off versus standard, so this is a small adjustment, not a different
layout. Holding the drop at 4.5" would push the print slightly below the visual centre
of a shorter body; 4.0" keeps it at the same proportional height as the oversized spec.

**Crop before you print.** If you're cutting down a longer blank yourself rather than
buying one cut boxy, do it *first* and hand the shop the finished garment. Placement is
measured from the collar and eyeballed against the hem — cropping afterwards moves the
print relative to the body and there's no undo.

---

## Embroidery note (read this one)

At 3.25" wide, the wave's stroke works out to about **0.30"** thick. That is too wide
for a satin stitch — long satin stitches snag and pull. Tell the digitizer to run the
wave as a **fill (tatami) stitch**, not satin.

The mark has no gradients, no closed counters, and no detail under 1/8", so it should
digitize cleanly with no simplification. Ask for a **physical stitch-out** on scrap
before the real garment.

The app's logo tile has a *dashed* rounded-square border around the mark. It is
deliberately **not** in these files: dashed strokes don't embroider, and it's a
placeholder in the app anyway.

---

## Printing method by garment

The quantity here is 1–2 per style, which rules out screen printing — screen setup is
charged per color per design and only amortizes over a dozen-plus pieces.

| Garment | Fabric | Method |
|---|---|---|
| Workout tee | 100% polyester | **DTF transfer** |
| Oversized cropped tee | Heavyweight cotton | **Puff print**, or DTG |
| Golf polo | Performance piqué | **Embroidery**, left chest |

**Puff is the right call on the cropped tee.** The same thing that makes the wave
awkward to embroider — a stroke ~0.30" thick with no fine detail — makes it ideal for
puff, which needs bold simple shapes and destroys thin lines. Puff is screen printing,
so ask about setup cost at single quantity; some shops run it as a one-off, others will
push you to DTG. DTG is the safe fallback and looks fine, just flat.

**Polyester needs DTF, not screen print.** Poly dye migrates into plastisol ink and
discolors it from the inside — white goes pink or grey over weeks. If a shop insists on
screen printing the workout tee, it must be low-bleed poly ink over a blocker base.
DTF sidesteps the problem entirely and is cheaper at this quantity.

---

## Ask every shop

1. Minimum order — will they do single pieces?
2. Will they print on customer-supplied blanks, and does that void anything?
3. Digitizing fee for the embroidery file (one-time, typically $25–75; some waive it)
4. Do they provide a physical stitch-out before running the garment?
5. Turnaround. Budget 2–3 weeks, longer through August and September when every team in
   the region is ordering.
