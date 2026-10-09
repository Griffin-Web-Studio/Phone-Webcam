#!/usr/bin/env python3
"""Generate static/images/favicon.ico from static/images/dark-bg-icon.svg.

Uses CairoSVG to rasterize the SVG at each target size, then Pillow to pack
the results into a single multi-size ICO (16, 32, 48, 256 px). Run manually
whenever the source SVG changes - the output is checked into git, not
regenerated at build/deploy time.
"""

import sys
from io import BytesIO
from pathlib import Path

import cairosvg
from PIL import Image

ROOT = Path(__file__).parent.parent
SVG = ROOT / "static" / "images" / "dark-bg-icon.svg"
ICO = ROOT / "static" / "images" / "favicon.ico"
SIZES = [(16, 16), (32, 32), (48, 48), (256, 256)]


def main() -> None:
    if not SVG.exists():
        print(f"ERROR: {SVG} not found", file=sys.stderr)
        sys.exit(1)

    ICO.parent.mkdir(parents=True, exist_ok=True)

    largest = max(SIZES)
    png_bytes = cairosvg.svg2png(
        url=str(SVG), output_width=largest[0], output_height=largest[1]
    )

    img = Image.open(BytesIO(png_bytes)).convert("RGBA")
    img.save(ICO, format="ICO", sizes=SIZES)

    print(f"Generated {ICO}")


if __name__ == "__main__":
    main()
