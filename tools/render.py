"""Render the captured still image and GIF frames to PNGs, and probe remaining checksums."""
import zlib
from PIL import Image

W, H = 320, 480

def modbus(data, init=0xFFFF):
    crc = init
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc

def rgb565(v):
    r, g, b = (v >> 11) & 0x1F, (v >> 5) & 0x3F, v & 0x1F
    return (r << 3 | r >> 2, g << 2 | g >> 4, b << 3 | b >> 2)

still = open("captures/still.bin", "rb").read()
px = still[11:]
for endian in ("little", "big"):
    img = Image.new("RGB", (W, H))
    img.putdata([rgb565(int.from_bytes(px[i:i + 2], endian)) for i in range(0, W * H * 2, 2)])
    img.save(f"captures/still_{endian}.png")

gif = open("captures/gif.bin", "rb").read()
n = gif[13]
frames = []
for i in range(n):
    off = int.from_bytes(gif[i * 20:i * 20 + 4], "little")
    hdr = gif[off:off + 16]
    pal_raw = gif[off + 16:off + 16 + 512]
    idx = gif[off + 528:off + 528 + W * H]
    for endian in ("little",) if i else ("little", "big"):
        pal = [rgb565(int.from_bytes(pal_raw[j:j + 2], endian)) for j in range(0, 512, 2)]
        img = Image.new("RGB", (W, H))
        img.putdata([pal[k] for k in idx])
        if i == 0:
            img.save(f"captures/gif_f0_{endian}.png")
        frames.append(img) if endian == "little" else None
    if i < 3:
        print(f"frame {i} hdr {hdr.hex(' ')}  modbus(idx)={modbus(idx):04x} "
              f"modbus(pal+idx)={modbus(pal_raw + idx):04x}")
frames[0].save("captures/gif_decoded.gif", save_all=True, append_images=frames[1:], duration=80, loop=0)

body = gif[300:]
print("table crc field b2b3 -> want 0xb3b2")
for name, d in [("body", body), ("frame0", gif[300:300 + 154128]), ("table0", gif[:18])]:
    print(f"  modbus({name})={modbus(d):04x}")
print("table size field 0x2346f0 =", 0x2346F0, "; written bytes =", len(gif), "; diff", 0x2346F0 - len(gif))
