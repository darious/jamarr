"""Artwork resizing: output geometry, transparency, atomic publication and
request coalescing (#317, #318). No DB, no HTTP."""
import asyncio
import os
import threading
import time

import pytest
from PIL import Image

from app.media import art


def _write(path, img, fmt, **kw):
    img.save(path, format=fmt, **kw)
    return str(path)


def _jpeg_bytes(path):
    with open(path, "rb") as f:
        data = f.read()
    assert data.startswith(b"\xff\xd8\xff"), "not a JPEG"
    return data


# ---------------------------------------------------------------- geometry


@pytest.mark.parametrize(
    "size,target,expected",
    [
        ((1200, 1200), 600, (600, 600)),
        ((1200, 600), 600, (600, 300)),
        ((600, 1200), 300, (150, 300)),
        ((10000, 1), 600, (600, 1)),
        ((1, 10000), 600, (1, 600)),
        ((3, 4000), 100, (1, 100)),
        ((500, 500), 600, (500, 500)),  # never upscale
        ((1, 1), 100, (1, 1)),
        ((601, 599), 600, (600, 598)),
    ],
)
def test_fit_within_preserves_aspect_and_never_hits_zero(size, target, expected):
    assert art._fit_within(*size, target) == expected


# ---------------------------------------------------------------- encoding


def test_transparent_rgba_is_flattened_onto_white_after_resize(tmp_path):
    img = Image.new("RGBA", (1600, 1600), (0, 0, 0, 0))
    # Opaque red square in the middle, transparent border.
    for x in range(400, 1200):
        for y in range(400, 1200):
            img.putpixel((x, y), (255, 0, 0, 255))
    src = _write(tmp_path / "a.png", img, "PNG")
    dst = str(tmp_path / "out")

    art._create_resized(src, dst, 400)

    with Image.open(dst) as out:
        assert out.format == "JPEG" and out.mode == "RGB" and out.size == (400, 400)
        r, g, b = out.getpixel((5, 5))
        assert r > 240 and g > 240 and b > 240, "transparent border must be white"
        r, g, b = out.getpixel((200, 200))
        assert r > 200 and g < 60 and b < 60, "opaque centre must stay red"


