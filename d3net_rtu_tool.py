#!/usr/bin/env python3
"""CLI tool for Daikin DTA116A51 over Modbus RTU (RS485 USB adapters)."""

from __future__ import annotations

import argparse
import glob
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parent
D3NET_PYTHON_LIB = REPO_ROOT / "custom_components" / "daikin_d3net"
if str(D3NET_PYTHON_LIB) not in sys.path:
    sys.path.insert(0, str(D3NET_PYTHON_LIB))

try:
    from d3net.const import D3netFanDirection, D3netFanSpeed, D3netOperationMode
    from d3net.encoding import SystemStatus, UnitCapability, UnitError, UnitHolding, UnitStatus
except ModuleNotFoundError:
    from enum import Enum

    class D3netOperationMode(Enum):
        FAN = 0
        HEAT = 1
        COOL = 2
        AUTO = 3
        VENT = 4
        UNDEFINED = 5
        SLAVE = 6
        DRY = 7

    class D3netFanSpeed(Enum):
        Auto = 0
        Low = 1
        LowMedium = 2
        Medium = 3
        HighMedium = 4
        High = 5

    class D3netFanDirection(Enum):
        P0 = 0
        P1 = 1
        P2 = 2
        P3 = 3
        P4 = 4
        Stop = 6
        Swing = 7

    class _InputBase:
        ADDRESS = None
        COUNT = None

        def __init__(self, registers: list[int]) -> None:
            self._registers = registers
            self._dirty = False

        def _bit(self, bit: int, value: bool | None = None):
            register = int(bit / 16)
            mask = 1 << (bit % 16)
            current = self._registers[register] & mask > 0
            if value is None or value == current:
                return current
            self._registers[register] += mask * (1 if value else -1)
            self._dirty = True
            return value

        def _decode_bit_array(self, start: int, length: int):
            return [self._bit(x) for x in range(start, start + length)]

        def _decode_bit(self, start: int) -> bool:
            return self._bit(start)

        def _decode_uint(self, start: int, length: int) -> int:
            result: int = 0
            for bit in range(length):
                if self._bit(start + bit):
                    result += 1 << bit
            return result

        def _decode_sint(self, start: int, length: int) -> int:
            result = self._decode_uint(start, length - 1)
            if self._bit(start + length - 1):
                result = 0 - result
            return result

        def _encode_bit(self, start: int, value: bool):
            self._bit(start, value)

        def _encode_uint(self, start: int, length: int, value: int):
            for bit in range(length):
                self._bit(start + bit, (value & 1 << bit) > 0)

        def _encode_sint(self, start: int, length: int, value: int):
            self._encode_uint(start, length - 1, abs(value))
            self._encode_bit(start + length - 1, value < 0)

    class SystemStatus(_InputBase):
        ADDRESS = 0
        COUNT = 9

        @property
        def initialised(self) -> bool:
            return self._decode_bit(0)

        @property
        def other_device_exists(self) -> bool:
            return self._decode_bit(1)

        @property
        def units_connected(self):
            return self._decode_bit_array(16, 64)

        @property
        def units_error(self):
            return self._decode_bit_array(80, 64)

    class UnitCapability(_InputBase):
        ADDRESS = 1000
        COUNT = 3

        @property
        def fan_mode_capable(self) -> bool:
            return self._decode_bit(0)

        @property
        def cool_mode_capable(self) -> bool:
            return self._decode_bit(1)

        @property
        def heat_mode_capable(self) -> bool:
            return self._decode_bit(2)

        @property
        def auto_mode_capable(self) -> bool:
            return self._decode_bit(3)

        @property
        def dry_mode_capable(self) -> bool:
            return self._decode_bit(4)

    class UnitStatus(_InputBase):
        ADDRESS = 2000
        COUNT = 6

        @property
        def power(self) -> bool:
            return self._decode_bit(0)

        @property
        def thermo(self) -> bool:
            return self._decode_bit(7)

        @property
        def heat(self) -> bool:
            return self._decode_bit(6)

        @property
        def defrost(self) -> bool:
            return self._decode_bit(29)

        @property
        def filter_warning(self) -> bool:
            return self._decode_uint(20, 4) != 0

        @property
        def fan_direct(self) -> D3netFanDirection:
            return D3netFanDirection(self._decode_uint(8, 3))

        @property
        def fan_speed(self) -> D3netFanSpeed:
            return D3netFanSpeed(self._decode_uint(12, 3))

        @property
        def operating_mode(self) -> D3netOperationMode:
            return D3netOperationMode(self._decode_uint(16, 4))

        @property
        def operating_current(self) -> D3netOperationMode:
            return D3netOperationMode(self._decode_uint(24, 4))

        @property
        def temp_setpoint(self) -> float:
            return self._decode_sint(32, 16) / 10

        @property
        def temp_current(self) -> float:
            return self._decode_sint(64, 16) / 10

    class UnitError(_InputBase):
        ADDRESS = 3600
        COUNT = 2

        @property
        def error_code(self) -> str:
            return chr(self._decode_uint(0, 8)) + chr(self._decode_uint(8, 8))

        @property
        def error_sub_code(self) -> int:
            return self._decode_uint(16, 6)

        @property
        def error(self) -> int:
            return self._decode_bit(24)

        @property
        def alarm(self) -> int:
            return self._decode_bit(25)

        @property
        def warning(self) -> int:
            return self._decode_bit(26)

        @property
        def error_unit_number(self) -> int:
            return self._decode_uint(28, 4)

    class UnitHolding(_InputBase):
        ADDRESS = 2000
        COUNT = 3

        @property
        def dirty(self) -> bool:
            return self._dirty

        @property
        def registers(self) -> list[int]:
            return self._registers

        @property
        def power(self) -> bool:
            return self._decode_bit(0)

        @power.setter
        def power(self, state: bool):
            self._encode_bit(0, state)

        @property
        def fan_direct(self) -> D3netFanDirection:
            return D3netFanDirection(self._decode_uint(8, 3))

        @fan_direct.setter
        def fan_direct(self, direct: D3netFanDirection):
            self._encode_uint(8, 3, direct.value)
            self.fan_control = True

        @property
        def fan_speed(self) -> D3netFanSpeed:
            return D3netFanSpeed(self._decode_uint(12, 3))

        @fan_speed.setter
        def fan_speed(self, speed: D3netFanSpeed):
            self._encode_uint(12, 3, speed.value)
            self.fan_control = True

        @property
        def fan_control(self) -> bool:
            return self._decode_uint(4, 4) == 6

        @fan_control.setter
        def fan_control(self, enabled: bool):
            self._encode_uint(4, 4, 6 if enabled else 0)

        @property
        def operating_mode(self):
            return D3netOperationMode(self._decode_uint(16, 4))

        @operating_mode.setter
        def operating_mode(self, mode: D3netOperationMode):
            self._encode_uint(16, 4, mode.value)

        @property
        def temp_setpoint(self) -> float:
            return self._decode_sint(32, 16) / 10

        @temp_setpoint.setter
        def temp_setpoint(self, setpoint: float):
            self._encode_sint(32, 16, int(setpoint * 10))

        @property
        def filter_reset(self) -> bool:
            return self._decode_uint(20, 4) != 0

        @filter_reset.setter
        def filter_reset(self, state: bool):
            self._encode_uint(20, 4, 15 if state else 0)


