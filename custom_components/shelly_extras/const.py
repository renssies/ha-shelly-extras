"""Constants for the Shelly Extras integration."""

from __future__ import annotations

from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "shelly_extras"

# Service names exposed by this integration (see services.yaml).
SERVICE_EXAMPLE_ACTION = "example_action"
