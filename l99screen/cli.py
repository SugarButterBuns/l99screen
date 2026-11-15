"""l99screen: set the picture or animation on the AULA L99 keyboard screen."""
from __future__ import annotations

import argparse
import sys
import time

from PIL import Image

from . import encode, linux_access, protocol

MAX_SAFE_FRAMES = encode.MAX_FRAMES
UDEV_RULE = linux_access.RULE


def _open_screen(port):
    """Open the screen; on Linux, offer the one-time permission setup if access is denied."""
    try:
        return protocol.Screen(port)
    except protocol.PortPermissionError as e:
        if not (linux_access.is_linux() and sys.stdin.isatty()):
            raise
        answer = input(f"{e.port} needs a one-time permission setup (asks for your password). "
                       "Do it now? [Y/n] ").strip().lower()
        if answer not in ("", "y", "yes"):
            raise
        ok, msg = linux_access.install_rule(interactive_terminal=True)
        print(msg)
        if not ok or not linux_access.wait_for_access(e.port):
            raise
        return protocol.Screen(port)


def cmd_setup(args) -> int:
    if not linux_access.is_linux():
        print("Nothing to set up on this system.")
        return 0
    ok, msg = linux_access.install_rule(interactive_terminal=sys.stdin.isatty())
    print(msg, file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


def _progress(label: str):
    start = time.monotonic()

    def cb(i, n):
        pct = i * 100 // n
        bar = "#" * (pct // 4)
        sys.stderr.write(f"\r{label} [{bar:<25}] {pct:3d}%  {time.monotonic() - start:4.1f}s")
        if i == n:
            sys.stderr.write("\n")
        sys.stderr.flush()
    return cb


def _deliver(args, base: int, blob: bytes, label: str) -> int:
    if args.dump:
        with open(args.dump, "wb") as f:
            for frame in protocol.iter_upload_frames(base, blob):
                f.write(frame)
        print(f"wrote {len(blob)} bytes of {label} as raw frames to {args.dump} (nothing sent)")
        return 0
    with _open_screen(args.port) as scr:
        print(f"using {scr.port}")
        scr.upload(base, blob, _progress(f"uploading {label}"))
    print("done")
    return 0


def cmd_image(args) -> int:
    img = encode.fit(Image.open(args.file), args.fit, args.rotate)
    if args.preview:
        img.save(args.preview)
        print(f"preview saved to {args.preview}")
    return _deliver(args, protocol.STILL_ADDR, encode.encode_still(img), "image")


def cmd_gif(args) -> int:
    if args.max_frames > MAX_SAFE_FRAMES and not args.i_know_the_risk:
        print(f"--max-frames above {MAX_SAFE_FRAMES} has not been tested and could overwrite "
              "other data in the keyboard's flash. Add --i-know-the-risk to allow it.",
              file=sys.stderr)
        return 2
    frames, delays = encode.load_animation(args.file, args.fit, args.rotate,
                                           args.max_frames, args.delay)
    print(f"{len(frames)} frames, delays {delays} ms")
    if args.preview:
        frames[0].save(args.preview, save_all=True, append_images=frames[1:],
                       duration=delays, loop=0)
        print(f"preview saved to {args.preview}")
    return _deliver(args, protocol.GIF_ADDR, encode.encode_animation(frames, delays), "animation")


def cmd_detect(args) -> int:
    port = protocol.find_port()
    if port:
        print(f"AULA L99 screen found at {port}")
        return 0
    print("not found: connect the keyboard with a USB cable", file=sys.stderr)
    return 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="l99screen", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("file")
        sp.add_argument("--fit", choices=encode.FIT_MODES, default="cover",
                        help="cover = fill and crop (default), contain = letterbox, stretch")
        sp.add_argument("--rotate", type=int, default=0, choices=(0, 90, 180, 270),
                        help="rotate clockwise before fitting (landscape images: try 90)")
        sp.add_argument("--port", help="serial port (default: auto-detect EEEF:268A)")
        sp.add_argument("--preview", metavar="OUT", help="also save what will be shown")
        sp.add_argument("--dump", metavar="OUT", help="write the USB frames to a file "
                        "instead of sending them (for testing)")

    sp = sub.add_parser("image", help="set a still picture (JPG/PNG/...)")
    common(sp)
    sp.set_defaults(func=cmd_image)

    sp = sub.add_parser("gif", help="set an animation (GIF/APNG/WebP)")
    common(sp)
    sp.add_argument("--max-frames", type=int, default=MAX_SAFE_FRAMES,
                    help=f"frames kept, sampled evenly (default and tested max: {MAX_SAFE_FRAMES})")
    sp.add_argument("--delay", type=int, help="force ms per frame instead of the GIF's timing")
    sp.add_argument("--i-know-the-risk", action="store_true", help=argparse.SUPPRESS)
    sp.set_defaults(func=cmd_gif)

    sp = sub.add_parser("detect", help="check that the screen device is connected")
    sp.set_defaults(func=cmd_detect)

    sp = sub.add_parser("setup", help="Linux: allow your user to use the screen "
                        "(one-time, asks for your password)")
    sp.set_defaults(func=cmd_setup)

    sp = sub.add_parser("udev-rule", help="print the Linux udev rule (pipe to sudo tee "
                        "/etc/udev/rules.d/70-aula-l99-screen.rules)")
    sp.set_defaults(func=lambda a: print(UDEV_RULE, end="") or 0)

    sp = sub.add_parser("gui", help="open the graphical uploader")
    sp.add_argument("file", nargs="?")
    sp.set_defaults(func=lambda a: __import__("l99screen.gui", fromlist=["main"]).main(
        [a.file] if a.file else None))

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except protocol.ProtocolError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except PermissionError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
