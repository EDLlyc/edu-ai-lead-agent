#!/usr/bin/env python3
"""Create deterministic, metadata-free publication derivatives for the local article fixture."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

QUALITY = 82
SUBSAMPLING = 2  # Pillow's deterministic 4:2:0 setting.

ASSETS = (
    ("xiaosai-science-observe-v1.png", "xiaosai-science-observe-publication-v2.jpg"),
    (
        "xiaosai-science-experiment-v1.png",
        "xiaosai-science-experiment-publication-v2.jpg",
    ),
    ("xiaosai-science-reflect-v1.png", "xiaosai-science-reflect-publication-v2.jpg"),
    (
        "xiaosai-science-inquiry-cover-v1.png",
        "xiaosai-science-inquiry-cover-publication-v2.jpg",
    ),
)


def create_derivatives(asset_directory: Path) -> None:
    for source_name, target_name in ASSETS:
        source = asset_directory / source_name
        target = asset_directory / target_name
        with Image.open(source) as image:
            # Converting only pixel data deliberately drops EXIF, ICC, comments and text chunks.
            pixels = image.convert("RGB")
            pixels.save(
                target,
                format="JPEG",
                quality=QUALITY,
                subsampling=SUBSAMPLING,
                optimize=False,
                progressive=False,
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--asset-directory",
        type=Path,
        default=Path("docs/portfolio/assets/content-showcase"),
    )
    args = parser.parse_args()
    create_derivatives(args.asset_directory)


if __name__ == "__main__":
    main()