@dataclass(frozen=True)
class RtuConfig:
    port: str
    baudrate: int
    bytesize: int
    parity: str
    stopbits: int
    timeout: float
    slave: int


def _build_client(cfg: RtuConfig):
    from pymodbus.client import ModbusSerialClient

    return ModbusSerialClient(
        port=cfg.port,
        baudrate=cfg.baudrate,
        bytesize=cfg.bytesize,
        parity=cfg.parity,
        stopbits=cfg.stopbits,
        timeout=cfg.timeout,
    )


def _read_input(client: Any, address: int, count: int, slave: int) -> list[int]:
    response = client.read_input_registers(address=address, count=count, slave=slave)
    if response.isError():
        raise RuntimeError(f"read_input_registers failed at {address} ({response})")
    return response.registers


def _read_holding(client: Any, address: int, count: int, slave: int) -> list[int]:
    response = client.read_holding_registers(address=address, count=count, slave=slave)
    if response.isError():
        raise RuntimeError(f"read_holding_registers failed at {address} ({response})")
    return response.registers


def _write_holding(client: Any, address: int, values: list[int], slave: int) -> None:
    response = client.write_registers(address=address, values=values, slave=slave)
    if response.isError():
        raise RuntimeError(f"write_registers failed at {address} ({response})")


