# Poco — Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

A Home Assistant custom component for the **Poco** lighting controller by Lumitec.

Exposes each Poco external switch as a `light` entity with full on/off, brightness, and HS colour support. Uses the WebSocket push channel for real-time state updates and falls back to HTTP polling if the WebSocket is unavailable.

---

## Features

- Auto-discovers switches via the local HTTP API
- **WebSocket push** (typ:3 broadcasts) for instant state updates — no lag between a physical button press and the HA UI
- **WebSocket commands** (typ:1/4) on firmware ≥ v3.4.0 WS extension — commands get an immediate response from the device
- Graceful degradation: if WS is unavailable the integration falls back to 30-second HTTP polling; WS reconnects automatically in the background
- Config flow UI — no YAML required
- One HA `light` entity per switch (supports `ColorMode.HS` or `ColorMode.BRIGHTNESS` depending on hardware)

---

## Requirements

| Requirement | Minimum version |
|---|---|
| Home Assistant | 2024.1.0 |
| Poco firmware | v3.4.0 (HTTP API) |
| Poco firmware (WS commands) | v3.4.0 WS extension |

---

## Installation

### Via HACS (recommended)

1. In HACS, go to **Integrations → ⋮ → Custom repositories**.
2. Add this repository URL with category **Integration**.
3. Search for **Poco** and click **Download**.
4. Restart Home Assistant.

### Manual

1. Copy the `custom_components/poco/` folder from this repository into your HA
   `<config>/custom_components/poco/` directory.
2. Restart Home Assistant.

---

## Configuration

After restarting:

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **Poco**.
3. Enter the hostname or IP address of your Poco controller (e.g. `poco.local` or `192.168.1.100`).
4. Select the switches you want to expose as lights.
5. Click **Submit**.

The integration will appear under your device list and the selected switches will be available as light entities.

---

## Finding the switch ID

If you are unsure which switch IDs exist on your device you can query the API directly:

```bash
curl -s "http://poco.local/v3/extsw?q=1" | python3 -m json.tool
```

The `id` field in each `extsw` array entry is the switch identifier used during setup.

---

## API overview

The component uses the Poco HTTP REST API (v3.4.0):

```
GET http://{host}/v3/extsw?q=1[&id=N][&act=N][&hue=N][&sat=N][&bright=N]
```

| Action | `act` value |
|---|---|
| Query state | 0 |
| Turn off | 1 |
| Turn on | 2 |
| Set brightness (T2B) | 10 |
| Set hue + sat + brightness (T2HSB) | 8 |
| Set hue + sat (T2HS) | 9 |

**Colour scale:** Poco uses 0–255 for both hue and saturation. HA uses 0–360° for hue and 0–100% for saturation. The component converts automatically.

WebSocket endpoint: `ws://{host}/websocket/ws.cgi`

| Message type | Direction | Meaning |
|---|---|---|
| `typ:0` | server→client | Heartbeat |
| `typ:1` | client→server | Command (WS extension, firmware ≥ v3.4.0 WS) |
| `typ:2` | server→client | Config changed |
| `typ:3` | server→client | State changed (broadcast) |
| `typ:4` | server→client | Command response |

---

## Known limitations

- The Poco firmware field for available actions is named `acts` (array of integers) in the actual firmware but `act` (array of objects) in the v3.3.0 API spec. This component ignores the `acts`/`act` field and relies on the other state fields (`state`, `bright`, `hue`, `sat`).
- Multi-switch commands (e.g. using `ids` instead of `id`) are not yet exposed in the HA UI, but the coordinator's `async_send_action` method supports arbitrary query parameters if you extend the component.
- HACS auto-update requires the repository to be hosted on GitHub with tagged releases. Tag releases with [semantic versioning](https://semver.org/) (e.g. `v0.1.0`) and create a GitHub Release for each version.

---

## Development

```bash
# Clone the repo alongside your HA config directory
git clone https://github.com/YOUR_USERNAME/poco-ha.git

# Symlink the component into HA for live development
ln -s /path/to/poco-ha/custom_components/poco \
      /path/to/homeassistant/custom_components/poco
```

Changes to Python files take effect after restarting HA (or reloading the integration from the UI where supported).

---

## License

MIT — see [LICENSE](LICENSE).
