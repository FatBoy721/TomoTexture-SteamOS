"""Generate .ugctex.zs and _Thumb.ugctex.zs companion files for canvas textures.

Adapted from farbensplasch/tomodachi-texture-tool (MIT).

The game expects three files per UGC item:
  - *.canvas.zs   — 256x256 RGBA swizzled (what app.py already writes)
  - *.ugctex.zs   — 512x512 DXT1 swizzled
  - *_Thumb.ugctex.zs — 256x256 DXT5 swizzled
"""

import io
import struct
from pathlib import Path

import zstandard as zstd
from PIL import Image, ImageOps

from swizzle import nsw_swizzle

SWIZZLE_MODE = 4
ZSTD_LEVEL = 16


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
    struct.pack_into("<I", hdr, 80, 0x4)   # DDPF_FOURCC
    hdr[84:88] = fourcc
    struct.pack_into("<I", hdr, 108, 0x1000)
    return bytes(hdr) + data


def png_to_ugctex(img: Image.Image) -> bytes:
    """Convert a PIL image to raw swizzled UGCTEX blob (512x512 DXT1)."""
    img = img.convert("RGBA")
    if img.size != (512, 512):
        img = ImageOps.fit(img, (512, 512), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="DDS", pixel_format="DXT1")
    dxt1_data = buf.getvalue()[128:]
    return bytes(nsw_swizzle(dxt1_data, (512, 512), (4, 4), 8, SWIZZLE_MODE))


def png_to_thumb(img: Image.Image) -> bytes:
    """Convert a PIL image to raw swizzled thumbnail blob (256x256 DXT5)."""
    img = img.convert("RGBA")
    if img.size != (256, 256):
        img = ImageOps.fit(img, (256, 256), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="DDS", pixel_format="DXT5")
    dxt5_data = buf.getvalue()[128:]
    return bytes(nsw_swizzle(dxt5_data, (256, 256), (4, 4), 16, 3))


def zstd_compress(data: bytes) -> bytes:
    return zstd.ZstdCompressor(level=ZSTD_LEVEL).compress(data)


def write_companion_files(img: Image.Image, canvas_path: Path) -> tuple[Path, Path]:
    """Write .ugctex.zs and _Thumb.ugctex.zs next to a .canvas.zs file.

    *img* should be the final RGBA image that was used for the canvas.
    Returns (ugctex_path, thumb_path).
    """
    stem = canvas_path.name.replace('.canvas.zs', '')
    parent = canvas_path.parent

    ugctex_path = parent / f"{stem}.ugctex.zs"
    thumb_path = parent / f"{stem}_Thumb.ugctex.zs"

    ugctex_data = zstd_compress(png_to_ugctex(img.copy()))
    thumb_data = zstd_compress(png_to_thumb(img.copy()))

    ugctex_path.write_bytes(ugctex_data)
    thumb_path.write_bytes(thumb_data)

    return ugctex_path, thumb_path
