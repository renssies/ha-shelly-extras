# Shelly Extras

Companion integration that adds extra **actions** (services) on top of the core Home Assistant Shelly integration.

## Actions

### `shelly_extras.change_light`

Changes a Shelly light's **brightness, color, or color temperature without
changing its power state** — the piece `light.turn_on` can't do, since setting
any property there always powers the light on.

- **Drop-in replacement for `light.turn_on`.** The fields have the same names,
  selectors, and capability filters, so you can swap `light.turn_on` for
  `shelly_extras.change_light` and keep the same `data:` block.
- **Fields that don't apply are hidden**, exactly like `light.turn_on`: a
  brightness-only light shows no color fields; a light without color-temperature
  support hides that field. (Driven by each light's `supported_color_modes`.)
- Works on lights already configured through the **core Shelly integration**
  (both Gen2+ RPC devices and Gen1 block devices).
- Uses the same **target picker as `light.turn_on`** — pick a single light, a
  device, an area, or a label. The picker is restricted to Shelly lights.
- If a light is **off it stays off**; the Shelly device stores the new values
  and applies them the next time it turns on. If it's on, the change is applied
  live.
- Only properties the target light supports are sent; unsupported ones are
  skipped with a warning.

**Fields** (all named as in `light.turn_on`): `brightness` (0-255) or
`brightness_pct` (0-100); `color_temp_kelvin` or `color_temp` (mireds);
`rgb_color`, `rgbw_color`, `rgbww_color`, `hs_color`, `xy_color`, `color_name`
(all normalized to what the device supports); and `transition` (seconds).

> The action id is `shelly_extras.change_light` — the first part is this
> integration's domain, which is what makes its field definitions and filters
> load. It can't be registered under the core `shelly` domain without losing them.

Example:

```yaml
action: shelly_extras.change_light
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
