#!/usr/bin/env python3
"""Roehn Wizard UDP discovery and device enumeration tool."""

from __future__ import annotations

import argparse
import ipaddress
import json
import socket
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


HEADER = b"HSN_S-UDP"


@dataclass
class ProcessorInfo:
    source_ip: str
    name: str
    version: str = ""
    serial: str = ""
    ip: str = ""
    mask: str = ""
    gateway: str = ""
    mac: str = ""


@dataclass
class DeviceInfo:
    processor_ip: str
    port: int
    hsnet_id: int
    device_id: int
    dev_model: int
    fw: str
    model: str
    extended_model: str
    serial_hex: str
    status: int
    crc: int
    eeprom_address: int
    bitmap: int


@dataclass
class BiosInfo:
    version: str
    major_version: int
    minor_version: int
    patch_version: int
    max_modules: int = 0
    max_units: int = 0
    event_block: int = 0
    string_var_block: int = 0
    max_scripts: int = 0
    cad_scripts: int = 0
    max_procedures: int = 0
    cad_procedures: int = 0
    max_var: int = 0
    cad_var: int = 0
    max_scenes: int = 0
    cad_scenes: int = 0


def c_string(data: bytes, start: int, max_len: int | None = None) -> str:
    if start < 0 or start >= len(data):
        return ""
    end = len(data) if max_len is None else min(len(data), start + max_len)
    chunk = data[start:end]
    nul = chunk.find(b"\x00")
    if nul >= 0:
        chunk = chunk[:nul]
    return chunk.decode("ascii", errors="ignore").strip()


def build_discover_packet() -> bytes:
    return HEADER + bytes((3, 0, 0, 0))


def build_get_connected_devices_packet(read_index: int) -> bytes:
    if read_index < 0:
        read_index = 0
    return HEADER + bytes((100, 1, read_index & 0xFF, (read_index >> 8) & 0xFF, 0))


def build_get_bios_packet() -> bytes:
    return HEADER + bytes((4, 9, 0))


def parse_serial_hex(serial_text: str) -> bytes:
    tokenized = serial_text.replace("-", ":").split(":")
    if len(tokenized) != 6:
        raise ValueError("serial must have 6 bytes (format: AA:BB:CC:DD:EE:FF)")
    out = bytearray()
    for token in tokenized:
        token = token.strip()
        if len(token) == 0 or len(token) > 2:
            raise ValueError("invalid serial byte in serial string")
        out.append(int(token, 16))
    return bytes(out)


def build_identify_packet(serial: bytes, beep: bool) -> bytes:
    if len(serial) != 6:
        raise ValueError("serial must be 6 bytes")
    # Matches IdentifyModuleBySerialNumberCallObject.GetNextDataBlock()
    data = bytearray(28)
    data[0:9] = HEADER
    data[9] = 1
    data[10] = 1
    data[11] = 0
    data[12] = 16
    data[13] = 125
    data[14] = 1
    data[15] = 0xFF
    data[16] = 0
    data[17:23] = serial
    data[23] = 4
    data[24] = 238
    data[25] = 0
    data[26] = 0
    data[27] = 1 if beep else 0
    return bytes(data)


def parse_processor_response(data: bytes, source_ip: str) -> ProcessorInfo | None:
    if len(data) < 15:
        return None
    if data[:9] != HEADER:
        return None
    if data[9] != 3 or data[10] != 0:
        return None

    info = ProcessorInfo(source_ip=source_ip, name=c_string(data, 12))
    if len(data) >= 82:
        info.version = f"{data[32]}.{data[33]}.{data[34]}.{data[35]}"
        info.serial = c_string(data, 42, 16)
        info.ip = ".".join(str(x) for x in data[62:66])
        info.mask = ".".join(str(x) for x in data[66:70])
        info.gateway = ".".join(str(x) for x in data[70:74])
        info.mac = ":".join(f"{x:02X}" for x in data[74:80])
    return info


