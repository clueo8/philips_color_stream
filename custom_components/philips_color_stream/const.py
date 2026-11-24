"""Constants for the Philips Color Stream integration."""

DOMAIN = "philips_color_stream"
MANUFACTURER = "Philips"
MODEL_DOUBLE_COLOR = "ColorStream+ (DoubleColor)"
MODEL_LEGACY = "Color Stream (GV_RGB)"

# Seconds of inactivity before the BLE connection is dropped.
# The lights only accept one connection at a time, so releasing it quickly lets the
# other strands receive RF mesh packets without radio collision, and lets other controllers connect.
DISCONNECT_DELAY = 2.0
DEFAULT_SPEED = 1

# Supported device types
TYPE_DOUBLE_COLOR = "double_color"
TYPE_LEGACY_WLT = "legacy_wlt"
