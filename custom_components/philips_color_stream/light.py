"""Light platform for Philips Color Stream / DoubleColor."""
from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import ColorStreamConfigEntry
from .const import CONF_ENABLE_ALL_STRANDS, DOMAIN, TYPE_DOUBLE_COLOR
from .device import ColorStreamDevice
from .entity import ColorStreamEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ColorStreamConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    device = entry.runtime_data
    entities: list[LightEntity] = [ColorStreamLight(device, entry.title)]

    if device.device_type == TYPE_DOUBLE_COLOR:
        entries = hass.config_entries.async_entries(DOMAIN)
        is_first = bool(entries and entries[0].entry_id == entry.entry_id)
        enable_master = entry.options.get(
            CONF_ENABLE_ALL_STRANDS,
            entry.data.get(CONF_ENABLE_ALL_STRANDS, is_first),
        )
        if enable_master:
            entities.append(ColorStreamAllStrandsLight(device, entry.title))

    async_add_entities(entities)


class ColorStreamLight(ColorStreamEntity, LightEntity, RestoreEntity):
    _attr_name = None

    def __init__(self, device: ColorStreamDevice, title: str) -> None:
        super().__init__(device, title)
        self._attr_unique_id = device.address
        self._attr_is_on = False
        self._attr_effect = None
        self._attr_effect_list = device.effect_list
        self._attr_supported_features = LightEntityFeature.EFFECT

        if device.device_type == TYPE_DOUBLE_COLOR:
            self._attr_color_mode = ColorMode.BRIGHTNESS
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
            self._attr_brightness = 255
        else:
            self._attr_color_mode = ColorMode.ONOFF
            self._attr_supported_color_modes = {ColorMode.ONOFF}
            self._attr_brightness = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self._attr_is_on = last.state == STATE_ON
            if (last_eff := last.attributes.get(ATTR_EFFECT)) in self._attr_effect_list:
                self._attr_effect = last_eff
            if (last_bri := last.attributes.get(ATTR_BRIGHTNESS)) is not None:
                self._attr_brightness = last_bri

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._attr_is_on = True
        if (effect := kwargs.get(ATTR_EFFECT)) is not None:
            self._attr_effect = effect
        if (brightness := kwargs.get(ATTR_BRIGHTNESS)) is not None:
            self._attr_brightness = brightness
        self.async_write_ha_state()

        if not kwargs or ATTR_EFFECT not in kwargs:
            await self._device.turn_on(broadcast=False)

        if (effect := kwargs.get(ATTR_EFFECT)) is not None:
            await self._device.set_effect(effect, broadcast=False)

        if (brightness := kwargs.get(ATTR_BRIGHTNESS)) is not None:
            pct = max(1, min(100, round((brightness / 255.0) * 100)))
            await self._device.set_brightness(pct, broadcast=False)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._attr_is_on = False
        self.async_write_ha_state()
        await self._device.turn_off(broadcast=False)


class ColorStreamAllStrandsLight(ColorStreamEntity, LightEntity, RestoreEntity):
    _attr_name = "All Strands"

    def __init__(self, device: ColorStreamDevice, title: str) -> None:
        super().__init__(device, title)
        self._attr_unique_id = f"{device.address}_all_strands"
        self._attr_is_on = False
        self._attr_effect = None
        self._attr_effect_list = device.effect_list
        self._attr_supported_features = LightEntityFeature.EFFECT
        self._attr_color_mode = ColorMode.BRIGHTNESS
        self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
        self._attr_brightness = 255

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self._attr_is_on = last.state == STATE_ON
            if (last_eff := last.attributes.get(ATTR_EFFECT)) in self._attr_effect_list:
                self._attr_effect = last_eff
            if (last_bri := last.attributes.get(ATTR_BRIGHTNESS)) is not None:
                self._attr_brightness = last_bri

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._attr_is_on = True
        if (effect := kwargs.get(ATTR_EFFECT)) is not None:
            self._attr_effect = effect
        if (brightness := kwargs.get(ATTR_BRIGHTNESS)) is not None:
            self._attr_brightness = brightness
        self.async_write_ha_state()

        if not kwargs or ATTR_EFFECT not in kwargs:
            await self._device.turn_on(broadcast=True)

        if (effect := kwargs.get(ATTR_EFFECT)) is not None:
            await self._device.set_effect(effect, broadcast=True)

        if (brightness := kwargs.get(ATTR_BRIGHTNESS)) is not None:
            pct = max(1, min(100, round((brightness / 255.0) * 100)))
            await self._device.set_brightness(pct, broadcast=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._attr_is_on = False
        self.async_write_ha_state()
        await self._device.turn_off(broadcast=True)