def parse_devices_response(data: bytes, source_ip: str) -> tuple[list[DeviceInfo], int, int] | None:
    if len(data) <= 22:
        return None
    if data[:9] != HEADER:
        return None
    if data[9] != 100 or data[10] != 1:
        return None

    header_len = data[12]
    register_len = data[13]
    registers_qty = data[14]
    read_index = data[16] | (data[17] << 8)

    devices: list[DeviceInfo] = []
    base = 9 + 3 + header_len
    for i in range(registers_qty):
        pos = base + i * register_len
        if pos + 40 > len(data):
            break
        serial = data[pos + 28 : pos + 34]
        d = DeviceInfo(
            processor_ip=source_ip,
            status=data[pos],
            port=data[pos + 1],
            hsnet_id=data[pos + 3] | (data[pos + 4] << 8),
            device_id=data[pos + 5] | (data[pos + 6] << 8),
            dev_model=data[pos + 7],
            fw=f"{data[pos + 8]}.{data[pos + 9]}.{data[pos + 10]}",
            model=data[pos + 11 : pos + 18].decode("ascii", errors="ignore").replace("\x00", "").strip(),
            extended_model=data[pos + 18 : pos + 28]
            .decode("ascii", errors="ignore")
            .replace("\x00", "")
            .strip(),
            serial_hex=":".join(f"{b:02X}" for b in serial),
            crc=(data[pos + 34] << 8) | data[pos + 35],
            eeprom_address=data[pos + 36] | (data[pos + 37] << 8),
            bitmap=data[pos + 38] | (data[pos + 39] << 8),
        )
        devices.append(d)
    return devices, registers_qty, read_index


def parse_bios_response(data: bytes) -> BiosInfo | None:
    if len(data) < 15:
        return None
    if data[:9] != HEADER:
        return None
    if data[9] != 4 or data[10] != 9:
        return None
    major = int(data[12])
    minor = int(data[13])
    patch = int(data[14])
    info = BiosInfo(
        version=f"{major}.{minor}.{patch}",
        major_version=major,
        minor_version=minor,
        patch_version=patch,
    )
    if len(data) >= 16:
        info.max_modules = int(data[15])
    if len(data) >= 18:
        info.max_units = int(data[16]) | (int(data[17]) << 8)
    if len(data) >= 22:
        info.event_block = int(data[20]) | (int(data[21]) << 8)
    if len(data) >= 24:
        info.string_var_block = int(data[22]) | (int(data[23]) << 8)
    if len(data) >= 28:
        info.max_scripts = int(data[26]) | (int(data[27]) << 8)
    if len(data) >= 30:
        info.cad_scripts = int(data[28]) | (int(data[29]) << 8)
    if len(data) >= 32:
        info.max_procedures = int(data[30]) | (int(data[31]) << 8)
    if len(data) >= 34:
        info.cad_procedures = int(data[32]) | (int(data[33]) << 8)
    if len(data) >= 36:
        info.max_var = int(data[34]) | (int(data[35]) << 8)
    if len(data) >= 38:
        info.cad_var = int(data[36]) | (int(data[37]) << 8)
        if info.cad_var > 65000:
            info.cad_var = 0
    if len(data) >= 40:
        info.max_scenes = int(data[38]) | (int(data[39]) << 8)
    if len(data) >= 42:
        info.cad_scenes = int(data[40]) | (int(data[41]) << 8)
    return info


def processor_key(p: ProcessorInfo) -> tuple[str, str]:
    return (p.serial or "", p.ip or p.source_ip)


def merge_processors(dst: dict[tuple[str, str], ProcessorInfo], items: list[ProcessorInfo]) -> None:
    for item in items:
        dst[processor_key(item)] = item


def discover_processors_broadcast(
    port: int,
    timeout: float,
    probes: int,
    probe_interval: float,
    broadcast_ip: str,
) -> list[ProcessorInfo]:
    found: dict[tuple[str, str], ProcessorInfo] = {}
    packet = build_discover_packet()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", 0))
        sock.settimeout(0.2)

        for _ in range(max(1, probes)):
            sock.sendto(packet, (broadcast_ip, port))
            time.sleep(max(0.0, probe_interval))

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data, (src_ip, _) = sock.recvfrom(4096)
            except socket.timeout:
                continue
            info = parse_processor_response(data, src_ip)
            if not info:
                continue
            found[processor_key(info)] = info
    finally:
        sock.close()

    return sorted(found.values(), key=lambda x: (x.ip or x.source_ip, x.serial))


def hosts_from_subnet(subnet_cidr: str, limit: int) -> list[str]:
    net = ipaddress.ip_network(subnet_cidr, strict=False)
    hosts = [str(h) for h in net.hosts()]
    if limit > 0:
        hosts = hosts[:limit]
    return hosts


