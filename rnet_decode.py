"""
Decode frames from rnet.bin produced by rnet_logger.py.

Protocol (inferred):
  - Start byte: 0x02
  - Marker:     0x7E
  - Payload:    variable (>=1 byte)
  - CRC16-IBM (poly 0xA001, init 0xFFFF) over bytes AFTER the leading 0x02.
    Stored big‑endian (high byte then low byte).

This script:
  * Scans the stream for 0x02 0x7E markers.
  * Splits frames at each marker.
  * Verifies CRC and prints a table.
"""

import argparse
from pathlib import Path


def crc16_ccitt(data: bytes, init: int = 0xFFFF) -> int:
    """
    CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF), MSB-first.
    binascii.crc_hqx implements this variant.
    """
    import binascii

    return binascii.crc_hqx(data, init) & 0xFFFF


def parse_frames(blob: bytes):
    markers = [i for i in range(len(blob) - 1) if blob[i] == 0x02 and blob[i + 1] == 0x7E]
    for idx, pos in enumerate(markers):
        end = markers[idx + 1] if idx + 1 < len(markers) else len(blob)
        frame = blob[pos:end]
        if len(frame) < 5:  # 0x02 0x7E x crc_hi crc_lo
            yield (pos, frame, False, None)
            continue
        data_for_crc = frame[1:-2]  # exclude leading 0x02, drop CRC
        stored_crc = (frame[-2] << 8) | frame[-1]  # big-endian on wire
        calc_crc = crc16_ccitt(data_for_crc)
        ok = stored_crc == calc_crc
        yield (pos, frame, ok, calc_crc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", nargs="?", default="rnet.bin", help="input raw byte file from rnet_logger")
    args = ap.parse_args()

    blob = Path(args.file).read_bytes()
    print(f"Input {args.file}: {len(blob)} bytes")

    for idx, (pos, frame, ok, crc) in enumerate(parse_frames(blob)):
        hex_bytes = " ".join(f"{b:02X}" for b in frame)
        status = "OK" if ok else "BAD"
        print(f"{idx:04d} @{pos:05d} len={len(frame):02d} {status} crc_calc={crc:04X} -> {hex_bytes}")


if __name__ == "__main__":
    main()
