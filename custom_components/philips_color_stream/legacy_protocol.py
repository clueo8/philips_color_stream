"""Legacy unencrypted Willis Link Technology protocol (for GV_RGB_* controllers)."""
from __future__ import annotations

from datetime import datetime

SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
NOTIFY_CHAR_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"
WRITE_CHAR_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"

STEADY = 0xE0
ANIMATED = 0x00

LEGACY_EFFECTS: dict[str, tuple[int, int]] = {
    "Red": (0x02, STEADY),
    "Green": (0x03, STEADY),
    "Blue": (0x04, STEADY),
    "Warm white": (0x05, STEADY),
    "Cyan": (0x06, STEADY),
    "Purple": (0x07, STEADY),
    "White": (0x08, STEADY),
    "Multicolor steady": (0x14, ANIMATED),
    "Red blink": (0x02, ANIMATED),
    "Green blink": (0x03, ANIMATED),
    "Blue blink": (0x04, ANIMATED),
    "Yellow blink": (0x05, ANIMATED),
    "Cyan blink": (0x06, ANIMATED),
    "Purple blink": (0x07, ANIMATED),
    "White blink": (0x08, ANIMATED),
    "Red-green blink": (0x09, ANIMATED),
    "Red-blue blink": (0x0A, ANIMATED),
    "Green-blue blink": (0x0B, ANIMATED),
    "Red-yellow blink": (0x0C, ANIMATED),
    "Cyan-purple blink": (0x0D, ANIMATED),
    "Cyan-white blink": (0x0E, ANIMATED),
    "Purple-white blink": (0x0F, ANIMATED),
    "Color change slow": (0x10, ANIMATED),
    "Color change medium": (0x11, ANIMATED),
    "Color change fast": (0x12, ANIMATED),
    "Color fade": (0x13, ANIMATED),
}


def _packet(target: bytes, body: bytes) -> bytes:
    return (target + b"\x00" * 10 + b"WLT" + body).ljust(23, b"\x00")


def cmd_probe() -> bytes:
    return _packet(b"\xe1\xff\xff", b"")


def cmd_probe_done() -> bytes:
    return _packet(b"\xe2\xff\xff", b"")


def cmd_time_sync(now: datetime) -> bytes:
    return _packet(
        b"\xff\xff\xff",
        bytes([
            0x07, 0x00,
            now.year % 100, now.month, now.day,
            now.hour, now.minute, now.second,
            now.isoweekday() % 7,
        ]),
    )


def cmd_power(device_id: bytes, on: bool) -> bytes:
    return _packet(b"\xff" + device_id, bytes([0x02, 0x11, 0x01 if on else 0x02]))


def cmd_effect(device_id: bytes, mode_num: int, modifier: int) -> bytes:
    return _packet(b"\xff" + device_id, bytes([0x02, mode_num, modifier]))


def cmd_speed(device_id: bytes, speed_value: int) -> bytes:
    spd = max(1, min(100, speed_value))
    return _packet(b"\xff" + device_id, bytes([0x03, 0x0C, 0x01, spd]))
