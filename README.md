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

## Screens

![Integration](/images/integration.png)

![Device List](/images/devices.png)

![Device Details](/images/device.png)

## Hardware

[Example DIY hardware implementation](hardware.md)
