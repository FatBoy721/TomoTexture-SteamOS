"""Nintendo Switch GOB swizzle/deswizzle.

Derived from Aclios/pyswizzle (MIT License) via farbensplasch/tomodachi-texture-tool.
Supports parameterized image sizes, block sizes, and swizzle modes for
RGBA (canvas), DXT1 (ugctex), and DXT5 (thumbnail) formats.
"""

import numpy as np

CANVAS_W = 256
CANVAS_H = 256
BPP = 4
BLOCK_HEIGHT_GOBS = 16
GOB_W = 64
GOB_H = 8
RAW_SIZE = CANVAS_W * CANVAS_H * BPP


def _build_lut(width: int, height: int, bpp: int, block_height_gobs: int) -> np.ndarray:
    gobs_per_row = (width * bpp) // GOB_W
    block_bytes = GOB_W * GOB_H * block_height_gobs
    block_rows_px = GOB_H * block_height_gobs

    y = np.arange(height)[:, None]
    xb = np.arange(width * bpp)[None, :]

    block_y = y // block_rows_px
    y_in_block = y % block_rows_px
    gob_y_in_block = y_in_block // GOB_H
    y_in_gob = y_in_block % GOB_H

    block_x = xb // GOB_W
    x_in_gob = xb % GOB_W

    block_off = (block_y * gobs_per_row + block_x) * block_bytes
    gob_off_in_block = gob_y_in_block * GOB_W * GOB_H

    off_in_gob = (
        ((x_in_gob & 32) << 3)
        | ((y_in_gob & 6) << 5)
        | ((x_in_gob & 16) << 1)
        | ((y_in_gob & 1) << 4)
        | (x_in_gob & 15)
    )

    return (block_off + gob_off_in_block + off_in_gob).ravel().astype(np.int64)


_LUT = _build_lut(CANVAS_W, CANVAS_H, BPP, BLOCK_HEIGHT_GOBS)


def swizzle(linear_rgba: bytes) -> bytes:
    """Swizzle 256x256 RGBA linear data (legacy canvas-only API)."""
    if len(linear_rgba) != RAW_SIZE:
        raise ValueError(f"expected {RAW_SIZE} bytes, got {len(linear_rgba)}")
    src = np.frombuffer(linear_rgba, dtype=np.uint8)
    out = np.empty_like(src)
    out[_LUT] = src
    return out.tobytes()


def deswizzle(swizzled: bytes) -> bytes:
    """Deswizzle 256x256 RGBA swizzled data (legacy canvas-only API)."""
    if len(swizzled) != RAW_SIZE:
        raise ValueError(f"expected {RAW_SIZE} bytes, got {len(swizzled)}")
    src = np.frombuffer(swizzled, dtype=np.uint8)
    return src[_LUT].tobytes()


# ---------------------------------------------------------------------------
# General-purpose swizzle/deswizzle for arbitrary sizes and block formats
# (DXT1, DXT5, RGBA etc.) — ported from farbensplasch/tomodachi-texture-tool
# ---------------------------------------------------------------------------

def nsw_swizzle(data, im_size, block_size, bytes_per_block, swizzle_mode):
    return _BytesSwizzle(data, im_size, block_size, bytes_per_block, swizzle_mode).swizzle()


def nsw_deswizzle(data, im_size, block_size, bytes_per_block, swizzle_mode):
    return _BytesDeswizzle(data, im_size, block_size, bytes_per_block, swizzle_mode).deswizzle()


class _BytesSwizzle:
    def __init__(self, data, im_size, block_size, bytes_per_block, swizzle_mode):
        self.data = data
        datasize = len(data)
        im_width, im_height = im_size
        block_width, block_height = block_size

        expected = (im_width * im_height) // (block_width * block_height) * bytes_per_block
        if expected != datasize:
            raise ValueError(f"Invalid data size: expected {expected}, got {datasize}")

        tile_datasize = 512 * (2 ** swizzle_mode)
        tile_width = 64 // bytes_per_block * block_width
        tile_height = 8 * block_height * (2 ** swizzle_mode)

        if datasize % tile_datasize != 0:
            raise ValueError(f"Data size must be a multiple of {tile_datasize}")
        if im_width % tile_width != 0:
            raise ValueError(f"Image width must be a multiple of {tile_width}")
        if im_height % tile_height != 0:
            raise ValueError(f"Image height must be a multiple of {tile_height}")

        self.swizzle_ops = [(2 ** swizzle_mode, 0), (2, 1), (4, 0), (2, 1), (2, 0)]
        self.read_size = 16
        self.column_count = (bytes_per_block * im_width) // (block_width * 16)
        self.tile_per_width = im_width // tile_width
        self.tile_per_height = im_height // tile_height
        self.row_count = im_height // block_height

    def _to_array(self):
        idx = 0
        array = None
        for i in range(self.row_count):
            row = []
            for _ in range(self.column_count):
                row.append(self.data[idx: idx + self.read_size])
                idx += self.read_size
            arr_row = np.array([row], dtype=np.void)
            array = arr_row if array is None else np.vstack((array, arr_row))
        return array

    @staticmethod
    def _split(arrays, n, axis):
        result = []
        for a in arrays:
            result.extend(np.split(a, n, axis))
        return result

    def swizzle(self):
        out = bytearray()
        tiles = self._split([self._to_array()], self.tile_per_height, 0)
        tiles = self._split(tiles, self.tile_per_width, 1)
        for tile in tiles:
            parts = [tile]
            for n, axis in self.swizzle_ops:
                parts = self._split(parts, n, axis)
            for block in parts:
                out += block[0][0].item()
        return bytes(out)


class _BytesDeswizzle:
    def __init__(self, data, im_size, block_size, bytes_per_block, swizzle_mode):
        self.data = data
        datasize = len(data)
        im_width, im_height = im_size
        block_width, block_height = block_size

        expected = (im_width * im_height) // (block_width * block_height) * bytes_per_block
        if expected != datasize:
            raise ValueError(f"Invalid data size: expected {expected}, got {datasize}")

        tile_datasize = 512 * (2 ** swizzle_mode)
        tile_width = 64 // bytes_per_block * block_width
        tile_height = 8 * block_height * (2 ** swizzle_mode)

        self.deswizzle_ops = [(2, 0), (2, 1), (4, 0), (2, 1), (2 ** swizzle_mode, 0)]
        self.read_size = 16
        self.read_per_tile = 32 * (2 ** swizzle_mode)
        self.tile_count = datasize // tile_datasize
        self.tile_per_width = im_width // tile_width
        self.data_idx = 0

    def _read_tile(self):
        parts = []
        for _ in range(self.read_per_tile):
            parts.append(np.array([[self.data[self.data_idx: self.data_idx + self.read_size]]], dtype=np.void))
            self.data_idx += self.read_size
        return parts

    @staticmethod
    def _concat(arrays, n, axis):
        result = []
        for i in range(0, len(arrays), n):
            result.append(np.concatenate(arrays[i: i + n], axis=axis))
        return result

    def _deswizzle_tile(self):
        parts = self._read_tile()
        for n, axis in self.deswizzle_ops:
            parts = self._concat(parts, n, axis)
        return parts[0]

    def deswizzle(self):
        tiles = [self._deswizzle_tile() for _ in range(self.tile_count)]
        rows = self._concat(tiles, self.tile_per_width, 1)
        full = self._concat(rows, len(rows), 0)[0]
        return full.tobytes()
