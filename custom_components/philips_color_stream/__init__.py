"""The Philips Color Stream / DoubleColor integration."""
from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DISCONNECT_DELAY
from .device import ColorStreamDevice

PLATFORMS = [Platform.LIGHT, Platform.NUMBER]

type ColorStreamConfigEntry = ConfigEntry[ColorStreamDevice]


async def async_setup_entry(hass: HomeAssistant, entry: ColorStreamConfigEntry) -> bool:
    address: str = entry.data[CONF_ADDRESS]
    ble_device = bluetooth.async_ble_device_from_address(
        hass, address.upper(), connectable=True
    )
    if ble_device is None:
        raise ConfigEntryNotReady(f"Could not find Color Stream / DoubleColor lights at {address}")

    device = ColorStreamDevice(ble_device, DISCONNECT_DELAY)
    entry.runtime_data = device

    @callback
    def _async_update_ble(
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        device.set_ble_device(service_info.device)

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            _async_update_ble,
            bluetooth.BluetoothCallbackMatcher(address=address, connectable=True),
            bluetooth.BluetoothScanningMode.PASSIVE,
        )
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ColorStreamConfigEntry) -> bool:
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.disconnect()
    return unload_ok
