"""
HealVPN Logo GIF Generator  v3
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Renders the shield from logo_mint_dark.svg with NO background
• Supersampling (4×) gives smooth, perfectly-uniform line widths
• Floating bob + wind-streak animation on a plain dark canvas
"""
import math, random, os
from PIL import Image, ImageDraw

# ── Output ────────────────────────────────────────────────────────────────────
OUTPUT    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "healvpn_logo_flying.gif")

# ── Render settings ───────────────────────────────────────────────────────────
CANVAS    = 512     # Final GIF size (px)
LOGO_SIZE = 300     # Logo size inside canvas
SS        = 4       # Supersampling factor (render at SS×, then downscale)
NUM_FRAMES = 60     # 2-second loop at 30 fps
FRAME_DUR  = 33     # ms per frame (~30 fps)
BOB_AMP   = 16      # Vertical float amplitude (px, in final canvas space)
WIND_N    = 30      # Wind streak count

# ── Colours ───────────────────────────────────────────────────────────────────
MINT      = (0, 230, 118)       # #00E676
CANVAS_BG = (5, 5, 5)           # #050505 — plain dark background (NO squircle)


# ══════════════════════════════════════════════════════════════════════════════
#  LOGO  (shield only, transparent background, supersampled)
# ══════════════════════════════════════════════════════════════════════════════

def cubic_bezier_pts(p0, p1, p2, p3, steps=32):
    """Uniformly-spaced samples along a cubic Bézier."""
    pts = []
    for i in range(steps + 1):
        t = i / steps
        m = 1 - t
        x = m**3*p0[0] + 3*m**2*t*p1[0] + 3*m*t**2*p2[0] + t**3*p3[0]
        y = m**3*p0[1] + 3*m**2*t*p1[1] + 3*m*t**2*p2[1] + t**3*p3[1]
        pts.append((x, y))
    return pts


