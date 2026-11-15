"""Convert pictures and GIFs into the byte formats the L99 screen stores in flash.

Still image (written at STILL_ADDR):
    u32 pixel_bytes | u16 width | u16 height | u8 0x00 | u16 crc16(pixels) | RGB565 LE pixels

Animation (written at GIF_ADDR):
    table: one 20-byte entry per frame
        u32 frame_offset | u32 body_size | u16 w | u16 h | u8 0x03 | u8 frame_count
        | u16 0 | u16 delay_ms | u16 crc16(body)
    body: per frame
        "LT" | u16 w | u16 h | u8 0x01 | u8 0x03 | u32 frame_size | u32 pixel_count
        | 256 x RGB565 LE palette | w*h palette indices
All integers little-endian; crc16 is CRC-16/MODBUS.
"""
from __future__ import annotations

from typing import Iterable, Sequence

from PIL import Image, ImageOps, ImageSequence

from .protocol import crc16_modbus

W, H = 320, 480
# The official software sent 15 frames. Flash beyond that is untested, so stay there
# by default: other firmware data may live after the animation area.
MAX_FRAMES = 15
MIN_DELAY_MS = 20

FIT_MODES = ("cover", "contain", "stretch")


def fit(img: Image.Image, mode: str = "cover", rotate: int = 0,
        background=(0, 0, 0)) -> Image.Image:
    img = img.convert("RGBA")
    if rotate:
        img = img.rotate(-rotate, expand=True)
    if mode == "stretch":
        out = img.resize((W, H), Image.LANCZOS)
    elif mode == "contain":
        out = ImageOps.contain(img, (W, H), Image.LANCZOS)
    elif mode == "cover":
        out = ImageOps.fit(img, (W, H), Image.LANCZOS)
    else:
        raise ValueError(f"fit mode must be one of {FIT_MODES}")
    canvas = Image.new("RGBA", (W, H), background + (255,))
    canvas.alpha_composite(out, ((W - out.width) // 2, (H - out.height) // 2))
    return canvas.convert("RGB")


def to_rgb565(r: int, g: int, b: int) -> int:
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def encode_still(img: Image.Image) -> bytes:
    if img.size != (W, H):
        raise ValueError(f"image must be {W}x{H}, got {img.size}")
    px = bytearray(W * H * 2)
    for i, (r, g, b) in enumerate(img.convert("RGB").getdata()):
        v = to_rgb565(r, g, b)
        px[2 * i] = v & 0xFF
        px[2 * i + 1] = v >> 8
    px = bytes(px)
    return (len(px).to_bytes(4, "little") + W.to_bytes(2, "little") + H.to_bytes(2, "little")
            + b"\x00" + crc16_modbus(px).to_bytes(2, "little") + px)


def _frame_record(palette565: Sequence[int], indices: bytes) -> bytes:
    pal = b"".join(v.to_bytes(2, "little") for v in palette565)
    pal = pal.ljust(512, b"\x00")
    size = 16 + len(pal) + len(indices)
    return (b"LT" + W.to_bytes(2, "little") + H.to_bytes(2, "little") + b"\x01\x03"
            + size.to_bytes(4, "little") + len(indices).to_bytes(4, "little") + pal + indices)


def quantize(frame: Image.Image) -> tuple[list[int], bytes]:
    q = frame.convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT,
                                      dither=Image.Dither.FLOYDSTEINBERG)
    flat = q.getpalette()[:768]
    pal = [to_rgb565(*flat[i:i + 3]) for i in range(0, len(flat), 3)]
    return pal, q.tobytes()


def encode_frames(frames: Sequence[tuple[list[int], bytes]], delays_ms: Sequence[int]) -> bytes:
    n = len(frames)
    if not 1 <= n <= 255:
        raise ValueError("need 1..255 frames")
    records = [_frame_record(p, idx) for p, idx in frames]
    body = b"".join(records)
    crc = crc16_modbus(body)
    table = bytearray()
    off = 20 * n
    for rec, delay in zip(records, delays_ms):
        table += (off.to_bytes(4, "little") + len(body).to_bytes(4, "little")
                  + W.to_bytes(2, "little") + H.to_bytes(2, "little") + bytes([0x03, n])
                  + b"\x00\x00" + max(1, min(int(delay), 0xFFFF)).to_bytes(2, "little")
                  + crc.to_bytes(2, "little"))
        off += len(rec)
    return bytes(table) + body


def load_animation(path: str, mode: str = "cover", rotate: int = 0,
                   max_frames: int = MAX_FRAMES, delay_ms: int | None = None
                   ) -> tuple[list[Image.Image], list[int]]:
    """Read every frame, then pick at most max_frames evenly, keeping total play time."""
    src = Image.open(path)
    frames, durs = [], []
    for fr in ImageSequence.Iterator(src):
        frames.append(fit(fr.copy(), mode, rotate))
        durs.append(int(fr.info.get("duration", src.info.get("duration", 100)) or 100))
    n = len(frames)
    if n > max_frames:
        picks = [round(i * n / max_frames) for i in range(max_frames)]
        bounds = picks[1:] + [n]
        frames = [frames[p] for p in picks]
        durs = [sum(durs[a:b]) for a, b in zip(picks, bounds)]
    if delay_ms:
        durs = [delay_ms] * len(frames)
    return frames, [max(MIN_DELAY_MS, d) for d in durs]


def encode_animation(frames: Iterable[Image.Image], delays_ms: Sequence[int]) -> bytes:
    return encode_frames([quantize(f) for f in frames], delays_ms)
