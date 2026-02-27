"""
Simple RNET bus sniffer for ROEHN M8 (RS‑485) using pyserial.

Default: COM3, 19200 baud, 8N1. Logs timestamped hex lines to a text file
and optionally dumps raw bytes to a binary file.

Usage examples:
  python rnet_logger.py               # log to rnet_log.txt until Ctrl+C
  python rnet_logger.py --duration 30 # 30‑second capture
  python rnet_logger.py --outfile m8.txt --raw m8.bin
  python rnet_logger.py --port COM4 --baud 19200 --parity E --stopbits 1
"""

import argparse
import sys
import time
from pathlib import Path

import serial


PARITY_MAP = {
    "N": serial.PARITY_NONE,
    "E": serial.PARITY_EVEN,
    "O": serial.PARITY_ODD,
    "M": serial.PARITY_MARK,
    "S": serial.PARITY_SPACE,
}

STOPBITS_MAP = {
    "1": serial.STOPBITS_ONE,
    "2": serial.STOPBITS_TWO,
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Timestamped RS‑485 logger for ROEHN RNET bus")
    p.add_argument("--port", default="COM3", help="Serial port (default: COM3)")
    p.add_argument("--baud", type=int, default=19200, help="Baud rate (default: 19200)")
    p.add_argument("--parity", choices=PARITY_MAP.keys(), default="N", help="Parity (default: N)")
    p.add_argument("--stopbits", choices=STOPBITS_MAP.keys(), default="1", help="Stop bits (default: 1)")
    p.add_argument("--outfile", default="rnet_log.txt", help="Text log path (timestamped hex per line)")
    p.add_argument(
        "--raw",
        default=None,
        help="Optional raw binary output path (appends bytes exactly as received)",
    )
    p.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Stop after N seconds (default: run until Ctrl+C)",
    )
    p.add_argument(
        "--chunk",
        type=int,
        default=4096,
        help="Read buffer size per iteration (default: 4096)",
    )
    return p.parse_args()


def open_ports(args: argparse.Namespace):
    ser = serial.Serial(
        port=args.port,
        baudrate=args.baud,
        bytesize=serial.EIGHTBITS,
        parity=PARITY_MAP[args.parity],
        stopbits=STOPBITS_MAP[args.stopbits],
        timeout=0,  # non‑blocking
    )
    text_path = Path(args.outfile)
    text_file = text_path.open("a", encoding="ascii", buffering=1)
    raw_file = None
    if args.raw:
        raw_file = Path(args.raw).open("ab", buffering=0)
    return ser, text_file, raw_file


def log_loop(args: argparse.Namespace):
    ser, text_file, raw_file = open_ports(args)
    start = time.time()
    next_flush = start + 1.0
    try:
        while True:
            if args.duration and (time.time() - start) >= args.duration:
                break

            data = ser.read(args.chunk)
            if data:
                ts = time.time()
                hex_line = " ".join(f"{b:02X}" for b in data)
                text_file.write(f"{ts:.6f} {hex_line}\n")
                if raw_file:
                    raw_file.write(data)

            # periodic flush keeps data on disk even if interrupted
            now = time.time()
            if now >= next_flush:
                text_file.flush()
                if raw_file:
                    raw_file.flush()
                next_flush = now + 1.0

            # avoid a tight CPU loop when bus is idle
            if not data:
                time.sleep(0.005)
    except KeyboardInterrupt:
        pass
    finally:
        text_file.flush()
        text_file.close()
        if raw_file:
            raw_file.flush()
            raw_file.close()
        ser.close()


def main():
    args = parse_args()
    try:
        log_loop(args)
    except serial.SerialException as exc:
        sys.stderr.write(f"Serial error: {exc}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
