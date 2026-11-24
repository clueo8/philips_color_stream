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

# DoubleColor Effect Modes mapping: name -> mode_id
DOUBLE_COLOR_EFFECTS: dict[str, int] = {
    "Combination": 0x0C,
    "Steady White": 0x01,
    "Steady Multi": 0x02,
    "Fade White": 0x03,
    "Fade Multi": 0x04,
    "Flash White": 0x05,
    "Flash Multi": 0x06,
    "Fade Between White and Multi": 0x07,
    "Flash Between White and Multi": 0x08,
}


class TelinkMeshProtocol:
    """Handles Telink pairing crypto, session key derivation, and packet encryption."""

    def __init__(self, mac_address: str, mesh_name: bytes = DEFAULT_MESH_NAME, password: bytes = DEFAULT_PASSWORD):
        self.set_mac(mac_address)
        self.mesh_name = mesh_name
        self.password = password
        self.creds = bytes(a ^ b for a, b in zip(
            self.mesh_name.ljust(16, b"\x00"),
            self.password.ljust(16, b"\x00")
        ))
        self.session_key: bytes | None = None
        self._refresh_seq()

    def set_mac(self, mac_address: str) -> None:
        """Update MAC and reversed byte representation."""
        self.mac = mac_address
        mac_clean = "".join(c for c in mac_address if c in "0123456789abcdefABCDEF")
        self.mac_rev = bytes(reversed(bytes.fromhex(mac_clean)))

    @property
    def unicast_mesh_address(self) -> int:
        """Derive node's unicast mesh address from MAC LSB: 0x0100 | MAC_LSB."""
        return 0x0100 | self.mac_rev[0]

    def _refresh_seq(self) -> None:
        """Start sequence number at a high random 24-bit value to avoid replay filter drops."""
        self._seq = (int.from_bytes(os.urandom(3), "little") & 0x7FFFFF) + 1000

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
        self._refresh_seq()
        return self.session_key

    def build_command_packet(
        self,
        wlt_payload: bytes,
        dest: int | None = None,
        seq: bytes | None = None,
    ) -> bytes:
        """Wrap a WLT command payload into a 20-byte encrypted Telink mesh packet.
        
        Defaults to unicast addressing (0x0100 | MAC_LSB) to avoid commanding other strands
        in the mesh. Pass dest=0xFFFF for broadcast.
        """
        if self.session_key is None:
            raise RuntimeError("Must complete login handshake before building commands")
        if seq is None:
            self._seq = (self._seq + 1) & 0xFFFFFF
            if self._seq == 0:
                self._seq = 1000
            seq = self._seq.to_bytes(3, "little")

        if dest is None:
            dest = BROADCAST_DEST

        nonce = bytes(self.mac_rev[0:4]) + b"\x01" + seq
        dest_bytes = dest.to_bytes(2, "little")
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
    def cmd_mode(mode_id: int) -> bytes:
        """574C5402 <mode_id> 00."""
        return b"WLT\x02" + bytes([mode_id, 0x00])

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
