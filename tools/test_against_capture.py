"""Check l99screen reproduces the official software's USB traffic byte-for-byte.

Run from the project folder:  python tools/test_against_capture.py
Needs captures/dev19.txt, captures/still_little.png, captures/gif.bin (made by the other tools).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

from l99screen import encode, protocol  # noqa: E402

outs = []
for line in open("captures/dev19.txt"):
    p = line.split()
    if len(p) >= 4 and not int(p[2], 16) & 0x80:
        outs.append(bytes.fromhex(p[3]))

still_cap = [f for f in outs if 0x041E0000 <= int.from_bytes(f[6:10], "big") < 0x04240000]
gif_cap = [f for f in outs if int.from_bytes(f[6:10], "big") >= 0x04240000]

# 1) still image: decoded PNG -> encoder -> frames, must equal capture exactly
still_blob = encode.encode_still(Image.open("captures/still_little.png"))
mine = list(protocol.iter_upload_frames(protocol.STILL_ADDR, still_blob))
ok1 = mine == still_cap
print(f"still: {len(mine)} frames generated, {len(still_cap)} captured -> "
      f"{'IDENTICAL' if ok1 else 'DIFFERENT'}")
if not ok1:
    for i, (a, b) in enumerate(zip(mine, still_cap)):
        if a != b:
            print("  first diff at frame", i, a[:16].hex(), b[:16].hex())
            break

# 2) animation: captured palettes+indices -> container encoder -> frames
gif = open("captures/gif.bin", "rb").read()
n = gif[13]
frames, delays = [], []
for i in range(n):
    e = gif[i * 20:(i + 1) * 20]
    off = int.from_bytes(e[:4], "little")
    pal = [int.from_bytes(gif[off + 16 + 2 * j:off + 18 + 2 * j], "little") for j in range(256)]
    frames.append((pal, gif[off + 528:off + 528 + 320 * 480]))
    delays.append(int.from_bytes(e[16:18], "little"))
blob = encode.encode_frames(frames, delays)
mine = list(protocol.iter_upload_frames(protocol.GIF_ADDR, blob))
ok2 = blob == gif and mine == gif_cap
print(f"animation: container {'IDENTICAL' if blob == gif else 'DIFFERENT'}, "
      f"{len(mine)} frames vs {len(gif_cap)} captured -> {'IDENTICAL' if mine == gif_cap else 'DIFFERENT'}")

# 3) reply parser on captured device replies
ins = []
for line in open("captures/dev19.txt"):
    p = line.split()
    if len(p) >= 4 and int(p[2], 16) & 0x80:
        ins.append(bytes.fromhex(p[3]))
buf = bytearray(b"".join(ins))
replies = protocol.parse_replies(buf)
oks = sum(1 for r in replies if r.cmd == 0x64 and r.body[4:6] == b"OK")
print(f"replies parsed: {len(replies)}, write OKs: {oks} (expected {sum(1 for f in outs if f[5] == 0x64)})")

# 4) end-to-end GIF path runs (quantizer etc.) on the decoded preview
fr, dl = encode.load_animation("captures/gif_decoded.gif")
b = encode.encode_animation(fr, dl)
print(f"encode GIF from file: {len(fr)} frames, {len(b)} bytes (official upload was {len(gif)})")

sys.exit(0 if ok1 and ok2 else 1)
