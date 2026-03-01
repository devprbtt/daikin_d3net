# daikin_d3net

## Overview
Home Assistant Daikin DIII-Net Modbus Integration.

Home Assistant custom component to integrate with the Daikin DTA116A51 DIII-Net/Modbus Adapter.

Developed against a VRV IV-S system, DTA116A51 and Modbus RTU/TCP gateway. Currently only supports communication over Modbus TCP. No current support for hot water functions. Unfortunately the DCPA01 is not supported and no documentation is available.

Enumerates units attached to DIII-Net bus, provides Climate entities for each.

## Installation
Install with [HACS](https://hacs.xyz), currently as a custom repository by manually adding this repository or with the link below

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=martinstafford&repository=daikin_d3net&category=integration)

OR

Download the [latest release](https://github.com/martinstafford/daikin_d3net/releases) and place the content in the Home Assistant `config/custom_components/daikin_d3net` folder.

After rebooting Home Assistant, this integration can be configured through the integration setup UI.

## Communication Specification

Communication details are based on the [Daikin Design Guide Modbus Interface DIII](https://www.daikin-ce.com/content/dam/document-library/Installer-reference-guide/ac/vrv/ekmbdxb/EKMBDXB_Design%20guide_4PEN642495-1A_English.pdf).

## Direct RS485 CLI Tool

This repo now includes `d3net_rtu_tool.py`, a standalone Python CLI for talking directly to a DTA116A51 through a USB-RS485 adapter.

### Install dependency

```bash
pip install pymodbus pyserial
```

### Typical workflow

0. Find your serial device first:

```bash
python d3net_rtu_tool.py ports
```

1. Scan for indoor units:

```bash
python d3net_rtu_tool.py --port /dev/ttyUSB0 scan --verbose
```

2. Read status for all discovered units:

```bash
python d3net_rtu_tool.py --port /dev/ttyUSB0 status --all
```

3. Show active errors/alarms/warnings:

```bash
python d3net_rtu_tool.py --port /dev/ttyUSB0 errors --all
```

4. Control a unit (example: unit index `3`):

```bash
python d3net_rtu_tool.py --port /dev/ttyUSB0 control --unit 3 --power on --mode cool --setpoint 23.0 --fan-speed medium
```

5. Watch one unit and save JSONL logs:

```bash
python d3net_rtu_tool.py --port /dev/ttyUSB0 watch --unit 3 --interval 5 --duration 300 --out ./logs/unit3.jsonl
```

Run full help:

```bash
python d3net_rtu_tool.py --help
```


### USB-RS485 adapter notes (FT232RL modules)

Your FT232RL USB-RS485 adapter type is compatible with this tool.

- Connect adapter `A/+` to DTA `D1/+` and adapter `B/-` to DTA `D0/-` (naming can vary by board, keep polarity consistent).
- If scanning fails, swap A/B once (some sellers label terminals in reverse).
- DTA defaults are typically `9600`, `8`, `E`, `1`, slave `1`.
- Linux users may need serial permission (`dialout` group).

Example with explicit serial settings:

```bash
python d3net_rtu_tool.py --port /dev/ttyUSB0 --baudrate 9600 --bytesize 8 --parity E --stopbits 1 --slave 1 scan --verbose
```

### Desktop UI (GUI)

If you prefer a UI instead of CLI, run:

```bash
python d3net_rtu_gui.py
```

The UI includes:

- serial setup and port discovery
- unit scan
- status reads
- error/alert reads
- control writes (power/mode/setpoint/fan/filter reset)
- live watch/logging with optional JSONL output file

### Build executable

This repository includes `build_executable.sh` to package the GUI into a standalone executable using PyInstaller:

```bash
./build_executable.sh
```

Output binary will be created at:

```bash
dist/d3net_rtu_gui
```

## RNET Keypad/Gateway Sniffing Notes (Feb 2026)

- Detailed Roehn Wizard protocol map from decompiled sources:
  - [roehn_wizard_protocol_map.md](roehn_wizard_protocol_map.md)


- Physical: RS‑485 on RNET A/B; 24 V on +/– (adapter must only touch A/B).
- Serial: 19200 baud, 8N1, CRC‑16/CCITT‑FALSE over bytes after leading 0x02.

Polls / address
- 6‑byte poll: `02 <addr> 01 0e <crc_hi> <crc_lo>`; address is the second byte (e.g., 0x66 = 102).
- Button frames themselves do not carry the address; they rely on the polled session.

Button frames (23 bytes)  
Format: `02 [dir] 12 0e P0 P1 P2 P3 ... CRC`  
Direction: 0x80 keypad→gateway (PRESS), 0x00 gateway→keypad (RELEASE/ack).  
Payload words that identify buttons:
- BTN1: 00 00 03 00 or 01 00 03 00
- BTN2: 00 00 0C 00 or 02 00 0C 00
- BTN3: 00 00 30 00 or 04 00 30 00
- BTN4: 00 00 C0 00 or 08 00 C0 00
Variants with mid‑bytes changing (e.g., `... 00 00 00 00 00 01 00 ...`) show up around hold/double/LED activity—still being mapped.

Other observed frames
- 5‑byte bursts like `02 64 00 da e1` coincide with LED/status traffic.
- Occasional 18‑byte frames (unmapped).

Helper scripts (repo root)
- `com_raw_live.py` — raw hex stream with timestamps.
- `com_filter_view.py` — live view with poll suppression + per‑second stats.
- `keypad_live_label.py` — live PRESS/RELEASE for BTN1–BTN4; OTHER payloads printed.
- `keypad_live_counter.py` — BTN1 press counter/logger.
- `keypad_capture_button1.py` — guided BTN1 capture window.
- `keypad_capture_sequence.py` — guided capture buttons 1→4 sequentially.
- `rnet_logger.py` — timed capture; `rnet_decode.py` — CRC framing/summary.

Roehn discovery tool
- roehn_discover.py - Roehn Wizard UDP processor discovery and module enumeration.

Roehn discovery examples
- Discover processors (broadcast on UDP 2006):
  - python roehn_discover.py discover
- Discover processors with unicast subnet sweep fallback:
  - python roehn_discover.py discover --subnet 192.168.51.0/24
- Discover with JSON output:
  - python roehn_discover.py discover --json
- Discover and save JSON to file:
  - python roehn_discover.py discover --json --out .\logs\roehn_processors.json
- Enumerate connected devices on one processor:
  - python roehn_discover.py devices 192.168.51.30
- Enumerate devices as JSON:
  - python roehn_discover.py devices 192.168.51.30 --json
- Identify module by serial (blink/beep):
  - python roehn_discover.py identify 192.168.51.30 29:11:00:09:DB:4E
- Identify module with beep disabled:
  - python roehn_discover.py identify 192.168.51.30 29:11:00:09:DB:4E --no-beep
- Query processor metadata (discovery + BIOS info):
  - python roehn_discover.py processor-info 192.168.51.30
- Query processor metadata with devices as JSON:
  - python roehn_discover.py processor-info 192.168.51.30 --with-devices --json --out .\logs\roehn_processor_info_192.168.51.30.json
- Enumerate devices and save JSON:
  - python roehn_discover.py devices 192.168.51.30 --json --out .\logs\roehn_devices_192.168.51.30.json
- Full scan (discover + device enumeration):
  - python roehn_discover.py scan-all --subnet 192.168.51.0/24 --json --out .\logs\roehn_scan_all.json

Next mapping steps
- Capture labeled press/hold/double sequences per button to lock down the OTHER variants.
- Map the 5‑byte frames to LED/status once those actions are timestamped.

## Screens

![Integration](/images/integration.png)

![Device List](/images/devices.png)

![Device Details](/images/device.png)

## Hardware

[Example DIY hardware implementation](hardware.md)
