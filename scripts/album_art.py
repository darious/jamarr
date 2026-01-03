#!/usr/bin/env python3
"""
export_jpg_scaled.py

Usage:
  python3 export_jpg_scaled.py /path/to/image.png

Requires:
  pip install pillow
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageFile


MAX_DIM = 2800
DPI = (72, 72)
ImageFile.LOAD_TRUNCATED_IMAGES = True


def build_output_path(input_path: Path) -> Path:
    # Always output as JPEG next to the original.
    # Suffix is "_scaled" even if no resize happened (per your request).
    return input_path.with_name(f"{input_path.stem}_scaled.jpg")


def convert_to_rgb(im: Image.Image) -> Image.Image:
    """
    JPEG doesn't support alpha. If there's transparency, composite over white.
    """
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        composited = Image.alpha_composite(background, rgba)
        return composited.convert("RGB")
    if im.mode != "RGB":
        return im.convert("RGB")
    return im


def resize_if_needed(im: Image.Image) -> tuple[Image.Image, bool]:
    w, h = im.size
    if w <= MAX_DIM and h <= MAX_DIM:
        return im, False

    # Resize to fit within MAX_DIM x MAX_DIM, preserving aspect ratio.
    im2 = im.copy()
    im2.thumbnail((MAX_DIM, MAX_DIM), Image.Resampling.LANCZOS)
    return im2, True


def save_jpeg_atomic(im: Image.Image, out_path: Path) -> None:
    """
    Save to a temporary file in the same directory then rename, to avoid partial outputs.
    """
    out_dir = out_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(prefix=out_path.stem + "_", suffix=".tmp", dir=str(out_dir))
    os.close(fd)
    tmp_path = Path(tmp_name)

    def _save_standard(img: Image.Image) -> None:
        img.save(
            tmp_path,
            format="JPEG",
            quality=100,           # screenshot: Quality 100
            optimize=True,         # screenshot: Optimise checked
            progressive=True,      # screenshot: Progressive checked
            subsampling=0,         # 4:4:4 (best quality)
            dpi=DPI,               # 72dpi
        )

    def _save_plain(img: Image.Image) -> None:
        img.save(tmp_path, format="JPEG", quality=95)

    try:
        try:
            _save_standard(im)
        except OSError:
            # Rebuild buffer and retry, then fall back to plain save.
            rebuilt = Image.frombytes(im.mode, im.size, im.tobytes())
            try:
                _save_standard(rebuilt)
            except OSError:
                _save_plain(rebuilt)
        tmp_path.replace(out_path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Export image to JPEG (max 2800px, 72dpi) and delete original.")
    parser.add_argument("image", type=Path, help="Path to the input image")
    args = parser.parse_args()

    in_path: Path = args.image

    if not in_path.exists():
        print(f"Error: file not found: {in_path}", file=sys.stderr)
        return 2
    if not in_path.is_file():
        print(f"Error: not a file: {in_path}", file=sys.stderr)
        return 2

    out_path = build_output_path(in_path)

    try:
        with Image.open(in_path) as im:
            im = convert_to_rgb(im)
            im, resized = resize_if_needed(im)

            save_jpeg_atomic(im, out_path)

        # Only delete original after successful save
        in_path.unlink()

        action = "Resized and exported" if resized else "Exported (no resize needed)"
        print(f"{action}: {out_path}")
        print(f"Deleted original: {in_path}")
        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        print("Original file NOT deleted.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
