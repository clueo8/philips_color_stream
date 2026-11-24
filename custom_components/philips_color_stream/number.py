"""Effect speed control for Philips Color Stream."""
from __future__ import annotations

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ColorStreamConfigEntry
from .const import DEFAULT_SPEED
from .device import ColorStreamDevice
from .entity import ColorStreamEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ColorStreamConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([ColorStreamSpeed(entry.runtime_data, entry.title)])


class ColorStreamSpeed(ColorStreamEntity, RestoreNumber):
    _attr_translation_key = "speed"
    _attr_icon = "mdi:speedometer"
    _attr_mode = NumberMode.SLIDER

    def __init__(self, device: ColorStreamDevice, title: str) -> None:
        super().__init__(device, title)
        min_val, max_val = device.speed_range
        self._attr_native_min_value = min_val
        self._attr_native_max_value = max_val
        self._attr_native_step = 1
        self._attr_unique_id = f"{device.address}-speed"
        self._attr_native_value = DEFAULT_SPEED

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_number_data()) is not None:
            if last.native_value is not None:
                self._attr_native_value = last.native_value

    async def async_set_native_value(self, value: float) -> None:
        val = int(value)
        await self._device.set_speed(val)
        self._attr_native_value = val
        self.async_write_ha_state()
