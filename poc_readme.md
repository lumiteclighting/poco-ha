---
title: "Poco Home Assistant PoC Integration Example"
author: [Lumitec]
date: "2026-04-09"
version: "1.0"
keywords: [Lumitec, Poco, Lighting, HomeAssistant, HASS, HTTP, Integration]
---
# Poco — Home Assistant PoC Integration

This is a proof-of-concept example using only built-in HA components. For a complete custom integration, see: https://github.com/lumiteclighting/poco-ha

Exposes a Poco external switch as a `light` entity in Home Assistant with
on/off, brightness (T2B), and full HS color (T2HSB) support.  State
(on/off, brightness, hue, saturation) is read back from the device on every
poll and immediately after every command.

**Firmware requirement:** Poco v3.4.0+ (adds `bright`/`hue`/`sat`/`pid` to
the REST response).

---

## What is installed

This PoC requires no add-ons or custom components.  It uses three built-in
HA platforms configured entirely in YAML:

| Platform | Role |
|---|---|
| `rest` sensor | Polls `GET /v3/extsw?q=1&id=<N>` every 30 s; exposes `state`, `bright`, `hue`, `sat`, `pid` |
| `rest_command` | Four services: on, off, brightness (T2B), color+brightness (T2HSB) |
| `template` light | Wraps the sensor + services into a single `light.<name>` entity |

**Limitation:** state is refreshed by polling (30 s) plus one forced re-poll
after each command.  The custom component (Phase 2) replaces polling with
WebSocket push notifications.

---

## Prerequisites

- Home Assistant 2022.x or later
- Poco device on the same LAN as HA (mDNS `poco-ABCD.local` or a static IP)
- Poco firmware v3.4.0+

Verify reachability from the HA host:

```bash
curl "http://<host>/v3/extsw?q=1"
```

The response should include `bright`, `hue`, `sat`, `pid` fields.  If not,
update the firmware first.

---

## Setup

### Step 1 — Find your switch ID

```bash
curl "http://<host>/v3/extsw?q=1"
```

Note the `id` field in the `extsw` array for the switch you want to control.

### Step 2 — Add to `secrets.yaml`

Replace `<host>` with your device hostname or IP, and `<id>` with the switch
ID from Step 1.

```yaml
# secrets.yaml
poco_extsw_url:          "http://<host>/v3/extsw?q=1&id=<id>"
poco_sw1_on_url:         "http://<host>/v3/extsw?q=1&id=<id>&act=2"
poco_sw1_off_url:        "http://<host>/v3/extsw?q=1&id=<id>&act=1"
poco_sw1_brightness_url: "http://<host>/v3/extsw?q=1&id=<id>&act=10&bright={{ bright }}"
poco_sw1_hsb_url:        "http://<host>/v3/extsw?q=1&id=<id>&act=8&hue={{ hue }}&sat={{ sat }}&bright={{ bright }}"
```

### Step 3 — Add to `configuration.yaml`

Append the following three blocks.  If you already have a `logger:`,
`rest:`, or `template:` section, merge carefully — do not duplicate keys.

