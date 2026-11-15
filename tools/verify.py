"""Check the decoded framing against every captured packet and probe the inner checksums."""
import binascii
import zlib

def modbus(data, init=0xFFFF):
    crc = init
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc

outs, ins = [], []
for line in open("captures/dev19.txt"):
    p = line.split()
    if len(p) >= 4:
        (ins if int(p[2], 16) & 0x80 else outs).append(bytes.fromhex(p[3]))

bad = [d[:12].hex() for d in outs if modbus(d[5:-2]) != int.from_bytes(d[-2:], "little")]
print(f"OUT packets: {len(outs)}, CRC mismatches: {len(bad)}", bad[:3])
lenbad = [d[:8].hex() for d in outs if int.from_bytes(d[2:5], "big") != len(d) - 5]
print("OUT length-field mismatches:", len(lenbad))

# IN frames can carry several messages: 5a a5 LEN <LEN bytes>, last 2 = crc
def split_in(d):
    msgs, i = [], 0
    while i + 3 <= len(d) and d[i:i + 2] == b"\x5a\xa5":
        n = d[i + 2]
        msgs.append(d[i:i + 3 + n])
        i += 3 + n
    return msgs
inbad, inmsgs = 0, 0
for d in ins:
    for m in split_in(d):
        inmsgs += 1
        if modbus(m[3:-2]) != int.from_bytes(m[-2:], "little"):
            inbad += 1
print(f"IN messages: {inmsgs}, CRC mismatches (crc over bytes after length): {inbad}")
print("example 0x66 reply:", [m.hex() for m in split_in([d for d in ins if d[3] == 0x66][0])])

# ---- inner checksums -----------------------------------------------------
still = open("captures/still.bin", "rb").read()
gif = open("captures/gif.bin", "rb").read()
print("\nstill header bytes 8..10:", still[8:11].hex())
for name, rng in [("pixels", still[11:]), ("all-but-hdr8", still[:8] + still[11:])]:
    print(f"  modbus({name}) = {modbus(rng):04x}  sum16={sum(rng) & 0xFFFF:04x}")

# region checksum reported by 0x66 replies: compare with crc32/sum over the written block
mem = {}
for d in outs:
    if d[5] == 0x64:
        mem[int.from_bytes(d[6:10], "big")] = d[10:-2]
def region(addr, n):
    buf = bytearray()
    a = addr
    while len(buf) < n:
        chunk = mem[a]
        buf += chunk
        a += len(chunk)
    return bytes(buf[:n])
q = [d for d in outs if d[5] == 0x66][0]
qaddr, qlen = int.from_bytes(q[6:10], "big"), int.from_bytes(q[10:14], "big")
blk = region(qaddr, qlen)
rep = [m for d in ins for m in split_in(d) if len(m) > 9 and m[3] == 0x66][0]
print(f"\n0x66 query addr={qaddr:#x} len={qlen:#x}; reply value={rep[8:12].hex()}")
print(f"  crc32={zlib.crc32(blk):08x} sum32={sum(blk) & 0xFFFFFFFF:08x} "
      f"modbus={modbus(blk):04x} crc32_mpeg?={binascii.crc_hqx(blk, 0xFFFF):04x}")

# GIF frame table
print("\nGIF frame table:")
for i in range(15):
    e = gif[i * 20:(i + 1) * 20]
    print(i, e.hex(" "))
f0 = int.from_bytes(gif[0:4], "little")
f1 = int.from_bytes(gif[20:24], "little")
print("frame0 offset", f0, "frame stride", f1 - f0)
fr = gif[f0:f1]
print("frame0 first 48:", fr[:48].hex(" "))
print("frame0 at 512..560:", fr[512:560].hex(" "))
print("frame0 last 48:", fr[-48:].hex(" "))