def _unit_id(index: int) -> str:
    return f"{int(index / 16 + 1)}-{index % 16:02d}"


def _connect_or_fail(client: Any, port: str) -> None:
    if not client.connect():
        raise RuntimeError(
            f"Unable to connect to serial adapter on '{port}'. Check --port, cabling, and adapter permissions."
        )


def _enum_names(enum_cls: type) -> list[str]:
    return [member.name.lower() for member in enum_cls]


def _parse_enum(enum_cls: type, text: str):
    normalized = text.strip().lower().replace("-", "")
    for member in enum_cls:
        if member.name.lower().replace("_", "") == normalized:
            return member
    choices = ", ".join(_enum_names(enum_cls))
    raise argparse.ArgumentTypeError(f"Unknown value '{text}'. Valid values: {choices}")


def _list_candidate_ports() -> list[str]:
    candidates: list[str] = []
    for pattern in ("/dev/ttyUSB*", "/dev/ttyACM*", "/dev/serial/by-id/*"):
        candidates.extend(sorted(glob.glob(pattern)))
    return candidates


def _list_ports() -> None:
    candidates = _list_candidate_ports()
    if not candidates:
        print("No serial ports auto-detected. On Windows this detection is limited; use --port COMx manually.")
        return

    print("Candidate serial ports:")
    for port in candidates:
        print(f"- {port}")


def _scan_units(client: Any, cfg: RtuConfig, verbose: bool) -> list[int]:
    system = SystemStatus(_read_input(client, SystemStatus.ADDRESS, SystemStatus.COUNT, cfg.slave))

    print(f"Initialised: {system.initialised}")
    print(f"Other DIII devices: {system.other_device_exists}")

    found: list[int] = []
    for index, connected in enumerate(system.units_connected):
        if not connected or system.units_error[index]:
            continue
        found.append(index)

    print(f"\nFound {len(found)} healthy unit(s):")
    for index in found:
        print(f"- idx={index:02d} id={_unit_id(index)}")
        if verbose:
            capability = UnitCapability(
                _read_input(
                    client,
                    UnitCapability.ADDRESS + index * UnitCapability.COUNT,
                    UnitCapability.COUNT,
                    cfg.slave,
                )
            )
            status = UnitStatus(
                _read_input(
                    client,
                    UnitStatus.ADDRESS + index * UnitStatus.COUNT,
                    UnitStatus.COUNT,
                    cfg.slave,
                )
            )
            print(
                f"  mode={status.operating_mode.name} power={status.power} "
                f"setpoint={status.temp_setpoint:.1f}°C room={status.temp_current:.1f}°C "
                f"fan={status.fan_speed.name}/{status.fan_direct.name} "
                f"cap_modes={{cool:{capability.cool_mode_capable}, heat:{capability.heat_mode_capable}, auto:{capability.auto_mode_capable}, dry:{capability.dry_mode_capable}, fan:{capability.fan_mode_capable}}}"
            )

    return found


def _show_status(client: Any, cfg: RtuConfig, units: Iterable[int]) -> None:
    for index in units:
        status = UnitStatus(
            _read_input(
                client,
                UnitStatus.ADDRESS + index * UnitStatus.COUNT,
                UnitStatus.COUNT,
                cfg.slave,
            )
        )
        print(
            f"idx={index:02d} id={_unit_id(index)} power={status.power} "
            f"mode={status.operating_mode.name} current_mode={status.operating_current.name} "
            f"setpoint={status.temp_setpoint:.1f}°C room={status.temp_current:.1f}°C "
            f"fan_speed={status.fan_speed.name} fan_dir={status.fan_direct.name} "
            f"thermo={status.thermo} heat={status.heat} defrost={status.defrost} filter_warning={status.filter_warning}"
        )


