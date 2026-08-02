# Shelly Extras

Companion integration that adds extra **actions** (services) on top of the core Home Assistant Shelly integration.

## Actions

### `shelly_extras.set_light_properties`

Changes a Shelly light's **brightness, color, or color temperature without
changing its power state** — the piece `light.turn_on` can't do, since setting
any property there always powers the light on.

- Works on lights already configured through the **core Shelly integration**
  (both Gen2+ RPC devices and Gen1 block devices).
- Uses the same **target picker as `light.turn_on`** — pick a single light, a
  device, an area, or a label. The picker is restricted to Shelly lights.
- If a light is **off it stays off**; the Shelly device stores the new values
  and applies them the next time it turns on. If it's on, the change is applied
  live.
- Only properties the target light supports are sent; unsupported targets are
  skipped with a warning.

**Fields:** `brightness` (0-255) or `brightness_pct` (0-100),
`color_temp_kelvin`, `rgb_color`, `rgbw_color`, `transition` (seconds).

Example:

```yaml
action: shelly_extras.set_light_properties
target:
  area_id: living_room
data:
  brightness_pct: 40
  rgb_color: [255, 120, 60]
```

How it works: RPC devices are driven via `<Component>.Set` (e.g. `RGB.Set`,
`CCT.Set`) with the `on` field omitted; block devices via `set_state` with the
`turn` field omitted. It reuses the core Shelly integration's own device
connection and error handling.

## Installation (HACS custom repository)

1. In HACS → *Integrations* → ⋮ → **Custom repositories**, add this repo's URL
   with category **Integration**.
2. Install **Shelly Extras**, then restart Home Assistant.
3. Add it via **Settings → Devices & Services → Add Integration → Shelly Extras**.

## Local development & debugging

This repo is developed alongside the sibling integrations in this workspace.
See the shared `../dev/` Docker environment for running Home Assistant with all
integrations mounted and `debugpy` remote debugging enabled. See
[../dev/README.md](../dev/README.md).

## License

[MIT](LICENSE)
