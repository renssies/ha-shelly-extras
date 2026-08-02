"""Constants for the Shelly Extras integration."""

from __future__ import annotations

from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "shelly_extras"

# The core Shelly integration domain we hook into.
SHELLY_DOMAIN = "shelly"

# Service names exposed by this integration (see services.yaml).
SERVICE_SET_LIGHT_PROPERTIES = "set_light_properties"

# Service field names (kept aligned with light.turn_on where possible).
ATTR_BRIGHTNESS = "brightness"
ATTR_BRIGHTNESS_PCT = "brightness_pct"
ATTR_COLOR_TEMP_KELVIN = "color_temp_kelvin"
ATTR_RGB_COLOR = "rgb_color"
ATTR_RGBW_COLOR = "rgbw_color"
ATTR_TRANSITION = "transition"