```yaml
logger:
  default: warning
  logs:
    homeassistant.components.rest_command: debug   # remove when verified
    homeassistant.components.rest: debug           # remove when verified

rest:
  - resource: !secret poco_extsw_url
    scan_interval: 30
    sensor:
      - name: "Poco SW1 Raw"
        value_template: "{{ value_json.extsw[0].state }}"
        json_attributes_path: "$.extsw[0]"
        json_attributes:
          - bright
          - hue
          - sat
          - pid

rest_command:
  poco_sw1_on:
    url: !secret poco_sw1_on_url
    method: get
  poco_sw1_off:
    url: !secret poco_sw1_off_url
    method: get
  poco_sw1_brightness:
    url: !secret poco_sw1_brightness_url
    method: get
  poco_sw1_hsb:
    url: !secret poco_sw1_hsb_url
    method: get

# Color scale:  Poco hue/sat 0-255  ↔  HA hue 0-360° / sat 0-100%
template:
  - light:
      - name: "Poco SW1"
        unique_id: poco_sw1_light
        state: >
          {{ states('sensor.poco_sw1_raw') | int(0) != 0 }}
        level: >
          {% set b = state_attr('sensor.poco_sw1_raw', 'bright') | int(-1) %}
          {{ b if b >= 0 else none }}
        hs: >
          {% set h = state_attr('sensor.poco_sw1_raw', 'hue') | int(-1) %}
          {% set s = state_attr('sensor.poco_sw1_raw', 'sat') | int(-1) %}
          {% if h >= 0 and s >= 0 %}
            {{ (h * 360 / 255) | round(1), (s * 100 / 255) | round(1) }}
          {% else %}
            {{ none }}
          {% endif %}
        turn_on:
          - action: rest_command.poco_sw1_on
          - action: homeassistant.update_entity
            target:
              entity_id: sensor.poco_sw1_raw
        turn_off:
          - action: rest_command.poco_sw1_off
          - action: homeassistant.update_entity
            target:
              entity_id: sensor.poco_sw1_raw
        set_level:
          - action: rest_command.poco_sw1_brightness
            data:
              bright: "{{ brightness | int }}"
          - action: homeassistant.update_entity
            target:
              entity_id: sensor.poco_sw1_raw
        set_hs:
          - choose:
              - conditions:
                  - condition: template
                    value_template: "{{ brightness is defined }}"
                sequence:
                  - action: rest_command.poco_sw1_hsb
                    data:
                      hue: "{{ (h * 255 / 360) | round(0) | int }}"
                      sat: "{{ (s * 255 / 100) | round(0) | int }}"
                      bright: "{{ brightness | int }}"
            default:
              - action: rest_command.poco_sw1_hsb
                data:
                  hue: "{{ (h * 255 / 360) | round(0) | int }}"
                  sat: "{{ (s * 255 / 100) | round(0) | int }}"
                  bright: >
                    {% set b = state_attr('sensor.poco_sw1_raw', 'bright') | int(-1) %}
                    {{ b if b > 0 else 255 }}
              - action: homeassistant.update_entity
                target:
                  entity_id: sensor.poco_sw1_raw
```

### Step 4 — Reload

Developer Tools → YAML:
1. **Check Configuration** — must show no errors
2. **REST entities** — loads the sensor and rest_commands
3. **Template entities** — loads the light

### Step 5 — Verify

| Check | Where |
|---|---|
| `sensor.poco_sw1_raw` appears with numeric state | Developer Tools → States |
| `sensor.poco_sw1_raw` has attributes `bright`, `hue`, `sat`, `pid` | States → click entity |
| `light.poco_sw1` appears and reflects device on/off state | States or Lovelace |
| Toggle on/off from UI → hardware responds | Lovelace light card |
| Drag brightness slider → hardware dims, state updates | Lovelace light card |

---

## Multiple switches

Duplicate the entire `rest:` sensor block, all five `secrets.yaml` entries,
all four `rest_command:` entries, and the `template:` light block — replacing
`sw1` with `sw2` (etc.) and updating the `id=` parameter in each URL.

---

## Troubleshooting

**`sensor.poco_sw1_raw` is `unavailable`**
Run `curl "http://<host>/v3/extsw?q=1&id=<id>"` from the HA host to
verify network reachability.

**State does not update after command**
The debug logger lines in Step 3 will show the exact URL sent and the HTTP
response code.  Settings → System → Logs → filter for `rest_command`.

**`bright`/`hue`/`sat` attributes missing**
The device is running firmware older than v3.4.0.  Update the firmware.

**`light.poco_sw1` always shows `unknown` brightness**
`bright=-1` means the device has not received a brightness command since
last power-on.  Send any brightness or color command once to initialize it.

---

## Known limitations

- Entities appear in the **Entities** list only, not as a Device.
- State refreshes every 30 s (plus immediately after commands).  For
  real-time push updates, use the custom component (Phase 2).
- One switch per block.  Multi-switch requires duplicating YAML blocks.
- Color mode is fixed to HS.  Dimmer-only switches (hue=-1) will show a
  color picker that has no effect on the hardware.
