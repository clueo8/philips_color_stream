"""Mode selection platform for Philips Color Stream / DoubleColor."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import ColorStreamConfigEntry
from .device import ColorStreamDevice
from .entity import ColorStreamEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ColorStreamConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([ColorStreamModeSelect(entry.runtime_data, entry.title)])


class ColorStreamModeSelect(ColorStreamEntity, SelectEntity, RestoreEntity):
    _attr_translation_key = "mode"
    _attr_icon = "mdi:palette"

    def __init__(self, device: ColorStreamDevice, title: str) -> None:
        super().__init__(device, title)
        self._attr_unique_id = f"{device.address}-mode"
        self._attr_options = device.effect_list
        self._attr_current_option = device.effect_list[0] if device.effect_list else None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            if last.state in self._attr_options:
                self._attr_current_option = last.state

    async def async_select_option(self, option: str) -> None:
        await self._device.set_effect(option)
        self._attr_current_option = option
        self.async_write_ha_state()
