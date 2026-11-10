# DDC/CI

## What is DDC/CI

- Display Data Channel / Command Interface
- VESA standard for bidirectional communication between PC and display
- Uses I2C protocol over the display cable (HDMI, DP, DVI, VGA)
- Allows reading/writing monitor settings (brightness, contrast, power, input source)

## VCP Code 0xD6 — Power Mode

- VCP (Virtual Control Panel) codes are the "registers" DDC/CI exposes
- Code 0xD6 controls display power state:
  - `0x01` = ON
  - `0x04` = OFF (soft standby)
  - `0x05` = OFF (hard standby)
- This app uses `PowerMode.on` (0x01) and `PowerMode.off_soft` (0x04)

## How monitorcontrol Library Works

- Python wrapper around Windows `dxva2.dll` (DirectX Video Acceleration)
- `GetPhysicalMonitorsFromHMONITOR` — gets DDC/CI handle
- `GetVCPFeatureAndVCPFeatureReply` — reads VCP values
- `SetVCPFeature` — writes VCP values
- `GetCapabilitiesStringLength` + `CapabilitiesRequestAndCapabilitiesReply` — reads capability string (contains model name)

## Limitations

- DDC/CI must be enabled in monitor's OSD settings (often disabled by default)
- Enumeration is slow (~1-3 seconds per monitor)
- Not all monitors support DDC/CI (especially older or budget models)
- Windows device interface identity is resolved to the current HMONITOR before each command; hardware is never selected by enumeration index. Missing or ambiguous physical targets are refused.
- Some monitors don't report model name in capabilities string
- USB-C/Thunderbolt connections may not support DDC/CI

## Troubleshooting

- **Toggle doesn't work**: Check DDC/CI is enabled in monitor OSD menu
- **Monitor unavailable**: Refresh or reselect its shortcut target after reconnecting it. The app deliberately refuses to guess a different target.
- **"No monitors found"**: Verify cable supports DDC/CI (DP/HDMI work, some adapters don't)
- **Slow startup**: Normal — DDC/CI enumeration is inherently slow, cached names help

## Wake and exit behavior

OFF sends `PowerMode.off_soft` once and shows OFF (REQUESTED) until a successful reading.
ON is retried with delays of 0.3, 0.6, 1.0 and 1.5 seconds; success requires a power-state reading of ON.
Native driver calls can add latency beyond these delays. There is no continuous DDC polling.

Normal Quit waits for pending commands and wakes only monitors successfully turned OFF by this session.
If ON cannot be confirmed, the app stays available and asks whether to retry, quit anyway or cancel.
Process termination, power loss and forced OS shutdown can bypass this cleanup.

Hardware check on 2026-11-07: the connected Philips secondary monitor (Windows model identifier PHLC338)
accepted OFF, reported standby (2), then returned ON (1) after repeated wake commands/readback.
This verifies that setup only; physical-button recovery may be necessary on other models.
The full application OFF → Quit → confirmed ON sequence was also verified on this setup.
