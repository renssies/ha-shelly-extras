"""Service (action) registration for Shelly Extras.

The ``shelly_extras.change_light`` action changes light properties (brightness,
color, color temperature) on lights provided by the core Shelly integration
*without changing their power state*.

Home Assistant's own ``light.turn_on`` always powers a light on when you set a
property. Shelly devices, however, accept property changes independently of the
on/off state: RPC (Gen2+) devices via ``<Component>.Set`` with the ``on`` field
omitted, and block (Gen1) devices via ``set_state`` with the ``turn`` field
omitted. This action reuses the core Shelly integration's own device connection
and error handling to do exactly that.

The service fields deliberately mirror ``light.turn_on`` (same names, same
selectors, same capability filters) so this action is a drop-in replacement.
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
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_component import DATA_INSTANCES
from homeassistant.helpers.service import async_extract_config_entry_ids
from homeassistant.helpers.target import (
    TargetSelection,
    async_extract_referenced_entity_ids,
)
from homeassistant.util import color as color_util

from .const import (
    ATTR_BRIGHTNESS,
    ATTR_BRIGHTNESS_PCT,
    ATTR_COLOR_NAME,
    ATTR_COLOR_TEMP,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_HS_COLOR,
    ATTR_METHOD,
    ATTR_PARAMS,
    ATTR_RGB_COLOR,
    ATTR_RGBW_COLOR,
    ATTR_RGBWW_COLOR,
    ATTR_TRANSITION,
    ATTR_XY_COLOR,
    DOMAIN,
    LOGGER,
    SERVICE_CHANGE_LIGHT,
    SERVICE_RPC_CALL,
    SHELLY_DOMAIN,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse
    from homeassistant.helpers.entity_component import EntityComponent

# Reasonable Kelvin bounds; the actual device range is applied per light.
_MIN_KELVIN = 1000
_MAX_KELVIN = 12000
_MAX_TRANSITION_SEC = 300

_RGB = vol.ExactSequence((cv.byte, cv.byte, cv.byte))
_RGBW = vol.ExactSequence((cv.byte, cv.byte, cv.byte, cv.byte))
_RGBWW = vol.ExactSequence((cv.byte, cv.byte, cv.byte, cv.byte, cv.byte))
_HS = vol.ExactSequence(
    (
        vol.All(vol.Coerce(float), vol.Range(min=0, max=360)),
        vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
    )
)
_XY = vol.ExactSequence(
    (
        vol.All(vol.Coerce(float), vol.Range(min=0, max=1)),
        vol.All(vol.Coerce(float), vol.Range(min=0, max=1)),
    )
)

CHANGE_LIGHT_SCHEMA = vol.Schema(
    {
        **cv.ENTITY_SERVICE_FIELDS,
        vol.Optional(ATTR_TRANSITION): vol.All(
            vol.Coerce(float), vol.Range(0, _MAX_TRANSITION_SEC)
        ),
        vol.Optional(ATTR_BRIGHTNESS): vol.All(vol.Coerce(int), vol.Range(0, 255)),
        vol.Optional(ATTR_BRIGHTNESS_PCT): vol.All(
            vol.Coerce(float), vol.Range(0, 100)
        ),
        vol.Optional(ATTR_COLOR_TEMP_KELVIN): vol.All(
            vol.Coerce(int), vol.Range(min=_MIN_KELVIN, max=_MAX_KELVIN)
        ),
        vol.Optional(ATTR_COLOR_TEMP): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional(ATTR_RGB_COLOR): _RGB,
        vol.Optional(ATTR_RGBW_COLOR): _RGBW,
        vol.Optional(ATTR_RGBWW_COLOR): _RGBWW,
        vol.Optional(ATTR_HS_COLOR): _HS,
        vol.Optional(ATTR_XY_COLOR): _XY,
        vol.Optional(ATTR_COLOR_NAME): cv.string,
    }
)


@dataclass
class LightProperties:
    """Parsed, device-agnostic light properties to apply.

    All of ``light.turn_on``'s color inputs are normalized here into the small
    canonical set the Shelly device understands.
    """

    brightness: int | None = None  # 0..255
    color_temp_kelvin: int | None = None
    rgb_color: tuple[int, int, int] | None = None
    rgbw_color: tuple[int, int, int, int] | None = None
    transition: float | None = None

    @classmethod
    def from_call(cls, call: ServiceCall) -> LightProperties:
        """Build canonical properties from a light.turn_on-style service call."""
        data = call.data

        brightness = data.get(ATTR_BRIGHTNESS)
        if brightness is None and ATTR_BRIGHTNESS_PCT in data:
            brightness = round(255 * data[ATTR_BRIGHTNESS_PCT] / 100)

        color_temp_kelvin = data.get(ATTR_COLOR_TEMP_KELVIN)
        if color_temp_kelvin is None and ATTR_COLOR_TEMP in data:
            color_temp_kelvin = color_util.color_temperature_mired_to_kelvin(
                data[ATTR_COLOR_TEMP]
            )

        rgb: tuple[int, int, int] | None = None
        if ATTR_RGB_COLOR in data:
            rgb = tuple(data[ATTR_RGB_COLOR])
        elif ATTR_HS_COLOR in data:
            rgb = color_util.color_hs_to_RGB(*data[ATTR_HS_COLOR])
        elif ATTR_XY_COLOR in data:
            rgb = color_util.color_xy_to_RGB(*data[ATTR_XY_COLOR])
        elif ATTR_COLOR_NAME in data:
            try:
                rgb = tuple(color_util.color_name_to_rgb(data[ATTR_COLOR_NAME]))
            except ValueError as err:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="invalid_color_name",
                    translation_placeholders={"name": data[ATTR_COLOR_NAME]},
                ) from err

        rgbw: tuple[int, int, int, int] | None = None
        if ATTR_RGBW_COLOR in data:
            rgbw = tuple(data[ATTR_RGBW_COLOR])
        elif ATTR_RGBWW_COLOR in data:
            red, green, blue, cold, warm = data[ATTR_RGBWW_COLOR]
            # Shelly RGBW has a single white channel; combine the two whites.
            rgbw = (red, green, blue, round((cold + warm) / 2))

        return cls(
            brightness=brightness,
            color_temp_kelvin=color_temp_kelvin,
            rgb_color=rgb,
            rgbw_color=rgbw,
            transition=data.get(ATTR_TRANSITION),
        )

    @property
    def has_any(self) -> bool:
        """Return True if at least one settable property was requested."""
        return any(
            value is not None
            for value in (
                self.brightness,
                self.color_temp_kelvin,
                self.rgb_color,
                self.rgbw_color,
            )
        )


def _expand_group_members(hass: HomeAssistant, entity_ids: set[str]) -> set[str]:
    """Recursively expand group entities into their member entity ids.

    Group entities (e.g. light groups created via the Group helper) live in the
    ``light`` domain and are not expanded by ``group.expand_entity_ids`` (which
    only handles the ``group.*`` domain). They advertise their members through
    the ``entity_id`` state attribute, which is what we follow here. Leaf
    entities (no ``entity_id`` attribute) are returned as-is.
    """
    resolved: set[str] = set()
    seen: set[str] = set()
    stack = list(entity_ids)
    while stack:
        entity_id = stack.pop()
        if entity_id in seen:
            continue
        seen.add(entity_id)
        state = hass.states.get(entity_id)
        members = state.attributes.get(ATTR_ENTITY_ID) if state else None
        if members:
            stack.extend(members)
        else:
            resolved.add(entity_id)
    return resolved


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


async def _async_change_light(call: ServiceCall) -> None:
    """Handle the ``shelly_extras.change_light`` service call."""
    hass = call.hass
    props = LightProperties.from_call(call)
    if not props.has_any:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_properties"
        )

    selected = async_extract_referenced_entity_ids(hass, TargetSelection(call.data))
    entity_ids = _expand_group_members(
        hass, selected.referenced | selected.indirectly_referenced
    )

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
            LOGGER.error("Failed to change %s: %s", entity_id, result)
            errors.append(entity_id)
            continue
        if not result:
            LOGGER.warning(
                "%s does not support any of the requested properties; skipped",
                entity_id,
            )
            continue
        LOGGER.debug("Changed %s on %s", ", ".join(result), entity_id)
        coordinators.add(entity.coordinator)

    # Refresh affected devices so Home Assistant state catches up promptly.
    for coordinator in coordinators:
        await coordinator.async_request_refresh()

    if errors:
        raise HomeAssistantError(
            f"Failed to change light(s): {', '.join(sorted(errors))}"
        )


RPC_CALL_SCHEMA = vol.Schema(
    {
        **cv.ENTITY_SERVICE_FIELDS,
        vol.Required(ATTR_METHOD): cv.string,
        vol.Optional(ATTR_PARAMS): dict,
    }
)


def _shelly_rpc_coordinators(
    hass: HomeAssistant, entry_ids: set[str]
) -> list[tuple[str, Any]]:
    """Return (device name, RPC coordinator) for loaded Gen2+ Shelly entries.

    Gen1 (block) devices and unloaded/foreign entries are skipped: only Shelly
    config entries whose runtime data carries an ``rpc`` coordinator qualify.
    """
    result: list[tuple[str, Any]] = []
    for entry_id in entry_ids:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != SHELLY_DOMAIN:
            continue
        rpc = getattr(getattr(entry, "runtime_data", None), "rpc", None)
        if rpc is None:
            LOGGER.debug(
                "Skipping Shelly entry %s: not a loaded Gen2+ (RPC) device",
                entry.title,
            )
            continue
        result.append((entry.title, rpc))
    return result


async def _async_rpc_call(call: ServiceCall) -> ServiceResponse:
    """Handle ``shelly_extras.rpc_call``: send a raw RPC to Gen2+ Shelly devices."""
    hass = call.hass
    method = call.data[ATTR_METHOD]
    params = call.data.get(ATTR_PARAMS)

    entry_ids = await async_extract_config_entry_ids(call)
    coordinators = _shelly_rpc_coordinators(hass, entry_ids)
    if not coordinators:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_rpc_devices"
        )

    responses = await asyncio.gather(
        *(rpc.device.call_rpc(method, params) for _, rpc in coordinators),
        return_exceptions=True,
    )

    results: dict[str, Any] = {}
    errors: list[str] = []
    for (name, _), response in zip(coordinators, responses, strict=True):
        if isinstance(response, Exception):
            LOGGER.error("RPC %s failed on %s: %s", method, name, response)
            errors.append(name)
            results[name] = {"error": str(response)}
        else:
            LOGGER.debug("RPC %s on %s -> %s", method, name, response)
            results[name] = response

    if errors and len(errors) == len(coordinators):
        raise HomeAssistantError(
            f"RPC '{method}' failed on: {', '.join(sorted(errors))}"
        )

    return {"results": results}


def async_register_services(hass: HomeAssistant) -> None:
    """Register all Shelly Extras services."""
    if hass.services.has_service(DOMAIN, SERVICE_CHANGE_LIGHT):
        return

    hass.services.async_register(
        DOMAIN,
        SERVICE_CHANGE_LIGHT,
        _async_change_light,
        schema=CHANGE_LIGHT_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_RPC_CALL,
        _async_rpc_call,
        schema=RPC_CALL_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )


def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove all Shelly Extras services."""
    hass.services.async_remove(DOMAIN, SERVICE_CHANGE_LIGHT)
    hass.services.async_remove(DOMAIN, SERVICE_RPC_CALL)
