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
- Monitor index correlation between Windows API and DDC/CI enumeration may differ
- Some monitors don't report model name in capabilities string
- USB-C/Thunderbolt connections may not support DDC/CI

## Troubleshooting

- **Toggle doesn't work**: Check DDC/CI is enabled in monitor OSD menu
- **Wrong monitor toggles**: Index mismatch — try different monitor
- **"No monitors found"**: Verify cable supports DDC/CI (DP/HDMI work, some adapters don't)
- **Slow startup**: Normal — DDC/CI enumeration is inherently slow, cached names help
