#!/usr/bin/env python3
"""Standalone BLE control and test script for Philips DoubleColor / ColorStream+ lights.

Hardware: Telink Semiconductor BLE Mesh chip (Vendor ID 0x0211)
Protocol: Telink legacy mesh + Willis Link Technology ("WLT") payloads
Default Credentials:
  Mesh Name: "DoubleColor"
  Password:  "123"
"""
from __future__ import annotations

import argparse
import asyncio
import os
import struct
import sys
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

UUID_NOTIFY  = "00010203-0405-0607-0809-0a0b0c0d1911"
UUID_COMMAND = "00010203-0405-0607-0809-0a0b0c0d1912"
UUID_PAIR    = "00010203-0405-0607-0809-0a0b0c0d1914"

VENDOR = b"\x11\x02"       # 0x0211 little-endian (Telink)
BROADCAST_DEST = 0xFFFF    # 0xFFFF little-endian

DEFAULT_MESH_NAME = b"DoubleColor"
DEFAULT_PASSWORD  = b"123"

KNOWN_MACS = [
    "57:4c:42:01:c9:5a",
    "57:4c:42:c5:2c:a6",
    "57:4c:42:fd:47:e9",
]

MODES = {
    "steady_white":                0x01,
    "steady_multi":                0x02,
    "fade_white":                  0x03,
    "fade_multi":                  0x04,
    "flash_white":                 0x05,
    "flash_multi":                 0x06,
    "fade_between_white_and_multi": 0x07,
    "flash_between_white_and_multi": 0x08,
}


class TelinkMeshProtocol:
    """Implements the Telink legacy BLE mesh cryptographic protocol."""

    def __init__(self, mac_address: str, mesh_name: bytes = DEFAULT_MESH_NAME, password: bytes = DEFAULT_PASSWORD):
        self.set_mac(mac_address)
        self.mesh_name = mesh_name
        self.password = password
        self.creds = bytes(a ^ b for a, b in zip(
            self.mesh_name.ljust(16, b"\x00"),
            self.password.ljust(16, b"\x00")
        ))
        self.session_key: bytes | None = None
        self._seq = (int.from_bytes(os.urandom(3), "little") & 0x7FFFFF) + 1000

    def set_mac(self, mac_address: str) -> None:
        self.mac = mac_address
        mac_clean = "".join(c for c in mac_address if c in "0123456789abcdefABCDEF")
        self.mac_rev = bytes(reversed(bytes.fromhex(mac_clean)))

    @property
    def unicast_mesh_address(self) -> int:
        return 0x0100 | self.mac_rev[0]

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

    def build_login_packet(self, randm: bytes) -> bytes:
        """Create the 17-byte 0x0C login handshake packet for characteristic 0x1914."""
        if len(randm) != 8:
            raise ValueError("randm must be 8 bytes")
        encd = self.enc_noout(randm + b"\x00" * 8, self.creds)
        sig = encd[8:16][::-1]
        return bytes([0x0C]) + randm + sig

    def derive_session_key(self, randm: bytes, rands: bytes) -> bytes:
        """Derive the 16-byte session key from client and device randoms."""
        self.session_key = self.enc_noout(self.creds, randm + rands)[::-1]
        self._seq = (int.from_bytes(os.urandom(3), "little") & 0x7FFFFF) + 1000
        return self.session_key

    def build_command_packet(
        self,
        wlt_payload: bytes,
        dest: int | None = None,
        seq: bytes | None = None,
    ) -> bytes:
        """Wrap a WLT command payload into a 20-byte encrypted Telink mesh packet."""
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

    # WLT Command Generators
    @staticmethod
    def cmd_power(on: bool) -> bytes:
        return b"WLT\x02\x11" + (b"\x01" if on else b"\x02")

    @staticmethod
    def cmd_mode(mode_id: int) -> bytes:
        return b"WLT\x02" + bytes([mode_id, 0x00])

    @staticmethod
    def cmd_brightness(percent: int) -> bytes:
        pct = max(0, min(100, percent))
        return b"WLT\x02\x09" + bytes([pct, 0x00])

    @staticmethod
    def cmd_speed(speed: int) -> bytes:
        spd = max(1, min(4, speed))
        return b"WLT\x03\x0c\x01" + bytes([spd])


