"""Config flow for Shelly Extras.

The integration is a single-instance service provider, so the flow simply
creates one entry with no user-supplied configuration.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class ShellyExtrasConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Shelly Extras."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(title="Shelly Extras", data={})

        return self.async_show_form(step_id="user")
