"""Small authored binary fixtures, generated without image dependencies."""
import base64
import struct
import zlib


def chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xffffffff)


def png(width=2, height=2, metadata=False):
    head = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = (b"\0" + b"\x45\x70\xe0" * width) * height
    extra = chunk(b"tEXt", b"author\0PRIVATE_SENTINEL") if metadata else b""
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head) + extra + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def pack(seed):
    return {"format": "seekmemory.persona-pack/v1", "seed": seed,
            "licenseText": "CC0-1.0. Test artwork and persona are original fixtures.",
            "artwork": {"mediaType": "image/png", "dataBase64": base64.b64encode(png()).decode()}}
