"""Telink Legacy BLE Mesh protocol implementation for DoubleColor / ColorStream+."""
from __future__ import annotations

import os
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

UUID_NOTIFY  = "00010203-0405-0607-0809-0a0b0c0d1911"
UUID_COMMAND = "00010203-0405-0607-0809-0a0b0c0d1912"
UUID_PAIR    = "00010203-0405-0607-0809-0a0b0c0d1914"

VENDOR = b"\x11\x02"       # 0x0211 little-endian (Telink)
BROADCAST_DEST = 0xFFFF

DEFAULT_MESH_NAME = b"DoubleColor"
DEFAULT_PASSWORD  = b"123"

# DoubleColor Effect Modes mapping: name -> (mode_id, is_steady)
DOUBLE_COLOR_EFFECTS: dict[str, tuple[int, bool]] = {
    "Combo": (0x01, False),
    "Steady White": (0x02, True),
    "Fade White": (0x02, False),
    "Steady Multi": (0x03, True),
    "Fade Multi": (0x03, False),
    "Fade Between": (0x04, False),
    "Twinkle / Flash": (0x05, False),
    "In Waves": (0x06, False),
    "Slow Fade": (0x07, False),
    "Gradient": (0x08, False),
}


class TelinkMeshProtocol:
    """Handles Telink pairing crypto, session key derivation, and packet encryption."""

    def __init__(self, mac_address: str, mesh_name: bytes = DEFAULT_MESH_NAME, password: bytes = DEFAULT_PASSWORD):
        self.mac = mac_address
        mac_clean = "".join(c for c in mac_address if c in "0123456789abcdefABCDEF")
        self.mac_rev = bytes(reversed(bytes.fromhex(mac_clean)))
        self.mesh_name = mesh_name
        self.password = password
        self.creds = bytes(a ^ b for a, b in zip(
            self.mesh_name.ljust(16, b"\x00"),
            self.password.ljust(16, b"\x00")
        ))
        self.session_key: bytes | None = None
        self._seq = 1

    @staticmethod
    def enc_noout(key: bytes, value: bytes) -> bytes:
        """Pairing convention: reverse key+data, AES-128-ECB, no output reversal."""
        k = bytes(reversed(key))
        v = bytes(reversed(value.ljust(16, b"\x00")))
        cipher = Cipher(algorithms.AES(k), modes.ECB())
        enc = cipher.encryptor()
        return enc.update(v) + enc.finalize()

    @staticmethod
    def enc_revout(key: bytes, value: bytes) -> bytes:
        """Command convention: reverse key+data AND output."""
        k = bytes(reversed(key))
        v = bytes(reversed(value.ljust(16, b"\x00")))
        cipher = Cipher(algorithms.AES(k), modes.ECB())
        enc = cipher.encryptor()
        out = enc.update(v) + enc.finalize()
        return bytes(reversed(out))

    @classmethod
    def _checksum(cls, key: bytes, nonce: bytes, payload: bytes) -> bytes:
        base = bytearray(nonce + bytes([len(payload)])).ljust(16, b"\x00")
        check = cls.enc_revout(key, bytes(base))
        for i in range(0, len(payload), 16):
            chunk = bytearray(payload[i:i + 16].ljust(16, b"\x00"))
            check = bytearray(a ^ b for a, b in zip(check, chunk))
            check = cls.enc_revout(key, bytes(check))
        return check

    @classmethod
    def _crypt_payload(cls, key: bytes, nonce: bytes, payload: bytes) -> bytes:
        base = bytearray(b"\x00" + nonce).ljust(16, b"\x00")
        result = bytearray()
        for i in range(0, len(payload), 16):
            enc_base = cls.enc_revout(key, bytes(base))
            result += bytearray(a ^ b for a, b in zip(enc_base, bytearray(payload[i:i + 16])))
            base[0] = (base[0] + 1) & 0xFF
        return result

    def build_login_packet(self, randm: bytes | None = None) -> tuple[bytes, bytes]:
        """Create the 17-byte 0x0C login handshake packet for characteristic 0x1914."""
        if randm is None:
            randm = os.urandom(8)
        encd = self.enc_noout(randm + b"\x00" * 8, self.creds)
        sig = encd[8:16][::-1]
        packet = bytes([0x0C]) + randm + sig
        return randm, packet

    def derive_session_key(self, randm: bytes, rands: bytes) -> bytes:
        """Derive the 16-byte session key from client and device randoms."""
        self.session_key = self.enc_noout(self.creds, randm + rands)[::-1]
        return self.session_key

    def build_command_packet(self, wlt_payload: bytes, seq: bytes | None = None) -> bytes:
        """Wrap a WLT command payload into a 20-byte encrypted Telink mesh packet."""
        if self.session_key is None:
            raise RuntimeError("Must complete login handshake before building commands")
        if seq is None:
            self._seq = (self._seq + 1) & 0xFFFFFF
            seq = self._seq.to_bytes(3, "little")

        nonce = bytes(self.mac_rev[0:4]) + b"\x01" + seq
        dest_bytes = BROADCAST_DEST.to_bytes(2, "little")
        opcode = 0xF0
        inner_payload = (dest_bytes + bytes([opcode]) + VENDOR + wlt_payload).ljust(15, b"\x00")

        mic = self._checksum(self.session_key, nonce, inner_payload)
        encrypted = self._crypt_payload(self.session_key, nonce, inner_payload)
        return seq + mic[0:2] + encrypted

    # WLT Command Builders
    @staticmethod
    def cmd_power(on: bool) -> bytes:
        """574C54021101 (ON) or 574C54021102 (OFF)."""
        return b"WLT\x02\x11" + (b"\x01" if on else b"\x02")

    @staticmethod
    def cmd_mode(mode_id: int, steady: bool = False) -> bytes:
        """574C5402 <mode> <modifier>."""
        modifier = 0xE0 if steady else 0x00
        return b"WLT\x02" + bytes([mode_id, modifier])

    @staticmethod
    def cmd_brightness(percent: int) -> bytes:
        """574C540209 <percent_hex> 00 (0..100%)."""
        pct = max(0, min(100, percent))
        return b"WLT\x02\x09" + bytes([pct, 0x00])

    @staticmethod
    def cmd_speed(speed: int) -> bytes:
        """574C54030C01 <speed> (1..4)."""
        spd = max(1, min(4, speed))
        return b"WLT\x03\x0c\x01" + bytes([spd])
