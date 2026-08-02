"""The Shelly Extras integration.

Companion integration that registers extra *actions* (services) that operate on
top of the core Home Assistant Shelly integration. It intentionally owns no
entities; it only adds services.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, LOGGER
from .services import async_register_services, async_unregister_services

type ShellyExtrasConfigEntry = ConfigEntry


async def async_setup_entry(hass: HomeAssistant, entry: ShellyExtrasConfigEntry) -> bool:
    """Set up Shelly Extras from a config entry."""
    LOGGER.debug("Setting up Shelly Extras")
    async_register_services(hass)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ShellyExtrasConfigEntry
) -> bool:
    """Unload a config entry."""
    # Only unregister the services once the last entry is being removed.
    if len(hass.config_entries.async_entries(DOMAIN)) <= 1:
        async_unregister_services(hass)
    return True
