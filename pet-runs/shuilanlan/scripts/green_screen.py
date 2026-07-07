#!/usr/bin/env python3
"""Robust green-screen removal for AI-generated sprites.

Distinguishes a green-dominant background from a cyan/blue body whose green
channel is also high. A pixel is treated as background only when G clearly
exceeds B (true green). Cyan/blue body pixels have B >= G and are preserved.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def remove_green_screen(input_path: Path, output_path: Path) -> None:
    im = Image.open(input_path).convert("RGBA")
    arr = np.array(im).astype(np.int16)
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    alpha = arr[..., 3]

    # Use only G vs B to decide. For a green background, G > B by a lot.
    # For a blue/cyan body, B >= G.
    green_overshoot = g - b
    # Body pixels often have lower saturation (e.g., light cyan) so the diff is small.

    # Three zones:
    # - solid background: green_overshoot > 30
    # - transition band: 5 < green_overshoot <= 30
    # - body / non-background: green_overshoot <= 5
    solid_bg = green_overshoot > 30
    band_bg = (green_overshoot > 5) & (green_overshoot <= 30)

    band_strength = np.where(
        band_bg,
        (green_overshoot - 5) / 25.0,  # 0..1
        0.0,
    )

    new_alpha = alpha.astype(np.float32)
    new_alpha[solid_bg] = 0
    new_alpha[band_bg] = np.minimum(
        new_alpha[band_bg], (1.0 - band_strength[band_bg]) * 255
    )

    # Despill: pull green down toward red+blue average for surviving pixels
    # that still carry a slight green tint.
    green_excess = np.clip(g - (r + b) // 2, 0, 30)
    arr[..., 1] = np.clip(g - green_excess, 0, 255)
    arr[..., 3] = np.clip(new_alpha, 0, 255).astype(np.int16)

    out = Image.fromarray(arr.astype(np.uint8), "RGBA")
    out.save(output_path)
    print(
        f"Wrote {output_path} ({output_path.stat().st_size} bytes). "
        f"Solid bg pixels: {int(solid_bg.sum())}, band: {int(band_bg.sum())}."
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--force", action="store_true")
    args = p.parse_args()
    if args.output.exists() and not args.force:
        print(f"Refusing to overwrite {args.output}", file=sys.stderr)
        raise SystemExit(2)
    remove_green_screen(args.input, args.output)


if __name__ == "__main__":
    main()
