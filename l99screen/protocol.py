"""Wire protocol for the AULA L99 screen.

The screen is a separate USB CDC-ACM serial device inside the keyboard (VID 0xEEEF,
PID 0x268A), opened at 115200 8N1. On Linux it appears as /dev/ttyACM*.

Host -> device frame:
    5A A5 | LEN (3 bytes, big-endian, = bytes after this field) | CMD | ADDR (4, BE)
          | PAYLOAD | CRC16/MODBUS(CMD..PAYLOAD), little-endian

Device -> host frame (one USB read can hold several):
    5A A5 | LEN (1 byte) | CMD ... | CRC16/MODBUS over the bytes after LEN, little-endian

Commands seen in captures of AULA's Windows software:
    0x64  write up to 2048 bytes of flash at ADDR. Reply: echo ADDR + "OK".
    0x66  query checksum of LEN (4-byte BE payload) bytes at ADDR; sent after every
          128 KiB (or the final partial chunk) of writes. Reply: ADDR + 4-byte value.
"""
from __future__ import annotations

import errno
import time
from dataclasses import dataclass
from typing import Callable, Iterator, Optional

VID, PID = 0xEEEF, 0x268A
BAUD = 115200

CMD_WRITE = 0x64
CMD_CHECK = 0x66

CHUNK = 2048            # payload bytes per write packet
GROUP = 0x20000         # writes are verified in 128 KiB groups

# Flash locations used by the official software (from USB captures).
STILL_ADDR = 0x041E0000
GIF_ADDR = 0x04240000


def crc16_modbus(data: bytes, crc: int = 0xFFFF) -> int:
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def build_frame(cmd: int, addr: int, payload: bytes = b"") -> bytes:
    body = bytes([cmd]) + addr.to_bytes(4, "big") + payload
    return (b"\x5a\xa5" + (len(body) + 2).to_bytes(3, "big") + body
            + crc16_modbus(body).to_bytes(2, "little"))


def iter_upload_frames(base: int, data: bytes) -> Iterator[bytes]:
    """Yield the exact frame sequence the official software sends for one upload."""
    for g in range(0, len(data), GROUP):
        group = data[g:g + GROUP]
        for off in range(0, len(group), CHUNK):
            yield build_frame(CMD_WRITE, base + g + off, group[off:off + CHUNK])
        yield build_frame(CMD_CHECK, base + g, len(group).to_bytes(4, "big"))


@dataclass
class Reply:
    cmd: int
    body: bytes  # bytes after CMD, without CRC


def parse_replies(buf: bytearray) -> list[Reply]:
    """Pull complete reply frames off the front of buf (mutates buf)."""
    out = []
    while True:
        start = buf.find(b"\x5a\xa5")
        if start < 0:
            buf.clear()
            return out
        del buf[:start]
        if len(buf) < 3 or len(buf) < 3 + buf[2]:
            return out
        n = buf[2]
        msg = bytes(buf[3:3 + n])
        del buf[:3 + n]
        if n < 3 or crc16_modbus(msg[:-2]) != int.from_bytes(msg[-2:], "little"):
            continue  # corrupt; resync
        out.append(Reply(msg[0], msg[1:-2]))


class ProtocolError(RuntimeError):
    pass


class PortPermissionError(PermissionError):
    """The screen's serial port exists but this user may not open it (Linux)."""

    def __init__(self, port: str):
        super().__init__(f"No permission to open {port}. Run 'l99screen setup' once "
                         "(asks for your password) to allow access.")
        self.port = port


def find_port() -> Optional[str]:
    from serial.tools import list_ports
    for p in list_ports.comports():
        if p.vid == VID and p.pid == PID:
            return p.device
    return None


class Screen:
    def __init__(self, port: Optional[str] = None, timeout: float = 2.0):
        import serial
        port = port or find_port()
        if not port:
            raise ProtocolError(
                "AULA L99 screen not found (USB EEEF:268A). Is the keyboard connected "
                "by USB cable (not the 2.4 GHz dongle or Bluetooth)?")
        self.port = port
        self.timeout = timeout
        try:
            self.ser = serial.Serial(port, BAUD, timeout=0.05, write_timeout=timeout)
        except serial.SerialException as e:
            if getattr(e, "errno", None) == errno.EACCES or "Permission denied" in str(e):
                raise PortPermissionError(port) from e
            raise
        self.ser.dtr = True
        self.ser.rts = True
        self._buf = bytearray()
        time.sleep(0.05)
        self.ser.reset_input_buffer()

    def close(self):
        try:
            self.ser.dtr = False
            self.ser.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _wait(self, cmd: int, addr: int) -> Reply:
        deadline = time.monotonic() + self.timeout
        want = addr.to_bytes(4, "big")
        while time.monotonic() < deadline:
            # read(1) returns as soon as a byte arrives; then drain whatever else is queued
            self._buf += self.ser.read(max(1, self.ser.in_waiting))
            for r in parse_replies(self._buf):
                if r.cmd == cmd and r.body[:4] == want:
                    return r
        raise ProtocolError(f"no reply to command {cmd:#04x} at {addr:#010x}")

    def send(self, frame: bytes) -> Reply:
        cmd, addr = frame[5], int.from_bytes(frame[6:10], "big")
        self.ser.write(frame)
        r = self._wait(cmd, addr)
        if cmd == CMD_WRITE and r.body[4:6] != b"OK":
            raise ProtocolError(f"write at {addr:#010x} rejected: {r.body.hex()}")
        return r

    def upload(self, base: int, data: bytes,
               progress: Optional[Callable[[int, int], None]] = None) -> None:
        frames = list(iter_upload_frames(base, data))
        for i, f in enumerate(frames, 1):
            self.send(f)
            if progress:
                progress(i, len(frames))
