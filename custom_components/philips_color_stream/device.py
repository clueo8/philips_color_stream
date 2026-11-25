"""BLE connection and protocol dispatch for Philips Color Stream lights."""
from __future__ import annotations

import asyncio
from datetime import datetime
import logging
import uuid

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    clear_cache,
    establish_connection,
)
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from .const import (
    DISCONNECT_DELAY,
    MODEL_DOUBLE_COLOR,
    MODEL_LEGACY,
    TYPE_DOUBLE_COLOR,
    TYPE_LEGACY_WLT,
)
from . import legacy_protocol
from .telink_protocol import (
    BROADCAST_DEST,
    DOUBLE_COLOR_EFFECTS,
    TelinkMeshProtocol,
    UUID_COMMAND,
    UUID_NOTIFY,
    UUID_PAIR,
)

_LOGGER = logging.getLogger(__name__)


def detect_device_type(ble_device: BLEDevice) -> str:
    """Determine whether this device is a Telink DoubleColor or legacy GV_RGB device."""
    name = ble_device.name or ""
    if name.startswith("Double") or name.startswith("BiColor"):
        return TYPE_DOUBLE_COLOR
    if name.startswith("GV_RGB"):
        return TYPE_LEGACY_WLT
    return TYPE_DOUBLE_COLOR


