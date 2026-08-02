"""Service (action) registration for Shelly Extras.

Add your extra Shelly-related actions here. Each service should be declared in
``services.yaml`` (for the UI) and registered below.
"""

from __future__ import annotations

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, LOGGER, SERVICE_EXAMPLE_ACTION

EXAMPLE_ACTION_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
        vol.Optional("value"): cv.string,
    }
)


async def _async_example_action(call: ServiceCall) -> None:
    """Handle the ``shelly_extras.example_action`` service call.

    TODO: Implement the real behaviour (e.g. call a Shelly RPC/CoAP endpoint or
    a core Shelly integration entity). This stub only logs its input so the
    integration is loadable and debuggable end-to-end.
    """
    LOGGER.debug("example_action called with data: %s", dict(call.data))


def async_register_services(hass: HomeAssistant) -> None:
    """Register all Shelly Extras services."""
    if hass.services.has_service(DOMAIN, SERVICE_EXAMPLE_ACTION):
        return

    hass.services.async_register(
        DOMAIN,
        SERVICE_EXAMPLE_ACTION,
        _async_example_action,
        schema=EXAMPLE_ACTION_SCHEMA,
    )


def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove all Shelly Extras services."""
    hass.services.async_remove(DOMAIN, SERVICE_EXAMPLE_ACTION)
