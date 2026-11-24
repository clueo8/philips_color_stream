"""Shared entity base for Philips Color Stream."""
from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, MANUFACTURER
from .device import ColorStreamDevice


class ColorStreamEntity(Entity):
    _attr_has_entity_name = True
    _attr_assumed_state = True

    def __init__(self, device: ColorStreamDevice, title: str) -> None:
        self._device = device
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.address)},
            connections={(CONNECTION_BLUETOOTH, device.address)},
            manufacturer=MANUFACTURER,
            model=device.model_name,
            name=title,
        )
