"""
Live BTN1 counter.

Listens on COM3@19200 and prints each detected Button‑1 press with timestamp,
maintaining a running count. Also logs all detections to logs/btn1_live_<ts>.txt.

BTN1 signature (keypad -> gateway, 23-byte frames):
  dir byte 0x80 and payload bytes 4-7 either:
    - 00 00 03 00
    - 01 00 03 00

Usage:
  python keypad_live_counter.py
Stop with Ctrl+C.
"""

import binascii
import time
from pathlib import Path

import serial

PORT = "COM3"
BAUD = 19200

# BTN1 payload patterns (bytes 4-7)
BTN1_PAYLOADS = {
    (0x00, 0x00, 0x03, 0x00),
    (0x01, 0x00, 0x03, 0x00),
}


def crc16_ccitt(data: bytes) -> int:
    return binascii.crc_hqx(data, 0xFFFF) & 0xFFFF


def decode_frames(buf: bytearray):
    """
    Extract CRC-valid frames (len 4..39) framed on 0x02 start.
    Returns (frames, leftover) so partial trailing data is preserved.
    """
    frames = []
    i = 0
    while i < len(buf) - 4:
        if buf[i] != 0x02:
            i += 1
            continue
        matched = False
        for L in range(4, 40):
            if i + L > len(buf):
                break  # not enough data yet
            data = buf[i + 1 : i + L - 2]
            stored = (buf[i + L - 2] << 8) | buf[i + L - 1]
            if crc16_ccitt(data) == stored:
                frames.append(bytes(buf[i : i + L]))
                i += L
                matched = True
                break
        if not matched:
            i += 1
    leftover = bytes(buf[i:])  # keep tail that might be partial frame
    return frames, leftover


def is_btn1_press(frame: bytes) -> bool:
    if len(frame) != 23:
        return False
    if frame[1] != 0x80:  # require keypad->gateway direction
        return False
    return tuple(frame[4:8]) in BTN1_PAYLOADS


def main():
    try:
        ser = serial.Serial(PORT, BAUD, bytesize=8, parity="N", stopbits=1, timeout=0)
    except Exception as exc:
        print(f"Could not open {PORT}: {exc}")
        return

    print(f"Listening on {PORT}@{BAUD} for BTN1 presses. Ctrl+C to stop.", flush=True)
    ts_start = int(time.time())
    logdir = Path("logs")
    logdir.mkdir(exist_ok=True)
    log_path = logdir / f"btn1_live_{ts_start}.txt"
    log_file = log_path.open("w", encoding="utf-8", buffering=1)

    buf = bytearray()
    count = 0
    try:
        while True:
            buf.extend(ser.read(4096))
            frames, leftover = decode_frames(buf)
            buf = bytearray(leftover)
            if not frames:
                time.sleep(0.01)
                continue
            now = time.time()
            for fr in frames:
                if is_btn1_press(fr):
                    count += 1
                    line = f"{now:.3f} BTN1 #{count} {fr.hex(' ')}"
                    print(line)
                    log_file.write(line + "\n")
    except KeyboardInterrupt:
        pass
    finally:
        ser.close()
        log_file.close()
        print(f"Stopped. Logged to {log_path}")


if __name__ == "__main__":
    main()
