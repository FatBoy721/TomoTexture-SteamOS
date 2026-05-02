"""Generate .ugctex.zs and _Thumb.ugctex.zs companion files for canvas textures.

Adapted from farbensplasch/tomodachi-texture-tool (MIT).

The game expects three files per UGC item:
  - *.canvas.zs
  - *.ugctex.zs   - 512x512 DXT1 swizzled, or 384x384 DXT1 for some foods
  - *_Thumb_ugctex.zs - 256x256 DXT5 swizzled
"""

import io
import struct
from pathlib import Path

import numpy as np
import zstandard as zstd
from PIL import Image, ImageOps

ZSTD_LEVEL = 16
ALPHA_CUTOFF = 20
DEFAULT_UGCTEX_SIZE = (512, 512)
FOOD_UGCTEX_SIZE = (384, 384)
THUMB_SIZE = (256, 256)


def _div_round_up(n: int, d: int) -> int:
    return (n + d - 1) // d


def _make_dds_header(data: bytes, w: int, h: int, fourcc: bytes) -> bytes:
    hdr = bytearray(128)
    hdr[0:4] = b"DDS "
    struct.pack_into("<I", hdr,  4, 124)
    struct.pack_into("<I", hdr,  8, 0x1 | 0x2 | 0x4 | 0x1000)
    struct.pack_into("<I", hdr, 12, h)
    struct.pack_into("<I", hdr, 16, w)
    struct.pack_into("<I", hdr, 20, len(data))
    struct.pack_into("<I", hdr, 28, 1)
    struct.pack_into("<I", hdr, 76, 32)
    struct.pack_into("<I", hdr, 80, 0x4)
    hdr[84:88] = fourcc
    struct.pack_into("<I", hdr, 108, 0x1000)
    return bytes(hdr) + data


def _gob_address(x: int, y: int, width_in_gobs: int,
                 bytes_per_element: int, block_height: int) -> int:
    x_bytes = x * bytes_per_element
    return (
        (y // (8 * block_height)) * 512 * block_height * width_in_gobs
        + (x_bytes // 64) * 512 * block_height
        + ((y % (8 * block_height)) // 8) * 512
        + ((x_bytes % 64) // 32) * 256
        + ((y % 8) // 2) * 64
        + ((x_bytes % 32) // 16) * 32
        + (y % 2) * 16
        + (x_bytes % 16)
    )


def _swizzle_block_linear(data: bytes, width: int, height: int,
                          bytes_per_element: int, block_height: int) -> bytes:
    width_in_gobs = _div_round_up(width * bytes_per_element, 64)
    padded_height = _div_round_up(height, 8 * block_height) * (8 * block_height)
    padded_size = width_in_gobs * padded_height * 64
    output = bytearray(padded_size)

    for y in range(height):
        for x in range(width):
            linear = (y * width + x) * bytes_per_element
            swizzled = _gob_address(x, y, width_in_gobs, bytes_per_element, block_height)
            output[swizzled:swizzled + bytes_per_element] = data[linear:linear + bytes_per_element]

    return bytes(output)


def _clean_alpha_pixels(img: Image.Image) -> Image.Image:
    arr = np.array(img.convert("RGBA"), dtype=np.uint8)
    arr[arr[..., 3] < ALPHA_CUTOFF, 3] = 0
    arr[arr[..., 3] > 0, 3] = 255
    arr[arr[..., 3] == 0] = 0
    return Image.fromarray(arr, mode="RGBA")


def _srgb_to_linear_image(img: Image.Image) -> Image.Image:
    arr = np.array(img.convert("RGBA"), dtype=np.uint8)
    rgb = arr[..., :3].astype(np.float32) / 255.0
    linear = np.where(
        rgb <= 0.04045,
        rgb / 12.92,
        ((rgb + 0.055) / 1.055) ** 2.4,
    )
    arr[..., :3] = np.clip(np.rint(linear * 255.0), 0, 255).astype(np.uint8)
    return Image.fromarray(arr, mode="RGBA")


def _detect_ugctex_size(ugctex_path: Path) -> tuple[int, int]:
    if ugctex_path.exists():
        try:
            raw_size = len(zstd.ZstdDecompressor().decompress(ugctex_path.read_bytes()))
            if raw_size == 98304:
                return FOOD_UGCTEX_SIZE
            if raw_size == 131072:
                return DEFAULT_UGCTEX_SIZE
        except Exception:
            pass

    if ugctex_path.name.startswith("UgcFood000"):
        return FOOD_UGCTEX_SIZE
    return DEFAULT_UGCTEX_SIZE


def png_to_ugctex(img: Image.Image, target_size: tuple[int, int] = DEFAULT_UGCTEX_SIZE) -> bytes:
    img = img.convert("RGBA")
    if img.size != target_size:
        img = ImageOps.fit(img, target_size, Image.LANCZOS)
    img = _clean_alpha_pixels(img)
    img = _srgb_to_linear_image(img)
    buf = io.BytesIO()
    img.save(buf, format="DDS", pixel_format="DXT1")
    dxt1_data = buf.getvalue()[128:]
    return _swizzle_block_linear(
        dxt1_data,
        target_size[0] // 4,
        target_size[1] // 4,
        8,
        16,
    )


def png_to_thumb(img: Image.Image) -> bytes:
    img = img.convert("RGBA")
    if img.size != THUMB_SIZE:
        img = ImageOps.fit(img, THUMB_SIZE, Image.LANCZOS)
    img = _clean_alpha_pixels(img)
    img = _srgb_to_linear_image(img)
    buf = io.BytesIO()
    img.save(buf, format="DDS", pixel_format="DXT5")
    dxt5_data = buf.getvalue()[128:]
    return _swizzle_block_linear(dxt5_data, 64, 64, 16, 8)


def zstd_compress(data: bytes) -> bytes:
    return zstd.ZstdCompressor(level=ZSTD_LEVEL).compress(data)


def write_companion_files(img: Image.Image, canvas_path: Path) -> tuple[Path, Path]:
    stem = canvas_path.name.replace('.canvas.zs', '')
    parent = canvas_path.parent

    ugctex_path = parent / f"{stem}.ugctex.zs"
    thumb_underscore = parent / f"{stem}_Thumb_ugctex.zs"
    thumb_dot = parent / f"{stem}_Thumb.ugctex.zs"
    thumb_path = thumb_dot if thumb_dot.exists() and not thumb_underscore.exists() else thumb_underscore

    ugctex_data = zstd_compress(png_to_ugctex(img.copy(), _detect_ugctex_size(ugctex_path)))
    thumb_data = zstd_compress(png_to_thumb(img.copy()))

    ugctex_path.write_bytes(ugctex_data)
    thumb_path.write_bytes(thumb_data)

    return ugctex_path, thumb_path