def _show_errors(client: Any, cfg: RtuConfig, units: Iterable[int], show_clear: bool) -> None:
    has_any = False
    for index in units:
        error = UnitError(
            _read_input(
                client,
                UnitError.ADDRESS + index * UnitError.COUNT,
                UnitError.COUNT,
                cfg.slave,
            )
        )
        if not show_clear and not (error.error or error.alarm or error.warning):
            continue
        has_any = True
        print(
            f"idx={index:02d} id={_unit_id(index)} "
            f"error={bool(error.error)} alarm={bool(error.alarm)} warning={bool(error.warning)} "
            f"code={error.error_code} sub={error.error_sub_code} src_unit={error.error_unit_number}"
        )

    if not has_any:
        print("No active errors/alarms/warnings.")


def _control_unit(client: Any, cfg: RtuConfig, args: argparse.Namespace) -> None:
    index = args.unit
    holding = UnitHolding(
        _read_holding(
            client,
            UnitHolding.ADDRESS + index * UnitHolding.COUNT,
            UnitHolding.COUNT,
            cfg.slave,
        )
    )

    changes = []
    if args.power is not None:
        holding.power = args.power == "on"
        changes.append(f"power={args.power}")
    if args.mode is not None:
        holding.operating_mode = args.mode
        changes.append(f"mode={args.mode.name}")
    if args.setpoint is not None:
        holding.temp_setpoint = args.setpoint
        changes.append(f"setpoint={args.setpoint:.1f}")
    if args.fan_speed is not None:
        holding.fan_speed = args.fan_speed
        changes.append(f"fan_speed={args.fan_speed.name}")
    if args.fan_direction is not None:
        holding.fan_direct = args.fan_direction
        changes.append(f"fan_direction={args.fan_direction.name}")
    if args.filter_reset:
        holding.filter_reset = True
        changes.append("filter_reset=true")

    if not holding.dirty:
        raise RuntimeError("No writable fields were changed. Provide at least one control option.")

    _write_holding(
        client,
        UnitHolding.ADDRESS + index * UnitHolding.COUNT,
        holding.registers,
        cfg.slave,
    )

    if args.filter_reset:
        holding.filter_reset = False
        if holding.dirty:
            _write_holding(
                client,
                UnitHolding.ADDRESS + index * UnitHolding.COUNT,
                holding.registers,
                cfg.slave,
            )

    print(f"Updated idx={index:02d} id={_unit_id(index)} with: {', '.join(changes)}")


def _watch(client: Any, cfg: RtuConfig, args: argparse.Namespace) -> None:
    output = Path(args.out) if args.out else None
    iterations = None if args.duration <= 0 else int(args.duration / args.interval)

    start = time.time()
    tick = 0
    while iterations is None or tick <= iterations:
        now = datetime.now(timezone.utc).isoformat()
        status = UnitStatus(
            _read_input(
                client,
                UnitStatus.ADDRESS + args.unit * UnitStatus.COUNT,
                UnitStatus.COUNT,
                cfg.slave,
            )
        )
        error = UnitError(
            _read_input(
                client,
                UnitError.ADDRESS + args.unit * UnitError.COUNT,
                UnitError.COUNT,
                cfg.slave,
            )
        )

        row = {
            "ts": now,
            "unit_index": args.unit,
            "unit_id": _unit_id(args.unit),
            "power": status.power,
            "mode": status.operating_mode.name,
            "setpoint": status.temp_setpoint,
            "room_temp": status.temp_current,
            "fan_speed": status.fan_speed.name,
            "fan_direction": status.fan_direct.name,
            "error": bool(error.error),
            "alarm": bool(error.alarm),
            "warning": bool(error.warning),
            "error_code": error.error_code,
            "error_sub_code": error.error_sub_code,
        }

        print(json.dumps(row, separators=(",", ":")))
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("a", encoding="utf-8") as file_handle:
                file_handle.write(json.dumps(row) + "\n")

        tick += 1
        if iterations is not None and tick > iterations:
            break
        time.sleep(args.interval)

    elapsed = time.time() - start
    print(f"Finished watch after {elapsed:.1f}s")


