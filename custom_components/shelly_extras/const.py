"""Constants for the Shelly Extras integration."""

from __future__ import annotations

from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "shelly_extras"

# The core Shelly integration domain we hook into.
SHELLY_DOMAIN = "shelly"

# Service names exposed by this integration (see services.yaml).
SERVICE_CHANGE_LIGHT = "change_light"

# Service field names — deliberately identical to light.turn_on so this action
# is a drop-in replacement (same data keys work).
ATTR_TRANSITION = "transition"
ATTR_BRIGHTNESS = "brightness"
ATTR_BRIGHTNESS_PCT = "brightness_pct"
ATTR_COLOR_TEMP_KELVIN = "color_temp_kelvin"
ATTR_COLOR_TEMP = "color_temp"  # mireds
ATTR_RGB_COLOR = "rgb_color"
ATTR_RGBW_COLOR = "rgbw_color"
ATTR_RGBWW_COLOR = "rgbww_color"
ATTR_HS_COLOR = "hs_color"
ATTR_XY_COLOR = "xy_color"
ATTR_COLOR_NAME = "color_name"
