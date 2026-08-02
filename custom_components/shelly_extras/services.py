"""Service (action) registration for Shelly Extras.

The ``shelly_extras.set_light_properties`` action changes light properties
(brightness, color, color temperature) on lights provided by the core Shelly
integration *without changing their power state*.

Home Assistant's own ``light.turn_on`` always powers a light on when you set a
property. Shelly devices, however, accept property changes independently of the
on/off state: RPC (Gen2+) devices via ``<Component>.Set`` with the ``on`` field
omitted, and block (Gen1) devices via ``set_state`` with the ``turn`` field
omitted. This action reuses the core Shelly integration's own device connection
and error handling to do exactly that.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.components.light import (
    DOMAIN as LIGHT_DOMAIN,
    ColorMode,
    brightness_supported,
)
from homeassistant.components.shelly.const import (
    BLOCK_MAX_TRANSITION_TIME_MS,
    DUAL_MODE_LIGHT_MODELS,
    RPC_MIN_TRANSITION_TIME_SEC,
)
from homeassistant.components.shelly.light import BlockShellyLight, RpcShellyLightBase
from homeassistant.components.shelly.utils import brightness_to_percentage
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_component import DATA_INSTANCES
from homeassistant.helpers.target import (
    TargetSelection,
    async_extract_referenced_entity_ids,
)

from .const import (
    ATTR_BRIGHTNESS,
    ATTR_BRIGHTNESS_PCT,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_RGB_COLOR,
    ATTR_RGBW_COLOR,
    ATTR_TRANSITION,
    DOMAIN,
    LOGGER,
    SERVICE_SET_LIGHT_PROPERTIES,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, ServiceCall
    from homeassistant.helpers.entity_component import EntityComponent

# Reasonable Kelvin bounds; the actual device range is applied per light.
_MIN_KELVIN = 1000
_MAX_KELVIN = 12000
_MAX_TRANSITION_SEC = 300

SET_LIGHT_PROPERTIES_SCHEMA = vol.Schema(
    {
        **cv.ENTITY_SERVICE_FIELDS,
        vol.Optional(ATTR_BRIGHTNESS): vol.All(vol.Coerce(int), vol.Range(0, 255)),
        vol.Optional(ATTR_BRIGHTNESS_PCT): vol.All(
            vol.Coerce(float), vol.Range(0, 100)
        ),
        vol.Optional(ATTR_COLOR_TEMP_KELVIN): vol.All(
            vol.Coerce(int), vol.Range(min=_MIN_KELVIN, max=_MAX_KELVIN)
        ),
        vol.Optional(ATTR_RGB_COLOR): vol.All(
            vol.ExactSequence((cv.byte, cv.byte, cv.byte)), vol.Coerce(tuple)
        ),
        vol.Optional(ATTR_RGBW_COLOR): vol.All(
            vol.ExactSequence((cv.byte, cv.byte, cv.byte, cv.byte)), vol.Coerce(tuple)
        ),
        vol.Optional(ATTR_TRANSITION): vol.All(
            vol.Coerce(float), vol.Range(0, _MAX_TRANSITION_SEC)
        ),
    }
)


@dataclass
class LightProperties:
    """Parsed, device-agnostic light properties to apply."""

    brightness: int | None = None  # 0..255
    color_temp_kelvin: int | None = None
    rgb_color: tuple[int, int, int] | None = None
    rgbw_color: tuple[int, int, int, int] | None = None
    transition: float | None = None

    @classmethod
    def from_call(cls, call: ServiceCall) -> LightProperties:
        """Build properties from a service call, normalizing brightness."""
        brightness = call.data.get(ATTR_BRIGHTNESS)
        if brightness is None and ATTR_BRIGHTNESS_PCT in call.data:
            brightness = round(255 * call.data[ATTR_BRIGHTNESS_PCT] / 100)
        return cls(
            brightness=brightness,
            color_temp_kelvin=call.data.get(ATTR_COLOR_TEMP_KELVIN),
            rgb_color=call.data.get(ATTR_RGB_COLOR),
            rgbw_color=call.data.get(ATTR_RGBW_COLOR),
            transition=call.data.get(ATTR_TRANSITION),
        )

    @property
    def has_any(self) -> bool:
        """Return True if at least one property was requested."""
        return any(
            value is not None
            for value in (
                self.brightness,
                self.color_temp_kelvin,
                self.rgb_color,
                self.rgbw_color,
            )
        )


def _resolve_shelly_light(
    hass: HomeAssistant, entity_id: str
) -> RpcShellyLightBase | BlockShellyLight | None:
    """Return the live core-Shelly light entity for an entity id, or None."""
    component: EntityComponent | None = hass.data.get(DATA_INSTANCES, {}).get(
        LIGHT_DOMAIN
    )
    if component is None:
        return None
    entity = component.get_entity(entity_id)
    if isinstance(entity, (RpcShellyLightBase, BlockShellyLight)):
        return entity
    return None


async def _apply_rpc(entity: RpcShellyLightBase, props: LightProperties) -> list[str]:
    """Apply properties to an RPC (Gen2+) Shelly light without touching power."""
    modes: set[ColorMode] = entity.supported_color_modes or set()
    params: dict[str, Any] = {"id": entity._id}  # noqa: SLF001
    applied: list[str] = []

    if props.brightness is not None and brightness_supported(modes):
        params["brightness"] = brightness_to_percentage(props.brightness)
        applied.append(ATTR_BRIGHTNESS)
    if props.color_temp_kelvin is not None and ColorMode.COLOR_TEMP in modes:
        params["ct"] = props.color_temp_kelvin
        applied.append(ATTR_COLOR_TEMP_KELVIN)
    if props.rgb_color is not None and modes & {ColorMode.RGB, ColorMode.RGBW}:
        params["rgb"] = list(props.rgb_color)
        applied.append(ATTR_RGB_COLOR)
    if props.rgbw_color is not None and ColorMode.RGBW in modes:
        params["rgb"] = list(props.rgbw_color[:-1])
        params["white"] = props.rgbw_color[-1]
        applied.append(ATTR_RGBW_COLOR)
    if props.transition is not None:
        params["transition_duration"] = max(
            props.transition, RPC_MIN_TRANSITION_TIME_SEC
        )

    if not applied:
        return []

    # Multi-mode lights (e.g. RGBCCT) need an explicit mode alongside the change.
    if entity.status.get("mode") is not None:
        if ATTR_COLOR_TEMP_KELVIN in applied:
            params["mode"] = "cct"
        elif {ATTR_RGB_COLOR, ATTR_RGBW_COLOR} & set(applied):
            params["mode"] = "rgb"

    await entity.call_rpc(f"{entity._component}.Set", params)  # noqa: SLF001
    return applied


async def _apply_block(entity: BlockShellyLight, props: LightProperties) -> list[str]:
    """Apply properties to a block (Gen1) Shelly light without touching power."""
    modes: set[ColorMode] = entity.supported_color_modes or set()
    block = entity.block
    params: dict[str, Any] = {}
    applied: list[str] = []
    set_mode: str | None = None

    if props.brightness is not None and brightness_supported(modes):
        pct = brightness_to_percentage(props.brightness)
        if hasattr(block, "gain"):
            params["gain"] = pct
        if hasattr(block, "brightness"):
            params["brightness"] = pct
        applied.append(ATTR_BRIGHTNESS)
    if props.color_temp_kelvin is not None and ColorMode.COLOR_TEMP in modes:
        set_mode = "white"
        params["temp"] = int(
            min(
                entity.max_color_temp_kelvin,
                max(entity.min_color_temp_kelvin, props.color_temp_kelvin),
            )
        )
        applied.append(ATTR_COLOR_TEMP_KELVIN)
    if props.rgb_color is not None and modes & {ColorMode.RGB, ColorMode.RGBW}:
        set_mode = "color"
        params["red"], params["green"], params["blue"] = props.rgb_color
        applied.append(ATTR_RGB_COLOR)
    if props.rgbw_color is not None and ColorMode.RGBW in modes:
        set_mode = "color"
        (params["red"], params["green"], params["blue"], params["white"]) = (
            props.rgbw_color
        )
        applied.append(ATTR_RGBW_COLOR)
    if props.transition is not None:
        params["transition"] = min(
            int(props.transition * 1000), BLOCK_MAX_TRANSITION_TIME_MS
        )

    if not applied:
        return []

    if (
        set_mode
        and set_mode != entity.mode
        and entity.coordinator.model in DUAL_MODE_LIGHT_MODELS
    ):
        params["mode"] = set_mode

    await entity.set_state(**params)
    return applied


async def _async_apply(
    entity: RpcShellyLightBase | BlockShellyLight, props: LightProperties
) -> list[str]:
    """Dispatch to the RPC or block implementation."""
    if isinstance(entity, RpcShellyLightBase):
        return await _apply_rpc(entity, props)
    return await _apply_block(entity, props)


async def _async_set_light_properties(call: ServiceCall) -> None:
    """Handle the ``shelly_extras.set_light_properties`` service call."""
    hass = call.hass
    props = LightProperties.from_call(call)
    if not props.has_any:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_properties"
        )

    selected = async_extract_referenced_entity_ids(hass, TargetSelection(call.data))
    entity_ids = selected.referenced | selected.indirectly_referenced

    lights = [
        (entity_id, entity)
        for entity_id in entity_ids
        if (entity := _resolve_shelly_light(hass, entity_id)) is not None
    ]
    if not lights:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_shelly_lights"
        )

    results = await asyncio.gather(
        *(_async_apply(entity, props) for _, entity in lights),
        return_exceptions=True,
    )

    errors: list[str] = []
    coordinators = set()
    for (entity_id, entity), result in zip(lights, results, strict=True):
        if isinstance(result, Exception):
            LOGGER.error("Failed to set properties on %s: %s", entity_id, result)
            errors.append(entity_id)
            continue
        if not result:
            LOGGER.warning(
                "%s does not support any of the requested properties; skipped",
                entity_id,
            )
            continue
        LOGGER.debug("Set %s on %s", ", ".join(result), entity_id)
        coordinators.add(entity.coordinator)

    # Refresh affected devices so Home Assistant state catches up promptly.
    for coordinator in coordinators:
        await coordinator.async_request_refresh()

    if errors:
        raise HomeAssistantError(
            f"Failed to set light properties on: {', '.join(sorted(errors))}"
        )


def async_register_services(hass: HomeAssistant) -> None:
    """Register all Shelly Extras services."""
    if hass.services.has_service(DOMAIN, SERVICE_SET_LIGHT_PROPERTIES):
        return

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_LIGHT_PROPERTIES,
        _async_set_light_properties,
        schema=SET_LIGHT_PROPERTIES_SCHEMA,
    )


def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove all Shelly Extras services."""
    hass.services.async_remove(DOMAIN, SERVICE_SET_LIGHT_PROPERTIES)