def _resolve_targets(client: Any, cfg: RtuConfig, args: argparse.Namespace) -> list[int]:
    targets = args.unit
    if getattr(args, "all", False):
        targets = _scan_units(client, cfg, verbose=False)
        print()

    if not targets:
        raise RuntimeError("No units selected. Pass --unit or use --all.")
    return targets


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Daikin DTA116A51 Modbus RTU utility over USB-RS485 adapters.",
    )
    parser.add_argument("--port", help="Serial port, e.g. /dev/ttyUSB0 or COM4")
    parser.add_argument("--baudrate", type=int, default=9600)
    parser.add_argument("--bytesize", type=int, choices=[7, 8], default=8)
    parser.add_argument("--parity", choices=["N", "E", "O"], default="E")
    parser.add_argument("--stopbits", type=int, choices=[1, 2], default=1)
    parser.add_argument("--timeout", type=float, default=1.0, help="Serial timeout in seconds")
    parser.add_argument("--slave", type=int, default=1, help="Modbus slave id on DTA adapter")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ports", help="List likely serial ports on this machine")

    scan = sub.add_parser("scan", help="Discover connected HVAC units")
    scan.add_argument("--verbose", action="store_true", help="Also read status/capability details")

    status = sub.add_parser("status", help="Read live status")
    status.add_argument("--unit", type=int, action="append", help="Unit index (repeat for multiple)")
    status.add_argument("--all", action="store_true", help="Read every unit reported by scan")

    errors = sub.add_parser("errors", help="Read error/alarm/warning registers")
    errors.add_argument("--unit", type=int, action="append", help="Unit index (repeat for multiple)")
    errors.add_argument("--all", action="store_true", help="Read every unit reported by scan")
    errors.add_argument("--show-clear", action="store_true", help="Show units even without active faults")

    control = sub.add_parser("control", help="Control one unit (power/mode/setpoint/fan)")
    control.add_argument("--unit", required=True, type=int, help="Unit index from scan")
    control.add_argument("--power", choices=["on", "off"])
    control.add_argument("--mode", type=lambda x: _parse_enum(D3netOperationMode, x))
    control.add_argument("--setpoint", type=float, help="Setpoint in Celsius")
    control.add_argument("--fan-speed", dest="fan_speed", type=lambda x: _parse_enum(D3netFanSpeed, x))
    control.add_argument(
        "--fan-direction",
        dest="fan_direction",
        type=lambda x: _parse_enum(D3netFanDirection, x),
    )
    control.add_argument("--filter-reset", action="store_true", help="Trigger filter reset pulse")

    watch = sub.add_parser("watch", help="Poll one unit and print JSONL style logs")
    watch.add_argument("--unit", required=True, type=int)
    watch.add_argument("--interval", type=float, default=5.0, help="Seconds between polls")
    watch.add_argument(
        "--duration",
        type=float,
        default=60.0,
        help="Total watch duration in seconds (<=0 means forever)",
    )
    watch.add_argument("--out", help="Optional JSONL file to append watch logs")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "ports":
        _list_ports()
        return 0

    if not args.port:
        parser.error("--port is required for this command")

    cfg = RtuConfig(
        port=args.port,
        baudrate=args.baudrate,
        bytesize=args.bytesize,
        parity=args.parity,
        stopbits=args.stopbits,
        timeout=args.timeout,
        slave=args.slave,
    )

    client = None
    try:
        client = _build_client(cfg)
        _connect_or_fail(client, cfg.port)

        if args.command == "scan":
            _scan_units(client, cfg, verbose=args.verbose)
            return 0

        if args.command == "status":
            _show_status(client, cfg, _resolve_targets(client, cfg, args))
        elif args.command == "errors":
            _show_errors(client, cfg, _resolve_targets(client, cfg, args), show_clear=args.show_clear)
        elif args.command == "control":
            _control_unit(client, cfg, args)
        elif args.command == "watch":
            _watch(client, cfg, args)
        return 0
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - single CLI error path
        print(f"ERROR: {exc}", file=sys.stderr)
        if "pymodbus" in str(exc):
            print("Install dependency with: pip install pymodbus pyserial", file=sys.stderr)
        return 1
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