def discover_processors_unicast(
    hosts: list[str],
    port: int,
    timeout: float,
    probes: int,
) -> list[ProcessorInfo]:
    found: dict[tuple[str, str], ProcessorInfo] = {}
    packet = build_discover_packet()
    per_probe_timeout = max(0.02, min(0.2, timeout / 10.0 if timeout > 0 else 0.05))

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("", 0))
        sock.settimeout(per_probe_timeout)
        for _ in range(max(1, probes)):
            for host in hosts:
                sock.sendto(packet, (host, port))
            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    data, (src_ip, _) = sock.recvfrom(4096)
                except socket.timeout:
                    continue
                info = parse_processor_response(data, src_ip)
                if not info:
                    continue
                found[processor_key(info)] = info
    finally:
        sock.close()
    return sorted(found.values(), key=lambda x: (x.ip or x.source_ip, x.serial))


def discover_processors(
    port: int,
    timeout: float,
    probes: int,
    probe_interval: float,
    broadcast_ip: str,
    subnet: str | None = None,
    sweep_limit: int = 0,
) -> list[ProcessorInfo]:
    merged: dict[tuple[str, str], ProcessorInfo] = {}
    merge_processors(
        merged,
        discover_processors_broadcast(
            port=port,
            timeout=timeout,
            probes=probes,
            probe_interval=probe_interval,
            broadcast_ip=broadcast_ip,
        ),
    )

    if subnet:
        hosts = hosts_from_subnet(subnet, sweep_limit)
        merge_processors(
            merged,
            discover_processors_unicast(
                hosts=hosts,
                port=port,
                timeout=timeout,
                probes=probes,
            ),
        )

    return sorted(merged.values(), key=lambda x: (x.ip or x.source_ip, x.serial))


def query_devices(ip: str, port: int, timeout: float, max_pages: int) -> list[DeviceInfo]:
    all_devices: list[DeviceInfo] = []
    read_index = 0

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(timeout)
        for _ in range(max_pages):
            sock.sendto(build_get_connected_devices_packet(read_index), (ip, port))
            deadline = time.time() + timeout
            parsed: tuple[list[DeviceInfo], int, int] | None = None
            while time.time() < deadline:
                try:
                    data, (src_ip, _) = sock.recvfrom(8192)
                except socket.timeout:
                    break
                if src_ip != ip:
                    continue
                parsed = parse_devices_response(data, src_ip)
                if parsed is not None:
                    break
            if parsed is None:
                break
            devices, qty, current_index = parsed
            all_devices.extend(devices)
            if qty < 24:
                break
            read_index = current_index + qty
    finally:
        sock.close()

    return all_devices


def query_processor_discovery_info(ip: str, port: int, timeout: float, probes: int) -> ProcessorInfo | None:
    packet = build_discover_packet()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(max(0.05, timeout))
        for _ in range(max(1, probes)):
            sock.sendto(packet, (ip, port))
            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    data, (src_ip, _) = sock.recvfrom(4096)
                except socket.timeout:
                    break
                if src_ip != ip:
                    continue
                parsed = parse_processor_response(data, src_ip)
                if parsed is not None:
                    return parsed
    finally:
        sock.close()
    return None


def query_processor_bios_info(ip: str, port: int, timeout: float, probes: int) -> BiosInfo | None:
    packet = build_get_bios_packet()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(max(0.05, timeout))
        for _ in range(max(1, probes)):
            sock.sendto(packet, (ip, port))
            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    data, (src_ip, _) = sock.recvfrom(4096)
                except socket.timeout:
                    break
                if src_ip != ip:
                    continue
                parsed = parse_bios_response(data)
                if parsed is not None:
                    return parsed
    finally:
        sock.close()
    return None


def identify_module(
    ip: str,
    serial: bytes,
    beep: bool,
    port: int,
    duration: float,
    interval: float,
    timeout: float,
) -> int:
    packet = build_identify_packet(serial=serial, beep=beep)
    sends = 0
    end_time = time.time() + max(0.0, duration)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(max(0.05, timeout))
        while time.time() < end_time:
            sock.sendto(packet, (ip, port))
            sends += 1
            time.sleep(max(0.01, interval))
    finally:
        sock.close()
    return sends


def print_processors(processors: list[ProcessorInfo]) -> None:
    if not processors:
        print("No processors found.")
        return
    print(f"Found {len(processors)} processor(s):")
    for p in processors:
        print(
            f"- src={p.source_ip} ip={p.ip or '-'} name={p.name or '-'} "
            f"serial={p.serial or '-'} version={p.version or '-'} mac={p.mac or '-'}"
        )


def print_devices(devices: list[DeviceInfo]) -> None:
    if not devices:
        print("No devices returned.")
        return
    print(f"Found {len(devices)} device record(s):")
    for d in devices:
        print(
            f"- hsnet={d.hsnet_id:5d} dev_id={d.device_id:5d} port={d.port:3d} "
            f"model={d.model or '-'} ext={d.extended_model or '-'} fw={d.fw} "
            f"serial={d.serial_hex}"
        )