async def run_command_on_device(mac: str, action: str, param: int | str | None = None):
    try:
        from bleak import BleakClient
    except ImportError:
        print("Error: 'bleak' is required to connect to BLE devices.")
        print("Install via: pip install bleak")
        return

    print(f"Connecting to Philips DoubleColor light strand [{mac}]...")
    proto = TelinkMeshProtocol(mac)

    async with BleakClient(mac, timeout=15.0) as client:
        print(f"Connected! Performing Telink Mesh authentication on {UUID_PAIR}...")
        randm = os.urandom(8)
        login_pkt = proto.build_login_packet(randm)
        await client.write_gatt_char(UUID_PAIR, login_pkt, response=True)
        await asyncio.sleep(0.3)

        reply = await client.read_gatt_char(UUID_PAIR)
        if len(reply) < 9 or reply[0] == 0x0E:
            raise RuntimeError(f"Authentication failed/rejected! Device reply: {bytes(reply).hex()}")
        
        rands = bytes(reply[1:9])
        proto.derive_session_key(randm, rands)
        print(f"Authentication successful! Derived session key: {proto.session_key.hex()}")

        # Enable notifications on 1911
        try:
            await client.start_notify(UUID_NOTIFY, lambda sender, data: None)
            await client.write_gatt_char(UUID_NOTIFY, b"\x01", response=True)
            await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Note on notification enable: {e}")

        # Build requested command
        if action == "on":
            print("Sending: Power ON (3 bursts)")
            payload = proto.cmd_power(True)
        elif action == "off":
            print("Sending: Power OFF (3 bursts)")
            payload = proto.cmd_power(False)
        elif action == "brightness":
            pct = int(param) if param is not None else 100
            print(f"Sending: Brightness {pct}% (3 bursts)")
            payload = proto.cmd_brightness(pct)
        elif action == "mode":
            mode_name = str(param).lower()
            if mode_name in MODES:
                m_id = MODES[mode_name]
                print(f"Sending: Mode '{mode_name}' (ID: {m_id}) (3 bursts)")
                payload = proto.cmd_mode(m_id)
            else:
                m_id = int(param)
                print(f"Sending: Mode ID {m_id} (3 bursts)")
                payload = proto.cmd_mode(m_id)
        elif action == "speed":
            spd = int(param) if param is not None else 1
            print(f"Sending: Speed {spd} (3 bursts)")
            payload = proto.cmd_speed(spd)
        else:
            print(f"Unknown action: {action}")
            return

        for b in range(3):
            cmd_pkt = proto.build_command_packet(payload)
            await client.write_gatt_char(UUID_COMMAND, cmd_pkt, response=False)
            if b < 2:
                await asyncio.sleep(0.04)
        print("Command transmitted successfully in 3 bursts!")


def main():
    parser = argparse.ArgumentParser(description="Philips DoubleColor / ColorStream+ BLE Control")
    parser.add_argument("--mac", "-m", default=KNOWN_MACS[0], help=f"Device MAC address (default: {KNOWN_MACS[0]})")
    parser.add_argument("action", choices=["on", "off", "brightness", "mode", "speed", "test-vectors"],
                        help="Action to perform")
    parser.add_argument("param", nargs="?", default=None, help="Parameter for brightness (0-100), mode name/id, or speed (1-4)")
    args = parser.parse_args()

    if args.action == "test-vectors":
        print("Running internal cryptographic test vectors against btsnoop capture...")
        proto = TelinkMeshProtocol("57:4c:42:01:c9:5a")
        test_randm = bytes.fromhex("68dafa3eae61c6c1")
        login_pkt = proto.build_login_packet(test_randm)
        expected_login = "0c68dafa3eae61c6c1f42092851baf4672"
        assert login_pkt.hex() == expected_login, f"Login mismatch: {login_pkt.hex()} vs {expected_login}"
        print(" [PASS] 0x0C Login handshake signature matches exactly!")

        test_rands = bytes.fromhex("773fe85e7dadc3a1")
        sk = proto.derive_session_key(test_randm, test_rands)
        expected_sk = "9c7b974d6fd2a9f90b0b495c7c17ac45"
        assert sk.hex() == expected_sk, f"Session key mismatch: {sk.hex()} vs {expected_sk}"
        print(" [PASS] Session key derivation matches exactly!")

        assert proto.unicast_mesh_address == 0x015a, f"Unicast address mismatch: {hex(proto.unicast_mesh_address)}"
        print(" [PASS] Unicast mesh address (0x015a) matches advertising packet #2138!")

        test_seq = bytes.fromhex("9f9075")
        cmd_pkt = proto.build_command_packet(proto.cmd_power(True), dest=BROADCAST_DEST, seq=test_seq)
        expected_cmd = "9f907552331d89fa5a8e69d5830cbf8b49b15071"
        assert cmd_pkt.hex() == expected_cmd, f"Command packet mismatch: {cmd_pkt.hex()} vs {expected_cmd}"
        print(" [PASS] Power ON encrypted command packet matches btsnoop capture byte-for-byte!")
        print("\nAll cryptographic test vectors verified successfully!")
        return

    asyncio.run(run_command_on_device(args.mac, args.action, args.param))


if __name__ == "__main__":
    main()