def render_shield(size: int, bob_px: float = 0.0) -> Image.Image:
    """
    Render the shield at (size×size) RGBA with transparent background.
    bob_px — vertical offset in FINAL canvas pixels (converted internally).
    Uses supersampling to ensure perfectly uniform stroke width.
    """
    hi = size * SS                      # high-res canvas for supersampling
    img = Image.new("RGBA", (hi, hi), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # ── Coordinate mapping ───────────────────────────────────────────────────
    # SVG:  viewBox 0 0 1024 1024
    # g transform: translate(212,212) scale(25)
    # Path unit → pixel:  px = (212 + u*25) * (hi/1024)
    scale = hi / 1024.0
    TX, TY, SC = 212.0, 212.0, 25.0
    bob_hi = bob_px * SS * (size / CANVAS)   # bob in high-res space

    def px(ux, uy):
        return ((TX + ux * SC) * scale,
                (TY + uy * SC) * scale + bob_hi)

    # ── Stroke width (uniform) ───────────────────────────────────────────────
    # SVG stroke-width = 2.2 in path units  → × SC=25 → 55 svg-px  → ×scale
    stroke_svg = 2.2 * SC * scale          # theoretical stroke in hi-res px
    stroke_w   = max(6, int(round(stroke_svg)))   # ensure integer, min 6

    # ── Shield outline points ────────────────────────────────────────────────
    # SVG path: M12 22 C12 22 20 18 20 12 V5 L12 2 L4 5 V12 C4 18 12 22 12 22 Z
    pts = []
    pts += cubic_bezier_pts(px(12,22), px(12,22), px(20,18), px(20,12))  # right curve
    pts.append(px(20, 5))   # top-right shoulder
    pts.append(px(12, 2))   # top centre
    pts.append(px(4,  5))   # top-left shoulder
    pts.append(px(4, 12))   # left mid
    pts += cubic_bezier_pts(px(4,12), px(4,18), px(12,22), px(12,22))    # left curve

    # ── Draw shield as closed stroke (line segments + dot at each joint) ─────
    # Drawing as filled outer − filled inner gives non-uniform thickness at
    # sharp corners.  Instead we use thick line segments at 4× resolution
    # (joints smooth out after downscaling).
    n = len(pts)
    for i in range(n):
        draw.line([pts[i], pts[(i + 1) % n]], fill=MINT, width=stroke_w)

    # Round caps at each vertex to fill the join gaps
    r = stroke_w // 2
    for (x0, y0) in pts:
        draw.ellipse([x0 - r, y0 - r, x0 + r, y0 + r], fill=MINT)

    # ── Plus sign: M8 12 H16  M12 8 V16 ────────────────────────────────────
    h0, hy  = px(8,  12);  h1, _   = px(16, 12)
    vx, vy0 = px(12,  8);   _, vy1  = px(12, 16)
    draw.line([(h0, hy),  (h1, hy)],   fill=MINT, width=stroke_w)
    draw.line([(vx, vy0), (vx, vy1)],  fill=MINT, width=stroke_w)
    # Round caps on plus ends
    for pt in [(h0, hy), (h1, hy), (vx, vy0), (vx, vy1)]:
        draw.ellipse([pt[0]-r, pt[1]-r, pt[0]+r, pt[1]+r], fill=MINT)

    # ── Downscale with Lanczos → smooth anti-aliased uniform lines ───────────
    return img.resize((size, size), Image.LANCZOS)


# ══════════════════════════════════════════════════════════════════════════════
#  WIND STREAKS
# ══════════════════════════════════════════════════════════════════════════════

def make_particles(w, h, n):
    random.seed(42)
    return [{
        'x':      random.uniform(-200, w),
        'y':      random.uniform(0, h),
        'speed':  random.uniform(8, 20),
        'length': random.uniform(60, 190),
        'alpha':  random.randint(12, 55),
        'width':  random.choice([1, 1, 1, 2, 2]),
    } for _ in range(n)]


def step_and_draw_wind(draw, particles, canvas_w, canvas_h):
    for p in particles:
        steps = max(4, int(p['length'] // 5))
        for k in range(steps):
            t  = k / steps
            a  = int(p['alpha'] * math.sin(t * math.pi))
            xa = p['x'] + t * p['length']
            xb = xa + p['length'] / steps
            draw.line([(xa, p['y']), (xb, p['y'])],
                      fill=(*MINT, a), width=p['width'])
        p['x'] -= p['speed']
        if p['x'] + p['length'] < -60:
            p['x']      = canvas_w + random.uniform(40, 280)
            p['y']      = random.uniform(0, canvas_h)
            p['speed']  = random.uniform(8, 20)
            p['length'] = random.uniform(60, 190)
            p['alpha']  = random.randint(12, 55)


# ══════════════════════════════════════════════════════════════════════════════
#  FRAME BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def build_frames():
    cx = cy = CANVAS // 2
    half = LOGO_SIZE // 2
    particles = make_particles(CANVAS, CANVAS, WIND_N)
    frames = []

    for i in range(NUM_FRAMES):
        t   = i / NUM_FRAMES
        bob = math.sin(t * math.pi * 2) * BOB_AMP   # bob in canvas px

        # Plain dark canvas, no background shapes
        canvas = Image.new("RGBA", (CANVAS, CANVAS), (*CANVAS_BG, 255))
        d = ImageDraw.Draw(canvas)

        step_and_draw_wind(d, particles, CANVAS, CANVAS)

        # Render shield with this frame's bob baked in
        shield = render_shield(LOGO_SIZE, bob_px=bob)

        # Paste centred (bob is already inside the shield image)
        canvas.paste(shield, (cx - half, cy - half), shield)

        # Convert to palette for GIF (256 colours)
        frames.append(canvas.convert("RGB").convert("P", palette=Image.ADAPTIVE, colors=256))

    return frames


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print(f"🎨  Rendering shield at {LOGO_SIZE}×{LOGO_SIZE} (SS×{SS} = {LOGO_SIZE*SS}px)")
    print(f"🎬  Building {NUM_FRAMES} frames …")
    frames = build_frames()
    print(f"💾  Saving …")
    frames[0].save(
        OUTPUT,
        save_all=True,
        append_images=frames[1:],
        duration=FRAME_DUR,
        loop=0,
        disposal=2,
    )
    kb = os.path.getsize(OUTPUT) // 1024
    print(f"✅  {OUTPUT}  ({kb} KB)")