class ColorStreamDevice:
    """Unified device manager for Philips Color Stream / DoubleColor."""

    def __init__(
        self,
        ble_device: BLEDevice,
        disconnect_delay: float = DISCONNECT_DELAY,
        hass: HomeAssistant | None = None,
    ) -> None:
        self._ble_device = ble_device
        self._disconnect_delay = disconnect_delay
        self._hass = hass
        self._device_type = detect_device_type(ble_device)
        self._client: BleakClientWithServiceCache | None = None
        self._lock = asyncio.Lock()
        self._disconnect_timer: asyncio.TimerHandle | None = None
        self._use_services_cache: bool = True
        self._cmd_seq: int = 0

        # Telink specific state
        self._telink_proto = TelinkMeshProtocol(ble_device.address)

        # Legacy specific state
        mac_bytes = bytes.fromhex("".join(c for c in ble_device.address if c in "0123456789abcdefABCDEF"))
        self._legacy_id = mac_bytes[-2:] if len(mac_bytes) >= 2 else b"\x00\x00"

    @property
    def address(self) -> str:
        return self._ble_device.address

    @property
    def device_type(self) -> str:
        return self._device_type

    @property
    def model_name(self) -> str:
        return MODEL_DOUBLE_COLOR if self._device_type == TYPE_DOUBLE_COLOR else MODEL_LEGACY

    @property
    def effect_list(self) -> list[str]:
        if self._device_type == TYPE_DOUBLE_COLOR:
            return list(DOUBLE_COLOR_EFFECTS.keys())
        return list(legacy_protocol.LEGACY_EFFECTS.keys())

    @property
    def speed_range(self) -> tuple[int, int]:
        """Min and max speed supported."""
        if self._device_type == TYPE_DOUBLE_COLOR:
            return (1, 4)
        return (1, 100)

    @property
    def supports_speed(self) -> bool:
        """DoubleColor hardware does not support speed control; only legacy models do."""
        return self._device_type != TYPE_DOUBLE_COLOR

    def set_ble_device(self, ble_device: BLEDevice) -> None:
        self._ble_device = ble_device
        self._telink_proto.set_mac(ble_device.address)

    # ------------------------------------------------------------------ public

    async def turn_on(self, broadcast: bool = False) -> None:
        _LOGGER.debug("turn_on called for %s (broadcast=%s)", self.address, broadcast)
        if self._device_type == TYPE_DOUBLE_COLOR:
            dest = BROADCAST_DEST if broadcast else self._telink_proto.unicast_mesh_address
            # Send 7 bursts (~650ms) to ensure sleeping standby nodes with 500ms sleep
            # intervals are reliably woken on the very first attempt.
            await self._send_telink(self._telink_proto.cmd_power(True), bursts=7, dest=dest)
        else:
            await self._send_legacy(legacy_protocol.cmd_power(self._legacy_id, True))

    async def turn_off(self, broadcast: bool = False) -> None:
        _LOGGER.debug("turn_off called for %s (broadcast=%s)", self.address, broadcast)
        if self._device_type == TYPE_DOUBLE_COLOR:
            dest = BROADCAST_DEST if broadcast else self._telink_proto.unicast_mesh_address
            await self._send_telink(self._telink_proto.cmd_power(False), bursts=6, dest=dest)
        else:
            await self._send_legacy(legacy_protocol.cmd_power(self._legacy_id, False))

    async def set_brightness(self, percent: int, broadcast: bool = False) -> None:
        _LOGGER.debug("set_brightness called for %s: %s%% (broadcast=%s)", self.address, percent, broadcast)
        if self._device_type == TYPE_DOUBLE_COLOR:
            dest = BROADCAST_DEST if broadcast else self._telink_proto.unicast_mesh_address
            await self._send_telink(self._telink_proto.cmd_brightness(percent), dest=dest)
        else:
            _LOGGER.debug("Brightness not supported by legacy GV_RGB firmware")

    async def set_effect(self, name: str, broadcast: bool = False) -> None:
        _LOGGER.debug("set_effect called for %s: %s (broadcast=%s)", self.address, name, broadcast)
        if self._device_type == TYPE_DOUBLE_COLOR:
            if name in DOUBLE_COLOR_EFFECTS:
                mode_id = DOUBLE_COLOR_EFFECTS[name]
                dest = BROADCAST_DEST if broadcast else self._telink_proto.unicast_mesh_address
                await self._send_telink(self._telink_proto.cmd_mode(mode_id), dest=dest)
        else:
            if name in legacy_protocol.LEGACY_EFFECTS:
                mode_num, modifier = legacy_protocol.LEGACY_EFFECTS[name]
                await self._send_legacy(legacy_protocol.cmd_effect(self._legacy_id, mode_num, modifier))

    async def set_speed(self, speed_value: int) -> None:
        _LOGGER.debug("set_speed called for %s: %s", self.address, speed_value)
        if self._device_type == TYPE_DOUBLE_COLOR:
            _LOGGER.debug("Speed control not supported on DoubleColor hardware; ignoring")
            return
        await self._send_legacy(legacy_protocol.cmd_speed(self._legacy_id, speed_value))

    async def disconnect(self) -> None:
        self._cancel_timer()
        async with self._lock:
            await self._disconnect_locked()

    # ----------------------------------------------------------------- internal

    async def _send_telink(self, wlt_payload: bytes, bursts: int = 5, dest: int | None = None) -> None:
        self._cmd_seq += 1
        my_seq = self._cmd_seq
        async with self._lock:
            if my_seq < self._cmd_seq:
                _LOGGER.debug(
                    "Skipping superseded command %s on %s (newer command #%d pending)",
                    wlt_payload.hex(),
                    self.address,
                    self._cmd_seq,
                )
                return
            for attempt in (1, 2):
                try:
                    client = await self._ensure_connected()
                    cmd_char = await self._find_char(client, UUID_COMMAND)
                    # Transmit bursts spaced at ~100ms (matching official app ~105ms timing).
                    # Waking up sleeping mesh nodes from standby requires spanning >500ms.
                    for b in range(bursts):
                        packet = self._telink_proto.build_command_packet(wlt_payload, dest=dest)
                        await client.write_gatt_char(cmd_char, packet, response=False)
                        if b < bursts - 1:
                            await asyncio.sleep(0.10)
                    _LOGGER.debug(
                        "Successfully transmitted %d bursts to %s (dest=0x%04x): %s",
                        bursts,
                        self.address,
                        dest if dest is not None else self._telink_proto.unicast_mesh_address,
                        wlt_payload.hex(),
                    )
                    break
                except (BleakError, Exception) as err:
                    _LOGGER.warning("Telink write failed on %s (attempt %s): %s", self.address, attempt, err)
                    await self._disconnect_locked()
                    if attempt == 2:
                        raise
                    await asyncio.sleep(0.5)
        self._reset_timer()

    async def _send_legacy(self, packet: bytes) -> None:
        self._cmd_seq += 1
        my_seq = self._cmd_seq
        async with self._lock:
            if my_seq < self._cmd_seq:
                _LOGGER.debug(
                    "Skipping superseded legacy command %s on %s (newer command #%d pending)",
                    packet.hex(),
                    self.address,
                    self._cmd_seq,
                )
                return
            for attempt in (1, 2):
                try:
                    client = await self._ensure_connected()
                    await client.write_gatt_char(legacy_protocol.WRITE_CHAR_UUID, packet, response=False)
                    break
                except (BleakError, Exception) as err:
                    _LOGGER.warning("Legacy write failed on %s (attempt %s): %s", self.address, attempt, err)
                    await self._disconnect_locked()
                    if attempt == 2:
                        raise
                    await asyncio.sleep(0.5)
        self._reset_timer()

    def _has_required_services(self, client: BleakClientWithServiceCache) -> bool:
        """Check if discovered services contain the required Telink or Legacy characteristics."""
        if not client.services:
            return False
        if self._device_type == TYPE_DOUBLE_COLOR:
            for s in client.services:
                for c in s.characteristics:
                    c_clean = c.uuid.lower().replace("-", "")
                    if "1914" in c_clean or "1419" in c_clean or "1912" in c_clean or "1219" in c_clean:
                        return True
            return False
        else:
            for s in client.services:
                for c in s.characteristics:
                    c_clean = c.uuid.lower().replace("-", "")
                    if "fff2" in c_clean or "f2ff" in c_clean:
                        return True
            return False

    async def _find_char(
        self, client: BleakClientWithServiceCache, target_uuid: str
    ) -> BleakGATTCharacteristic:
        """Find a characteristic by exact UUID, byte-reversed UUID, or 16-bit identifier."""
        if client.services:
            # 1. Exact match
            char = client.services.get_characteristic(target_uuid)
            if char is not None:
                return char

            # 2. Check byte-reversed UUID (ESPHome big-endian representation)
            # e.g. 00010203-0405-0607-0809-0a0b0c0d1914 <-> 14190d0c-0b0a-0908-0706-050403020100
            clean_hex = target_uuid.replace("-", "")
            if len(clean_hex) == 32:
                rev_uuid = str(uuid.UUID(bytes=bytes.fromhex(clean_hex)[::-1]))
                char = client.services.get_characteristic(rev_uuid)
                if char is not None:
                    _LOGGER.debug("Matched characteristic %s by reversed UUID for %s", rev_uuid, target_uuid)
                    return char

            # 3. Match by 4-hex pattern (e.g. '1914' or '1419')
            s1 = target_uuid[-4:].lower()
            s2 = s1[2:4] + s1[0:2]
            for s in client.services:
                for c in s.characteristics:
                    c_clean = c.uuid.lower().replace("-", "")
                    if s1 in c_clean or s2 in c_clean:
                        _LOGGER.debug("Matched characteristic %s by identifier %s/%s", c.uuid, s1, s2)
                        return c

        discovered = {s.uuid: [c.uuid for c in s.characteristics] for s in client.services} if client.services else {}
        self._use_services_cache = False
        try:
            if hasattr(client, "clear_cache"):
                await client.clear_cache()
            await clear_cache(self.address)
        except Exception:
            pass
        raise BleakError(
            f"Characteristic {target_uuid} was not found on {self.address}! Discovered services: {discovered}"
        )

    async def _ensure_connected(self) -> BleakClientWithServiceCache:
        if self._client is not None and self._client.is_connected:
            return self._client

        # Fetch fresh BLEDevice from Home Assistant Bluetooth manager if available
        if self._hass is not None:
            fresh_ble = bluetooth.async_ble_device_from_address(
                self._hass, self.address.upper(), connectable=True
            ) or bluetooth.async_ble_device_from_address(
                self._hass, self.address.lower(), connectable=True
            )
            if fresh_ble is not None:
                self._ble_device = fresh_ble

        use_cache = self._use_services_cache
        _LOGGER.debug("Connecting to %s (%s, use_services_cache=%s)", self.address, self._device_type, use_cache)
        client = await establish_connection(
            BleakClientWithServiceCache,
            self._ble_device,
            self._ble_device.name or self.address,
            disconnected_callback=self._on_disconnected,
            use_services_cache=use_cache,
            max_attempts=2,
        )

        # If cached services are missing required characteristics, immediately clear cache
        # and reconnect fresh with zero artificial delay
        if not self._has_required_services(client) and use_cache:
            _LOGGER.debug("Cached services on %s incomplete. Clearing cache and reconnecting fresh...", self.address)
            try:
                if hasattr(client, "clear_cache"):
                    await client.clear_cache()
                await clear_cache(self.address)
                await client.disconnect()
            except Exception:
                pass
            client = await establish_connection(
                BleakClientWithServiceCache,
                self._ble_device,
                self._ble_device.name or self.address,
                disconnected_callback=self._on_disconnected,
                use_services_cache=False,
                max_attempts=2,
            )

        # If STILL incomplete, abort cleanly so caller's retry loop can re-attempt
        if not self._has_required_services(client):
            discovered = {s.uuid: [c.uuid for c in s.characteristics] for s in client.services} if client.services else {}
            try:
                if hasattr(client, "clear_cache"):
                    await client.clear_cache()
                await clear_cache(self.address)
                await client.disconnect()
            except Exception:
                pass
            raise BleakError(
                f"Required GATT services not found on {self.address} after discovery. Discovered services: {discovered}"
            )

        # Success - cache is now valid for fast subsequent connections
        self._use_services_cache = True
        self._client = client

        if self._device_type == TYPE_DOUBLE_COLOR:
            await self._handshake_telink(client)
        else:
            await self._handshake_legacy(client)

        return client

    async def _handshake_telink(self, client: BleakClientWithServiceCache) -> None:
        """Perform the 0x0C Telink authentication handshake."""
        _LOGGER.debug("Authenticating with Telink mesh on %s...", self.address)
        pair_char = await self._find_char(client, UUID_PAIR)
        randm, login_pkt = self._telink_proto.build_login_packet()
        await client.write_gatt_char(pair_char, login_pkt, response=True)
        await asyncio.sleep(0.3)

        reply = await client.read_gatt_char(pair_char)
        if len(reply) < 9 or reply[0] == 0x0E:
            raise RuntimeError(f"Telink authentication rejected by {self.address}: {bytes(reply).hex()}")

        rands = bytes(reply[1:9])
        self._telink_proto.derive_session_key(randm, rands)
        _LOGGER.debug("Authenticated with %s. Session key established.", self.address)

    async def _handshake_legacy(self, client: BleakClientWithServiceCache) -> None:
        """Legacy probe handshake on FFF0/FFF2."""
        try:
            await client.start_notify(legacy_protocol.NOTIFY_CHAR_UUID, lambda _s, _d: None)
            await client.write_gatt_char(legacy_protocol.WRITE_CHAR_UUID, legacy_protocol.cmd_probe(), response=False)
            await asyncio.sleep(0.2)
            await client.write_gatt_char(
                legacy_protocol.WRITE_CHAR_UUID,
                legacy_protocol.cmd_time_sync(datetime.now()),
                response=False,
            )
            await client.write_gatt_char(legacy_protocol.WRITE_CHAR_UUID, legacy_protocol.cmd_probe_done(), response=False)
        except Exception as ex:
            _LOGGER.debug("Legacy handshake note on %s: %s", self.address, ex)

    def _on_disconnected(self, _client) -> None:
        _LOGGER.debug("Disconnected from %s", self.address)
        self._client = None

    async def _disconnect_locked(self) -> None:
        client, self._client = self._client, None
        if client is not None and client.is_connected:
            try:
                await client.disconnect()
            except BleakError as err:
                _LOGGER.debug("Error disconnecting %s: %s", self.address, err)

    def _reset_timer(self) -> None:
        self._cancel_timer()
        loop = asyncio.get_running_loop()
        self._disconnect_timer = loop.call_later(
            self._disconnect_delay,
            lambda: asyncio.ensure_future(self.disconnect()),
        )

    def _cancel_timer(self) -> None:
        if self._disconnect_timer is not None:
            self._disconnect_timer.cancel()
            self._disconnect_timer = None