def test_alpha_edge_has_no_dark_fringe(tmp_path):
    # Soft edge: alpha ramps 0 -> 255 across the middle columns. A resize that
    # ignored premultiplication would drag the (0,0,0,0) colour into the ramp.
    img = Image.new("RGBA", (1200, 200), (0, 0, 0, 0))
    for x in range(1200):
        a = max(0, min(255, (x - 500) * 255 // 200))
        for y in range(200):
            img.putpixel((x, y), (255, 255, 255, a))
    src = _write(tmp_path / "ramp.png", img, "PNG")
    dst = str(tmp_path / "out")

    art._create_resized(src, dst, 300)

    with Image.open(dst) as out:
        assert out.size == (300, 50)
        # Every pixel is white-on-white: nothing darker than near-white.
        assert min(out.getextrema(), key=lambda lo_hi: lo_hi[0])[0] > 235


def test_palette_png_with_transparency(tmp_path):
    img = Image.new("P", (900, 900))
    img.putpalette([0, 0, 255] + [0, 128, 0] + [0] * 762)
    for x in range(300, 600):
        for y in range(300, 600):
            img.putpixel((x, y), 1)
    img.info["transparency"] = 0  # index 0 (blue) is transparent
    src = _write(tmp_path / "p.png", img, "PNG", transparency=0)
    dst = str(tmp_path / "out")

    art._create_resized(src, dst, 300)

    with Image.open(dst) as out:
        assert out.mode == "RGB" and out.size == (300, 300)
        assert min(out.getpixel((10, 10))) > 240, "transparent index must become white"
        r, g, b = out.getpixel((150, 150))
        assert g > 100 and r < 40 and b < 40


def test_palette_png_without_transparency_keeps_its_colour(tmp_path):
    img = Image.new("P", (800, 400))
    img.putpalette([200, 30, 30] + [0] * 765)
    src = _write(tmp_path / "p.png", img, "PNG")
    dst = str(tmp_path / "out")

    art._create_resized(src, dst, 200)

    with Image.open(dst) as out:
        assert out.size == (200, 100)
        r, g, b = out.getpixel((100, 50))
        assert r > 180 and g < 60 and b < 60


@pytest.mark.parametrize("mode", ["L", "LA", "CMYK", "I;16", "1"])
def test_other_modes_become_rgb_jpegs(tmp_path, mode):
    img = Image.new(mode, (700, 700))
    fmt = "PNG" if mode in ("L", "LA", "I;16", "1") else "JPEG"
    src = _write(tmp_path / f"m.{fmt.lower()}", img, fmt)
    dst = str(tmp_path / "out")

    art._create_resized(src, dst, 100)

    with Image.open(dst) as out:
        assert out.format == "JPEG" and out.mode == "RGB" and out.size == (100, 100)


def test_large_jpeg_is_decoded_reduced_and_lands_on_exact_size(tmp_path):
    img = Image.new("RGB", (4000, 3000), (10, 200, 10))
    src = _write(tmp_path / "big.jpg", img, "JPEG", quality=70)
    dst = str(tmp_path / "out")

    art._create_resized(src, dst, 600)

    with Image.open(dst) as out:
        assert out.size == (600, 450)
        r, g, b = out.getpixel((300, 225))
        assert g > 180 and r < 40 and b < 40


def test_extreme_aspect_ratio_and_tiny_images(tmp_path):
    banner = _write(tmp_path / "banner.png", Image.new("RGB", (8000, 3), "white"), "PNG")
    dot = _write(tmp_path / "dot.png", Image.new("RGB", (1, 1), "white"), "PNG")
    small = _write(tmp_path / "small.jpg", Image.new("RGB", (80, 50), "white"), "JPEG")

    art._create_resized(banner, str(tmp_path / "o1"), 600)
    art._create_resized(dot, str(tmp_path / "o2"), 100)
    art._create_resized(small, str(tmp_path / "o3"), 300)

    with Image.open(tmp_path / "o1") as o:
        assert o.size == (600, 1)
    with Image.open(tmp_path / "o2") as o:
        assert o.size == (1, 1)
    with Image.open(tmp_path / "o3") as o:
        assert o.size == (80, 50), "small images are not upscaled"


# ---------------------------------------------------------------- atomic publish


def test_failed_encode_publishes_nothing_and_retry_succeeds(tmp_path):
    src = tmp_path / "x.png"
    src.write_bytes(b"not an image at all")
    dst = tmp_path / "resized" / "20" / "key"

    with pytest.raises(Exception):
        art._create_resized(str(src), str(dst), 200)

    assert not dst.exists()
    assert os.listdir(dst.parent) == [], "no staging file may be left behind"

    Image.new("RGB", (400, 400), "blue").save(src, format="PNG")
    art._create_resized(str(src), str(dst), 200)
    _jpeg_bytes(dst)


def test_publish_is_rename_into_place(tmp_path, monkeypatch):
    """The final path only ever appears complete: the bytes are written to a
    staging file in the same directory and renamed in one step."""
    src = _write(tmp_path / "a.png", Image.new("RGB", (500, 500), "red"), "PNG")
    dst = tmp_path / "out"
    seen = []
    real_replace = os.replace

    def spy_replace(a, b):
        seen.append((os.path.basename(a), b, dst.exists(), os.path.getsize(a)))
        real_replace(a, b)

    monkeypatch.setattr(art.os, "replace", spy_replace)
    art._create_resized(src, str(dst), 300)

    (staging, final, existed_before, staged_size), = seen
    assert staging.startswith(".out.") and staging.endswith(".tmp")
    assert final == str(dst) and not existed_before and staged_size > 0
    assert staged_size == dst.stat().st_size


def test_existing_file_is_not_rewritten(tmp_path):
    """Another process published it while we queued: leave it alone."""
    src = _write(tmp_path / "a.png", Image.new("RGB", (500, 500), "red"), "PNG")
    dst = tmp_path / "out"
    dst.write_bytes(b"\xff\xd8\xffpublished-by-someone-else")

    art._create_resized(src, str(dst), 300)

    assert dst.read_bytes() == b"\xff\xd8\xffpublished-by-someone-else"


# ---------------------------------------------------------------- coalescing


class _Counter:
    """Replacement for _create_resized that records concurrency."""

    def __init__(self, delay=0.15, fail=False):
        self.delay, self.fail = delay, fail
        self.calls, self.active, self.peak = [], 0, 0
        self._lock = threading.Lock()

    def __call__(self, original_path, resized_path, target_size):
        with self._lock:
            self.calls.append(resized_path)
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(self.delay)
            if self.fail:
                raise OSError("disk on fire")
            os.makedirs(os.path.dirname(resized_path), exist_ok=True)
            with open(resized_path, "wb") as f:
                f.write(b"\xff\xd8\xff" + os.path.basename(resized_path).encode())
        finally:
            with self._lock:
                self.active -= 1


@pytest.fixture
def fresh_pool(monkeypatch):
    """A new, small resize pool per test and an empty in-flight table."""
    monkeypatch.setattr(art, "_resize_pool", None)
    monkeypatch.setattr(art, "_inflight", {})
    monkeypatch.setattr(art, "get_art_resize_workers", lambda: 2)
    yield
    if art._resize_pool is not None:
        art._resize_pool.shutdown(wait=True)


@pytest.mark.asyncio
async def test_concurrent_requests_for_one_key_resize_once(tmp_path, fresh_pool, monkeypatch):
    counter = _Counter()
    monkeypatch.setattr(art, "_create_resized", counter)
    dst = str(tmp_path / "200" / "k")

    await asyncio.gather(*(art.ensure_resized("src", dst, 200) for _ in range(8)))

    assert counter.calls == [dst]
    assert art._inflight == {}, "completed work is forgotten"
    with open(dst, "rb") as f:
        assert f.read() == b"\xff\xd8\xffk"


@pytest.mark.asyncio
async def test_different_keys_run_concurrently_but_bounded(tmp_path, fresh_pool, monkeypatch):
    counter = _Counter(delay=0.2)
    monkeypatch.setattr(art, "_create_resized", counter)
    keys = [str(tmp_path / "300" / f"k{i}") for i in range(6)]

    t0 = time.monotonic()
    await asyncio.gather(*(art.ensure_resized("src", k, 300) for k in keys))
    elapsed = time.monotonic() - t0

    assert sorted(counter.calls) == sorted(keys)
    assert counter.peak == 2, "distinct keys overlap, up to the configured limit"
    assert elapsed < 6 * 0.2, "they did not run one after another"


@pytest.mark.asyncio
async def test_cancelled_waiter_does_not_strand_the_others(tmp_path, fresh_pool, monkeypatch):
    counter = _Counter(delay=0.3)
    monkeypatch.setattr(art, "_create_resized", counter)
    dst = str(tmp_path / "100" / "k")

    first = asyncio.ensure_future(art.ensure_resized("src", dst, 100))
    await asyncio.sleep(0.05)
    second = asyncio.ensure_future(art.ensure_resized("src", dst, 100))
    await asyncio.sleep(0.05)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    await second  # completes normally
    assert counter.calls == [dst]
    assert os.path.isfile(dst)


@pytest.mark.asyncio
async def test_failure_reaches_every_waiter_and_the_next_request_retries(
    tmp_path, fresh_pool, monkeypatch
):
    counter = _Counter(delay=0.05, fail=True)
    monkeypatch.setattr(art, "_create_resized", counter)
    dst = str(tmp_path / "100" / "k")

    results = await asyncio.gather(
        *(art.ensure_resized("src", dst, 100) for _ in range(3)), return_exceptions=True
    )
    assert all(isinstance(r, OSError) for r in results)
    assert counter.calls == [dst]
    assert art._inflight == {}

    counter.fail = False
    await art.ensure_resized("src", dst, 100)
    assert counter.calls == [dst, dst], "a later request gets a fresh attempt"
    assert os.path.isfile(dst)


def test_resize_worker_default_and_overrides(monkeypatch):
    from app import config

    monkeypatch.delenv("ART_RESIZE_WORKERS", raising=False)
    monkeypatch.setattr(config, "load_config", lambda: {})
    assert config.get_art_resize_workers() == 2
    monkeypatch.setattr(config, "load_config", lambda: {"artwork": {"resize_workers": 5}})
    assert config.get_art_resize_workers() == 5
    monkeypatch.setenv("ART_RESIZE_WORKERS", "0")
    assert config.get_art_resize_workers() == 1
    monkeypatch.setenv("ART_RESIZE_WORKERS", "nope")
    assert config.get_art_resize_workers() == 2