def emit_json(data: Any, out_path: str | None) -> None:
    text = json.dumps(data, indent=2)
    if out_path:
        Path(out_path).write_text(text + "\n", encoding="utf-8")
        print(f"Wrote {out_path}")
    else:
        print(text)


def cmd_discover(args: argparse.Namespace) -> int:
    processors = discover_processors(
        port=args.port,
        timeout=args.timeout,
        probes=args.probes,
        probe_interval=args.probe_interval,
        broadcast_ip=args.broadcast_ip,
        subnet=args.subnet,
        sweep_limit=args.sweep_limit,
    )
    if args.json:
        emit_json([asdict(p) for p in processors], args.out)
    else:
        print_processors(processors)
    return 0


def cmd_devices(args: argparse.Namespace) -> int:
    devices = query_devices(args.ip, args.port, args.timeout, args.max_pages)
    if args.json:
        emit_json([asdict(d) for d in devices], args.out)
    else:
        print_devices(devices)
    return 0


def cmd_scan_all(args: argparse.Namespace) -> int:
    processors = discover_processors(
        port=args.port,
        timeout=args.timeout,
        probes=args.probes,
        probe_interval=args.probe_interval,
        broadcast_ip=args.broadcast_ip,
        subnet=args.subnet,
        sweep_limit=args.sweep_limit,
    )
    results: list[dict[str, Any]] = []
    for p in processors:
        ip = p.ip or p.source_ip
        devices = query_devices(ip, args.port, args.device_timeout, args.max_pages)
        if devices or args.include_empty:
            results.append(
                {
                    "processor": asdict(p),
                    "devices": [asdict(d) for d in devices],
                }
            )

    if args.json:
        emit_json({"results": results}, args.out)
    else:
        if not results:
            print("No processors found.")
            return 0
        print(f"Found {len(results)} processor(s)")
        for item in results:
            p = item["processor"]
            print(
                f"- ip={p.get('ip') or p.get('source_ip')} name={p.get('name') or '-'} "
                f"serial={p.get('serial') or '-'} devices={len(item['devices'])}"
            )
    return 0


def cmd_identify(args: argparse.Namespace) -> int:
    serial = parse_serial_hex(args.serial)
    sent = identify_module(
        ip=args.ip,
        serial=serial,
        beep=not args.no_beep,
        port=args.port,
        duration=args.duration,
        interval=args.interval,
        timeout=args.timeout,
    )
    print(
        f"Sent {sent} identify packet(s) to {args.ip}:{args.port} "
        f"for serial {args.serial.upper()} (beep={'on' if not args.no_beep else 'off'})"
    )
    return 0


