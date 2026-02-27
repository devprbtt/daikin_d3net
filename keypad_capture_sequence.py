"""
Guided keypad capture.

Workflow per button (1→4):
  - Prompt user to press the button twice during a 6s window.
  - Record all bus bytes during that window.
  - Repeat after a 5s idle gap.

Output:
  logs/keypad_capture_<timestamp>.bin  (raw bytes for all windows)
  logs/keypad_capture_<timestamp>.txt  (human summary of 23‑byte frames)

Defaults: COM3, 19200 baud, 8N1. Adjust PORT/BAUD constants if needed.
Run: python keypad_capture_sequence.py
"""

import binascii
import time
from collections import Counter
from pathlib import Path

import serial

PORT = "COM3"
BAUD = 19200
WINDOW_SECONDS = 6
GAP_SECONDS = 5


def crc16_ccitt(data: bytes) -> int:
    return binascii.crc_hqx(data, 0xFFFF) & 0xFFFF


def capture_window(ser: serial.Serial, seconds: float) -> bytes:
    end = time.time() + seconds
    buf = bytearray()
    while time.time() < end:
        buf.extend(ser.read(4096))
        time.sleep(0.005)
    return bytes(buf)


def find_frames(blob: bytes):
    """Yield CRC‑valid frames (len 4..39) framed on 0x02 start."""
    i = 0
    while i < len(blob) - 4:
        if blob[i] != 0x02:
            i += 1
            continue
        matched = False
        for L in range(4, 40):
            if i + L > len(blob):
                break
            data = blob[i + 1 : i + L - 2]
            stored = (blob[i + L - 2] << 8) | blob[i + L - 1]
            if crc16_ccitt(data) == stored:
                yield bytes(blob[i : i + L])
                i += L
                matched = True
                break
        if not matched:
            i += 1


def summarize(frames):
    ctr = Counter(f for f in frames if len(f) == 23)
    lines = []
    lines.append(f"23-byte frames: {len(ctr)} unique")
    for f, c in ctr.most_common():
        lines.append(f"{c:3d}  {f.hex(' ')}")
    return "\n".join(lines)


def main():
    ser = serial.Serial(PORT, BAUD, bytesize=8, parity="N", stopbits=1, timeout=0)
    print(f"Opened {PORT} @ {BAUD}.")

    buttons = ["1", "2", "3", "4"]
    all_bytes = bytearray()
    for b in buttons:
        print(f"\nPress button {b} twice NOW (window {WINDOW_SECONDS}s)…")
        window_bytes = capture_window(ser, WINDOW_SECONDS)
        all_bytes.extend(window_bytes)
        if b != buttons[-1]:
            print(f"Waiting {GAP_SECONDS}s before next button…")
            time.sleep(GAP_SECONDS)

    ser.close()

    ts = int(time.time())
    logdir = Path("logs")
    logdir.mkdir(exist_ok=True)
    bin_path = logdir / f"keypad_capture_{ts}.bin"
    txt_path = logdir / f"keypad_capture_{ts}.txt"

    bin_path.write_bytes(all_bytes)
    frames = list(find_frames(all_bytes))
    summary = summarize(frames)
    txt_path.write_text(summary, encoding="utf-8")

    print(f"\nCapture complete. Raw: {bin_path}  Summary: {txt_path}")
    print(summary)


if __name__ == "__main__":
    main()
