"""
Capture a focused sample of button 1 presses.

Instructions:
  - When prompted, press button 1 about 10 times within the capture window.
  - Script records all bus traffic during the window, then summarizes 23-byte frames.

Outputs (in logs/):
  - button1_capture_<timestamp>.bin (raw bytes)
  - button1_capture_<timestamp>.txt (23-byte frame summary)
"""

import binascii
import time
from collections import Counter
from pathlib import Path

import serial

PORT = "COM3"
BAUD = 19200
CAPTURE_SECONDS = 25  # ample time for 10 presses


def crc16_ccitt(data: bytes) -> int:
    return binascii.crc_hqx(data, 0xFFFF) & 0xFFFF


def decode_frames(blob: bytes):
    i = 0
    out = []
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
                out.append(bytes(blob[i : i + L]))
                i += L
                matched = True
                break
        if not matched:
            i += 1
    return out


def summarize_23(frames):
    ctr = Counter(f for f in frames if len(f) == 23)
    lines = [f"23-byte frames: {len(ctr)} unique"]
    for f, c in ctr.most_common():
        lines.append(f"{c:3d}  {f.hex(' ')}")
    return "\n".join(lines)


def main():
    ser = serial.Serial(PORT, BAUD, bytesize=8, parity="N", stopbits=1, timeout=0)
    start = time.time()
    end = start + CAPTURE_SECONDS
    print(f"Started {start:.3f}; press BUTTON 1 about 10 times now (window {CAPTURE_SECONDS}s).")

    next_tick = CAPTURE_SECONDS
    buf = bytearray()
    while True:
        now = time.time()
        if now >= end:
            break
        chunk = ser.read(4096)
        if chunk:
            buf.extend(chunk)
        remaining = end - now
        if remaining <= next_tick:
            print(f"... {remaining:4.1f}s left")
            next_tick -= 1
        time.sleep(0.01)

    ser.close()
    raw = bytes(buf)
    frames = decode_frames(raw)
    summary = summarize_23(frames)

    ts = int(time.time())
    logdir = Path("logs")
    logdir.mkdir(exist_ok=True)
    bin_path = logdir / f"button1_capture_{ts}.bin"
    txt_path = logdir / f"button1_capture_{ts}.txt"
    bin_path.write_bytes(raw)
    txt_path.write_text(summary, encoding="utf-8")

    print(f"Capture complete. Raw: {bin_path}  Summary: {txt_path}")
    print(summary)


if __name__ == "__main__":
    main()
