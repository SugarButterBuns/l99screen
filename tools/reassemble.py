"""Rebuild the flash writes from captures/dev19.txt and probe the packet checksum."""
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "captures/dev19.txt"
outs, ins = [], []
for line in open(path):
    p = line.split()
    if len(p) < 4:
        continue
    ep, d = int(p[2], 16), bytes.fromhex(p[3])
    (ins if ep & 0x80 else outs).append(d)

# ---- reassemble 0x64 writes into address-keyed memory -------------------
mem = {}
for d in outs:
    if d[5] == 0x64:
        addr = int.from_bytes(d[6:10], "big")
        payload = d[10:-2]
        for i, b in enumerate(payload):
            mem[addr + i] = b

def region(start, length):
    return bytes(mem.get(start + i, 0) for i in range(length))

still = region(0x041E0000, 307211)
gif = region(0x04240000, 0x00220000 + 0x0001481C)
open("captures/still.bin", "wb").write(still)
open("captures/gif.bin", "wb").write(gif)
print("still header:", still[:16].hex())
print("gif header (first 96 bytes):")
for i in range(0, 96, 16):
    print(f"  {i:04x}: {gif[i:i+16].hex(' ')}")

# ---- checksum probing ------------------------------------------------------
def crc16(data, poly, init, refin, refout, xorout):
    crc = init
    for b in data:
        if refin:
            b = int(f"{b:08b}"[::-1], 2)
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    if refout:
        crc = int(f"{crc:016b}"[::-1], 2)
    return crc ^ xorout

samples = [d for d in outs if len(d) in (16, 23, 40)][:4] + outs[:2] + ins[:2]
found = []
for poly in (0x1021, 0x8005, 0x3D65, 0x0589, 0x8BB7, 0xA097, 0xC867):
    for init in (0x0000, 0xFFFF, 0x1D0F):
        for ref in (False, True):
            for xorout in (0x0000, 0xFFFF):
                for start in (0, 2, 3, 5):
                    for endian in ("big", "little"):
                        ok = True
                        for s in samples:
                            # IN frames may hold two messages; check only the first one.
                            if s[2] in (0x04,) and len(s) > 7:
                                s = s[:7]
                            want = int.from_bytes(s[-2:], endian)
                            if crc16(s[start:-2], poly, init, ref, ref, xorout) != want:
                                ok = False
                                break
                        if ok:
                            found.append((hex(poly), hex(init), ref, hex(xorout), start, endian))
print("crc16 matches:", found)
