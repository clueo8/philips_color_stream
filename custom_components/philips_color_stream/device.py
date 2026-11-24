"""BLE connection and protocol dispatch for Philips Color Stream lights."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

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

    def set_ble_device(self, ble_device: BLEDevice) -> None:
        self._ble_device = ble_device
        self._telink_proto.mac = ble_device.address

    # ------------------------------------------------------------------ public

    async def turn_on(self) -> None:
        _LOGGER.debug("turn_on called for %s", self.address)
        if self._device_type == TYPE_DOUBLE_COLOR:
            await self._send_telink(self._telink_proto.cmd_power(True))
        else:
            await self._send_legacy(legacy_protocol.cmd_power(self._legacy_id, True))

    async def turn_off(self) -> None:
        _LOGGER.debug("turn_off called for %s", self.address)
        if self._device_type == TYPE_DOUBLE_COLOR:
            await self._send_telink(self._telink_proto.cmd_power(False))
        else:
            await self._send_legacy(legacy_protocol.cmd_power(self._legacy_id, False))

    async def set_brightness(self, percent: int) -> None:
        _LOGGER.debug("set_brightness called for %s: %s%%", self.address, percent)
        if self._device_type == TYPE_DOUBLE_COLOR:
            await self._send_telink(self._telink_proto.cmd_brightness(percent))
        else:
            _LOGGER.debug("Brightness not supported by legacy GV_RGB firmware")

    async def set_effect(self, name: str) -> None:
        _LOGGER.debug("set_effect called for %s: %s", self.address, name)
        if self._device_type == TYPE_DOUBLE_COLOR:
            if name in DOUBLE_COLOR_EFFECTS:
                mode_id, steady = DOUBLE_COLOR_EFFECTS[name]
                await self._send_telink(self._telink_proto.cmd_mode(mode_id, steady))
        else:
            if name in legacy_protocol.LEGACY_EFFECTS:
                mode_num, modifier = legacy_protocol.LEGACY_EFFECTS[name]
                await self._send_legacy(legacy_protocol.cmd_effect(self._legacy_id, mode_num, modifier))

    async def set_speed(self, speed_value: int) -> None:
        _LOGGER.debug("set_speed called for %s: %s", self.address, speed_value)
        if self._device_type == TYPE_DOUBLE_COLOR:
            await self._send_telink(self._telink_proto.cmd_speed(speed_value))
        else:
            await self._send_legacy(legacy_protocol.cmd_speed(self._legacy_id, speed_value))

    async def disconnect(self) -> None:
        self._cancel_timer()
        async with self._lock:
            await self._disconnect_locked()

    # ----------------------------------------------------------------- internal

    async def _send_telink(self, wlt_payload: bytes) -> None:
        async with self._lock:
            for attempt in (1, 2):
                try:
                    client = await self._ensure_connected()
                    cmd_char = await self._find_char(client, UUID_COMMAND)
                    # Replicate the official Telink app: transmit 3 bursts with incrementing seq
                    for b in range(3):
                        packet = self._telink_proto.build_command_packet(wlt_payload)
                        await client.write_gatt_char(cmd_char, packet, response=False)
                        if b < 2:
                            await asyncio.sleep(0.04)
                    _LOGGER.debug("Successfully transmitted 3 bursts to %s: %s", self.address, wlt_payload.hex())
                    break
                except (BleakError, Exception) as err:
                    _LOGGER.warning("Telink write failed on %s (attempt %s): %s", self.address, attempt, err)
                    await self._disconnect_locked()
                    if attempt == 2:
                        raise
                    await asyncio.sleep(0.5)
        self._reset_timer()

    async def _send_legacy(self, packet: bytes) -> None:
        async with self._lock:
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

    async def _find_char(
        self, client: BleakClientWithServiceCache, target_uuid: str
    ) -> BleakGATTCharacteristic:
        """Find a characteristic by exact UUID or suffix, clearing stale cache if missing."""
        if client.services:
            char = client.services.get_characteristic(target_uuid)
            if char is not None:
                return char

            # Check suffix match (e.g. 1914, 1912, 1911)
            suffix = target_uuid[-4:].lower()
            for s in client.services:
                for c in s.characteristics:
                    if c.uuid.lower().replace("-", "").endswith(suffix):
                        _LOGGER.debug("Matched %s by suffix %s", c.uuid, suffix)
                        return c

        # If not found, clear cache and force fresh service discovery
        _LOGGER.warning(
            "Characteristic %s not found in cached services for %s. Clearing cache and rediscovering...",
            target_uuid,
            self.address,
        )
        try:
            if hasattr(client, "clear_cache"):
                await client.clear_cache()
        except Exception as ex:
            _LOGGER.debug("clear_cache error on %s: %s", self.address, ex)

        await client.get_services()

        if client.services:
            char = client.services.get_characteristic(target_uuid)
            if char is not None:
                return char

            suffix = target_uuid[-4:].lower()
            for s in client.services:
                for c in s.characteristics:
                    if c.uuid.lower().replace("-", "").endswith(suffix):
                        return c

        discovered = [f"{c.uuid} (handle {c.handle})" for s in client.services for c in s.characteristics] if client.services else []
        raise BleakError(
            f"Characteristic {target_uuid} was not found on {self.address}! Discovered characteristics: {discovered}"
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

        _LOGGER.debug("Connecting to %s (%s)", self.address, self._device_type)
        client = await establish_connection(
            BleakClientWithServiceCache,
            self._ble_device,
            self._ble_device.name or self.address,
            disconnected_callback=self._on_disconnected,
        )
        self._client = client

        # Populate services if cache is empty
        if not client.services:
            await client.get_services()

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
        try:
            await clear_cache(self.address)
        except Exception:
            pass

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
