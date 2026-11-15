"""One-time Linux permission setup, done by the app itself.

Linux only lets root (and group uucp/dialout) open /dev/ttyACM*. Instead of asking the user to
install a udev rule by hand, the app asks for their password once (pkexec, a graphical prompt,
or sudo in a terminal), installs the rule, and re-applies it to the connected keyboard so it
works straight away without replugging.
"""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
import time

RULE_PATH = "/etc/udev/rules.d/70-aula-l99-screen.rules"
OLD_RULE_PATH = "/etc/udev/rules.d/99-aula-l99-screen.rules"

RULE = """\
# AULA L99 keyboard screen (USB CDC serial, EEEF:268A): user access, no ModemManager probing
# Installed by l99screen. Must sort below 73 (systemd applies "uaccess" in 73-seat-late.rules).
SUBSYSTEM=="tty", ATTRS{idVendor}=="eeef", ATTRS{idProduct}=="268a", MODE="0660", TAG+="uaccess", ENV{ID_MM_DEVICE_IGNORE}="1", SYMLINK+="aula-l99-screen"
SUBSYSTEM=="usb", ATTRS{idVendor}=="eeef", ATTRS{idProduct}=="268a", ENV{ID_MM_DEVICE_IGNORE}="1"
"""


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def has_access(port: str) -> bool:
    return os.access(port, os.R_OK | os.W_OK)


def _root_script() -> str:
    b64 = base64.b64encode(RULE.encode()).decode()
    return (
        f"set -e; rm -f {OLD_RULE_PATH}; "
        f"echo {b64} | base64 -d > {RULE_PATH}; chmod 644 {RULE_PATH}; "
        "udevadm control --reload; "
        "udevadm trigger --action=change --subsystem-match=tty; "
        "udevadm trigger --action=change --subsystem-match=usb --attr-match=idVendor=eeef; "
        "udevadm settle --timeout=5 || true")


def install_rule(interactive_terminal: bool = False) -> tuple[bool, str]:
    """Install the udev rule as root. Returns (ok, message).

    Uses pkexec (graphical password prompt) when available; falls back to sudo when running
    in a terminal.
    """
    if not is_linux():
        return True, "not needed on this system"
    script = _root_script()
    if shutil.which("pkexec") and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        cmd = ["pkexec", "/bin/sh", "-c", script]
    elif interactive_terminal and shutil.which("sudo"):
        cmd = ["sudo", "/bin/sh", "-c", script]
    else:
        return False, ("Couldn't ask for your password (no pkexec/sudo available). Run:\n"
                       "  l99screen udev-rule | sudo tee " + RULE_PATH + "\n"
                       "  sudo udevadm control --reload && sudo udevadm trigger")
    # The AppImage runtime sets LD_LIBRARY_PATH etc. for its own Python; don't leak that
    # into system tools.
    env = {k: v for k, v in os.environ.items()
           if k not in ("LD_LIBRARY_PATH", "PYTHONHOME", "PYTHONPATH", "TCL_LIBRARY", "TK_LIBRARY")}
    try:
        r = subprocess.run(cmd, env=env, capture_output=not interactive_terminal, text=True)
    except OSError as e:
        return False, f"couldn't run {cmd[0]}: {e}"
    if cmd[0] == "pkexec" and r.returncode in (126, 127):  # dialog dismissed / not authorized
        return False, "Permission setup was cancelled."
    if r.returncode != 0:
        err = (r.stderr or "").strip() if not interactive_terminal else ""
        return False, f"Permission setup failed (exit {r.returncode}). {err}"
    return True, "Permission set up. You won't be asked again."


def wait_for_access(port: str, seconds: float = 5.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if has_access(port):
            return True
        time.sleep(0.2)
    return has_access(port)
