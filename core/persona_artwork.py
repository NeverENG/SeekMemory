"""Validate bounded static PNG bytes without filesystem or host dependencies.

校验有大小上限的静态 PNG 字节，不依赖文件系统或宿主。
"""
from __future__ import annotations

import struct
import zlib

MAX_ARTWORK_BYTES = 2 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def validate_artwork(data: bytes) -> bytes:
    """Validate static non-interlaced 8-bit PNG data and strip ancillary metadata.

    校验静态非交错 8 位 PNG 数据并移除辅助元数据。
    """
    if not 0 < len(data) <= MAX_ARTWORK_BYTES or not data.startswith(PNG_SIGNATURE):
        raise ValueError("封面必须是 2 MiB 以内的静态 PNG")
    position, width, height, color = 8, 0, 0, -1
    chunks, pixels = [], bytearray()
    seen, ended, idat_closed = set(), False, False
    while position < len(data):
        if position + 12 > len(data):
            raise ValueError("PNG 文件不完整")
        size = struct.unpack_from(">I", data, position)[0]
        kind = data[position + 4:position + 8]
        end = position + size + 12
        if end > len(data):
            raise ValueError("PNG 数据长度无效")
        body = data[position + 8:end - 4]
        crc = struct.unpack_from(">I", data, end - 4)[0]
        if zlib.crc32(kind + body) & 0xffffffff != crc:
            raise ValueError("PNG 校验失败")
        if not seen and kind != b"IHDR":
            raise ValueError("PNG 缺少图像头")
        if kind in {b"acTL", b"fcTL", b"fdAT"}:
            raise ValueError("封面暂不支持动画 PNG")
        if kind == b"IHDR":
            if seen or size != 13:
                raise ValueError("PNG 图像头无效")
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", body)
            if not (1 <= width <= 2048 and 1 <= height <= 2048 and width * height <= 4_000_000):
                raise ValueError("封面尺寸不能超过 2048×2048 或 400 万像素")
            if depth != 8 or color not in {0, 2, 3, 4, 6} or compression or filtering or interlace:
                raise ValueError("封面需要 8 位、非交错 PNG；请重新导出图片")
        elif kind == b"PLTE":
            if kind in seen or b"IDAT" in seen or color in {0, 4} or not 0 < size <= 768 or size % 3:
                raise ValueError("PNG 调色板无效")
        elif kind == b"tRNS":
            if kind in seen or b"IDAT" in seen or color in {4, 6}:
                raise ValueError("PNG 透明度无效")
            palette = next((len(chunk) - 12 for tag, chunk in chunks if tag == b"PLTE"), 0) // 3
            if not ((color == 0 and size == 2) or (color == 2 and size == 6) or (color == 3 and 0 < size <= palette)):
                raise ValueError("PNG 透明度长度无效")
        elif kind == b"IDAT":
            if idat_closed or (color == 3 and b"PLTE" not in seen):
                raise ValueError("PNG 图像数据顺序无效")
            pixels.extend(body)
        elif kind == b"IEND":
            if size or b"IDAT" not in seen or end != len(data):
                raise ValueError("PNG 结束标记无效")
            ended = True
        elif len(kind) != 4 or not all(65 <= x <= 90 or 97 <= x <= 122 for x in kind) or not kind[0] & 32:
            raise ValueError("不支持的 PNG 数据块")
        if b"IDAT" in seen and kind != b"IDAT":
            idat_closed = True
        if kind in {b"IHDR", b"PLTE", b"tRNS", b"IDAT", b"IEND"}:
            chunks.append((kind, data[position:end]))
        seen.add(kind)
        position = end
    if not ended:
        raise ValueError("PNG 文件不完整")
    stride = width * {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color] + 1
    expected = height * stride
    try:
        decoder = zlib.decompressobj()
        decoded = decoder.decompress(bytes(pixels), expected + 1)
        if len(decoded) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError("PNG 像素数据无效")
        if any(decoded[index] > 4 for index in range(0, expected, stride)):
            raise ValueError("PNG 行过滤器无效")
    except zlib.error as exc:
        raise ValueError("PNG 像素数据损坏") from exc
    return PNG_SIGNATURE + b"".join(chunk for _, chunk in chunks)
