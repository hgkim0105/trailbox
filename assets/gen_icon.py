"""Generate assets/trailbox.ico.

Run once from the repo root:
    .\\.venv\\Scripts\\python.exe assets\\gen_icon.py

Design:
  - Dark rounded square ("box") with a thin cool-blue border.
  - Two small blue "trail" dots leading in from the upper-left corner
    (the "trail" in trailbox).
  - Bright red recording dot dead center (the QA capture indicator),
    with a faint halo for emphasis at large sizes.

The base 256x256 PNG is downscaled into a multi-resolution ICO so Windows
can pick the right size for taskbar / Alt-Tab / file explorer contexts.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


def render(size: int = 256) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Geometry — proportions chosen for legibility down to 16x16.
    margin = int(size * 0.10)
    radius = int(size * 0.18)
    border_w = max(2, int(size * 0.025))
    dot_r = int(size * 0.22)
    trail_r1 = max(2, int(size * 0.035))
    trail_r2 = max(2, int(size * 0.055))

    cx, cy = size // 2, size // 2
    box_l, box_t = margin, margin
    box_r, box_b = size - margin, size - margin

    # Outer rounded "box".
    d.rounded_rectangle(
        (box_l, box_t, box_r, box_b),
        radius=radius,
        fill=(28, 30, 38, 255),
        outline=(74, 144, 226, 255),
        width=border_w,
    )

    # Faint halo around the record dot (only meaningful at large sizes).
    if size >= 64:
        halo = int(dot_r * 1.35)
        d.ellipse(
            (cx - halo, cy - halo, cx + halo, cy + halo),
            outline=(231, 76, 60, 90),
            width=max(2, int(size * 0.018)),
        )

    # The recording dot.
    d.ellipse(
        (cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r),
        fill=(231, 76, 60, 255),
    )

    # Trail dots in the upper-left (skipped at tiny sizes — they'd be noise).
    if size >= 48:
        tx1 = box_l - int(size * 0.04)
        ty1 = box_t - int(size * 0.04)
        tx2 = tx1 + int(size * 0.09)
        ty2 = ty1 + int(size * 0.09)
        d.ellipse(
            (tx1 - trail_r1, ty1 - trail_r1, tx1 + trail_r1, ty1 + trail_r1),
            fill=(74, 144, 226, 200),
        )
        d.ellipse(
            (tx2 - trail_r2, ty2 - trail_r2, tx2 + trail_r2, ty2 + trail_r2),
            fill=(74, 144, 226, 230),
        )

    return img


def main() -> int:
    out_dir = Path(__file__).resolve().parent
    base = render(256)
    base.save(out_dir / "trailbox.png", format="PNG")  # handy for previews
    # Pillow's ICO writer downsamples from the source for each requested size.
    ico_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    base.save(out_dir / "trailbox.ico", format="ICO", sizes=ico_sizes)
    print(f"wrote {out_dir / 'trailbox.ico'} (sizes {ico_sizes})")
    print(f"wrote {out_dir / 'trailbox.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
