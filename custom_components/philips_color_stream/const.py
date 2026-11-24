"""Constants for the Philips Color Stream integration."""

DOMAIN = "philips_color_stream"
MANUFACTURER = "Philips"
MODEL_DOUBLE_COLOR = "ColorStream+ (DoubleColor)"
MODEL_LEGACY = "Color Stream (GV_RGB)"

# Seconds of inactivity before the BLE connection is dropped.
# The lights only accept one connection at a time, so releasing it lets the
# phone app or other controllers connect again.
DISCONNECT_DELAY = 45
DEFAULT_SPEED = 1

# Supported device types
TYPE_DOUBLE_COLOR = "double_color"
TYPE_LEGACY_WLT = "legacy_wlt"
