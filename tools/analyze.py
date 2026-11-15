"""Summarise the L99 screen-device traffic exported from tshark (captures/dev19.txt)."""
import sys
from collections import Counter

path = sys.argv[1] if len(sys.argv) > 1 else "captures/dev19.txt"
pkts = []
for line in open(path):
    parts = line.split()
    if len(parts) < 4:
        continue
    num, t, ep, data = parts[0], float(parts[1]), int(parts[2], 16), bytes.fromhex(parts[3])
    pkts.append((int(num), t, ep, data))

print(f"{len(pkts)} packets")
print("endpoint/len histogram:", Counter((hex(ep), len(d)) for _, _, ep, d in pkts).most_common(12))

# Group OUT packets by header (first 8 bytes) and show offset ranges per run.
print("\n--- runs of OUT packets ---")
prev_hdr, run = None, []
def flush():
    if not run:
        return
    n0, t0, d0 = run[0]
    n1, t1, d1 = run[-1]
    offs = [int.from_bytes(d[8:10], "little") for _, _, d in run]
    print(f"frames {n0}-{n1} t={t0:.3f}-{t1:.3f} hdr={prev_hdr.hex()} n={len(run)} "
          f"len={len(d0)} off {offs[0]:#x}..{offs[-1]:#x}")
    print(f"   first: {d0[:40].hex()}  tail: {d0[-6:].hex()}")
    print(f"   last : {d1[:24].hex()}  tail: {d1[-6:].hex()}")
for n, t, ep, d in pkts:
    if ep & 0x80:
        continue
    hdr = d[:8]
    if hdr != prev_hdr:
        flush()
        prev_hdr, run = hdr, []
    run.append((n, t, d))
flush()

print("\n--- distinct IN responses (by first 8 bytes) ---")
seen = Counter()
examples = {}
for n, t, ep, d in pkts:
    if ep & 0x80:
        k = d[:8].hex()
        seen[k] += 1
        examples.setdefault(k, (n, d.hex()))
for k, c in seen.most_common():
    print(c, examples[k])

print("\n--- all non-2060 OUT packets ---")
for n, t, ep, d in pkts:
    if not ep & 0x80 and len(d) != 2060:
        print(n, f"{t:.3f}", hex(ep), len(d), d[:64].hex())
