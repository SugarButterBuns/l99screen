"""Brute-force the 16-bit trailer checksum of the L99 screen protocol.

Uses the XOR-difference trick: for two equal-length messages, CRC(a)^CRC(b) equals the
zero-init, zero-xorout CRC of a^b, so poly/reflection can be found independently of init.
"""
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "captures/dev19.txt"
outs = []
for line in open(path):
    p = line.split()
    if len(p) >= 4 and not int(p[2], 16) & 0x80:
        outs.append(bytes.fromhex(p[3]))

cmds = [d for d in outs if len(d) == 16]          # the 0x66 checksum-query packets
a, b, c = cmds[0], cmds[1], cmds[2]

def rev8(x):
    return int(f"{x:08b}"[::-1], 2)

def rev16(x):
    return int(f"{x:016b}"[::-1], 2)

def crc(data, poly, init, ref):
    r = init
    for byte in data:
        if ref:
            byte = rev8(byte)
        r ^= byte << 8
        for _ in range(8):
            r = ((r << 1) ^ poly) & 0xFFFF if r & 0x8000 else (r << 1) & 0xFFFF
    return rev16(r) if ref else r

hits = []
for start in (0, 2, 5):
    da = a[start:-2]
    diff = bytes(x ^ y for x, y in zip(a[start:-2], b[start:-2]))
    for endian in ("big", "little"):
        want = int.from_bytes(a[-2:], endian) ^ int.from_bytes(b[-2:], endian)
        for ref in (False, True):
            for poly in range(1, 0x10000):
                if crc(diff, poly, 0, ref) != want:
                    continue
                # poly fits; find init with xorout=0 then derive, verify on a third packet
                base = crc(da, poly, 0, ref)
                for init in range(0x10000):
                    if crc(da, poly, init, ref) == int.from_bytes(a[-2:], endian):
                        if crc(c[start:-2], poly, init, ref) == int.from_bytes(c[-2:], endian):
                            hits.append((start, endian, ref, hex(poly), hex(init)))
                            break
                print("poly candidate", start, endian, ref, hex(poly), "->", hits[-1:] , flush=True)
print("HITS:", hits)