def cmd_processor_info(args: argparse.Namespace) -> int:
    proc = query_processor_discovery_info(args.ip, args.port, args.timeout, args.probes)
    bios = query_processor_bios_info(args.ip, args.port, args.timeout, args.probes)
    payload: dict[str, Any] = {
        "target_ip": args.ip,
        "port": args.port,
        "processor": asdict(proc) if proc else None,
        "bios": asdict(bios) if bios else None,
    }
    if args.with_devices:
        payload["devices"] = [asdict(d) for d in query_devices(args.ip, args.port, args.timeout, args.max_pages)]

    if args.json:
        emit_json(payload, args.out)
    else:
        print(f"Processor target: {args.ip}:{args.port}")
        if proc:
            print(
                f"- discovery: name={proc.name or '-'} serial={proc.serial or '-'} "
                f"ip={proc.ip or proc.source_ip} version={proc.version or '-'} mac={proc.mac or '-'}"
            )
        else:
            print("- discovery: no response")
        if bios:
            print(
                f"- bios: version={bios.version} max_modules={bios.max_modules} "
                f"max_units={bios.max_units} max_scripts={bios.max_scripts} "
                f"event_block={bios.event_block} string_var_block={bios.string_var_block}"
            )
        else:
            print("- bios: no response")
        if args.with_devices:
            devices = payload.get("devices", [])
            print(f"- devices: {len(devices)} record(s)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Roehn Wizard UDP discovery utility")
    sub = p.add_subparsers(dest="command", required=True)

    p_discover = sub.add_parser("discover", help="Broadcast discover processors")
    p_discover.add_argument("--port", type=int, default=2006, help="UDP port (default: 2006)")
    p_discover.add_argument("--broadcast-ip", default="255.255.255.255", help="Broadcast address")
    p_discover.add_argument("--timeout", type=float, default=3.0, help="Listen timeout seconds")
    p_discover.add_argument("--probes", type=int, default=3, help="Number of broadcast probes")
    p_discover.add_argument(
        "--probe-interval",
        type=float,
        default=0.1,
        help="Delay between probes in seconds",
    )
    p_discover.add_argument(
        "--subnet",
        default=None,
        help="Optional unicast sweep subnet, e.g. 192.168.51.0/24",
    )
    p_discover.add_argument(
        "--sweep-limit",
        type=int,
        default=0,
        help="Optional cap on swept hosts (0 = all hosts in subnet)",
    )
    p_discover.add_argument("--json", action="store_true", help="Output JSON")
    p_discover.add_argument("--out", default=None, help="Write JSON output to file (with --json)")
    p_discover.set_defaults(func=cmd_discover)

    p_devices = sub.add_parser("devices", help="Enumerate connected devices on one processor IP")
    p_devices.add_argument("ip", help="Processor IP address")
    p_devices.add_argument("--port", type=int, default=2006, help="UDP port (default: 2006)")
    p_devices.add_argument("--timeout", type=float, default=1.0, help="Per-page timeout seconds")
    p_devices.add_argument("--max-pages", type=int, default=32, help="Safety cap on pagination")
    p_devices.add_argument("--json", action="store_true", help="Output JSON")
    p_devices.add_argument("--out", default=None, help="Write JSON output to file (with --json)")
    p_devices.set_defaults(func=cmd_devices)

    p_scan = sub.add_parser("scan-all", help="Discover processors, then enumerate devices on each")
    p_scan.add_argument("--port", type=int, default=2006, help="UDP port (default: 2006)")
    p_scan.add_argument("--broadcast-ip", default="255.255.255.255", help="Broadcast address")
    p_scan.add_argument("--timeout", type=float, default=3.0, help="Discovery listen timeout seconds")
    p_scan.add_argument("--probes", type=int, default=3, help="Number of discovery probes")
    p_scan.add_argument(
        "--probe-interval",
        type=float,
        default=0.1,
        help="Delay between probes in seconds",
    )
    p_scan.add_argument(
        "--subnet",
        default=None,
        help="Optional unicast sweep subnet, e.g. 192.168.51.0/24",
    )
    p_scan.add_argument(
        "--sweep-limit",
        type=int,
        default=0,
        help="Optional cap on swept hosts (0 = all hosts in subnet)",
    )
    p_scan.add_argument(
        "--device-timeout",
        type=float,
        default=1.0,
        help="Per-page device enumeration timeout seconds",
    )
    p_scan.add_argument("--max-pages", type=int, default=32, help="Safety cap on pagination")
    p_scan.add_argument("--include-empty", action="store_true", help="Include processors with 0 devices")
    p_scan.add_argument("--json", action="store_true", help="Output JSON")
    p_scan.add_argument("--out", default=None, help="Write JSON output to file (with --json)")
    p_scan.set_defaults(func=cmd_scan_all)

    p_ident = sub.add_parser(
        "identify",
        help="Blink/beep identify a module by serial on a processor IP",
    )
    p_ident.add_argument("ip", help="Processor IP address")
    p_ident.add_argument("serial", help="Module serial in hex, e.g. 29:11:00:09:DB:4E")
    p_ident.add_argument("--port", type=int, default=2006, help="UDP port (default: 2006)")
    p_ident.add_argument("--duration", type=float, default=3.0, help="Total send duration seconds")
    p_ident.add_argument("--interval", type=float, default=0.3, help="Send interval seconds")
    p_ident.add_argument("--timeout", type=float, default=0.2, help="Socket timeout seconds")
    p_ident.add_argument("--no-beep", action="store_true", help="Disable beep flag in identify payload")
    p_ident.set_defaults(func=cmd_identify)

    p_info = sub.add_parser("processor-info", help="Query processor discovery and BIOS/capacity info")
    p_info.add_argument("ip", help="Processor IP address")
    p_info.add_argument("--port", type=int, default=2006, help="UDP port (default: 2006)")
    p_info.add_argument("--timeout", type=float, default=1.0, help="Socket timeout seconds")
    p_info.add_argument("--probes", type=int, default=2, help="Number of request retries")
    p_info.add_argument("--with-devices", action="store_true", help="Include device enumeration in output")
    p_info.add_argument("--max-pages", type=int, default=32, help="Safety cap for --with-devices pagination")
    p_info.add_argument("--json", action="store_true", help="Output JSON")
    p_info.add_argument("--out", default=None, help="Write JSON output to file (with --json)")
    p_info.set_defaults(func=cmd_processor_info)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
