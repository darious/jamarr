#!/usr/bin/env python3
"""
export_jpg_scaled.py

Usage:
  python3 export_jpg_scaled.py /path/to/folder
  python3 export_jpg_scaled.py /path/to/image.jpg

Requires:
  pip install pillow
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import Iterable

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


def is_supported_image(path: Path) -> bool:
    return path.suffix.lower() in {".jpg", ".jpeg", ".png"}


def iter_images(root: Path) -> Iterable[Path]:
    if root.is_file():
        return [root] if is_supported_image(root) else []
    return (
        p
        for p in root.rglob("*")
        if p.is_file() and is_supported_image(p) and not p.stem.endswith("_scaled")
    )


def process_image(in_path: Path) -> bool:
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
        return True

    except Exception as e:
        print(f"Error processing {in_path}: {e}", file=sys.stderr)
        print("Original file NOT deleted.", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export all JPG/JPEG/PNG images under a path to JPEG (max 2800px, 72dpi) and delete originals."
    )
    parser.add_argument("path", type=Path, help="Path to an image file or directory to search")
    args = parser.parse_args()

    root: Path = args.path

    if not root.exists():
        print(f"Error: path not found: {root}", file=sys.stderr)
        return 2

    images = list(iter_images(root))
    if not images:
        print(f"No JPG/JPEG/PNG images found under {root}")
        return 0

    failures = 0
    for img_path in images:
        if not process_image(img_path):
            failures += 1

    if failures:
        print(f"Completed with {failures} failure(s). See errors above.", file=sys.stderr)
        return 1

    print(f"Processed {len(images)} image(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
