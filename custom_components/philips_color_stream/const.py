"""Constants for the Philips Color Stream integration."""

DOMAIN = "philips_color_stream"
MANUFACTURER = "Philips"
MODEL_DOUBLE_COLOR = "ColorStream+ (DoubleColor)"
MODEL_LEGACY = "Color Stream (GV_RGB)"

# Seconds of inactivity before the BLE connection is dropped.
# Keeping the connection open while actively controlling the lights ensures near-instant
# (50-100ms) responsiveness without having to re-authenticate on every click.
DISCONNECT_DELAY = 45
DEFAULT_SPEED = 1

# Supported device types
TYPE_DOUBLE_COLOR = "double_color"
TYPE_LEGACY_WLT = "legacy_wlt"
