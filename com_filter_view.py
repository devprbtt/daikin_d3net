"""
Live COM viewer with noise filtering.

Shows CRC‑valid frames from COM3@19200 but suppresses the constant 6‑byte poll noise
unless they change. Always shows 23‑byte frames (key events) immediately.

Controls:
  - Runs until Ctrl+C.
  - Prints a summary every second of suppressed polls (count).

Adjust PORT/BAUD below if needed.
"""

import binascii
import time
from collections import Counter
import serial

PORT = "COM3"
BAUD = 19200


def crc16_ccitt(data: bytes) -> int:
    return binascii.crc_hqx(data, 0xFFFF) & 0xFFFF


def decode_frames(buf: bytearray):
    """Return (frames, leftover) CRC‑valid frames len 4..39 framed on 0x02."""
    frames = []
    i = 0
    while i < len(buf) - 4:
        if buf[i] != 0x02:
            i += 1
            continue
        matched = False
        for L in range(4, 40):
            if i + L > len(buf):
                break
            data = buf[i + 1 : i + L - 2]
            stored = (buf[i + L - 2] << 8) | buf[i + L - 1]
            if crc16_ccitt(data) == stored:
                frames.append(bytes(buf[i : i + L]))
                i += L
                matched = True
                break
        if not matched:
            i += 1
    leftover = bytes(buf[i:])
    return frames, leftover


def main():
    try:
        ser = serial.Serial(PORT, BAUD, bytesize=8, parity="N", stopbits=1, timeout=0)
    except Exception as exc:
        print(f"Could not open {PORT}: {exc}")
        return

    print(f"Listening on {PORT}@{BAUD}. Ctrl+C to stop.")
    buf = bytearray()
    poll_counts = Counter()
    addr_counts = Counter()
    evt_counts = 0
    last_report = time.time()

    try:
        while True:
            buf.extend(ser.read(4096))
            frames, leftover = decode_frames(buf)
            buf = bytearray(leftover)

            now = time.time()
            for fr in frames:
                if len(fr) == 6:
                    poll_counts[fr] += 1  # count frame signatures
                    addr_counts[fr[1]] += 1  # track addresses
                elif len(fr) == 23:
                    evt_counts += 1
                    print(f"{now:.3f} EVT  {fr.hex(' ')}")
                else:
                    print(f"{now:.3f} FRM len={len(fr):02d} {fr.hex(' ')}")

            if now - last_report >= 1.0:
                if poll_counts:
                    total = sum(poll_counts.values())
                    uniq = len(poll_counts)
                    top_addrs = ", ".join(
                        f"{addr}(x{cnt})" for addr, cnt in addr_counts.most_common(3)
                    )
                    print(f"... polls: {total} (uniq {uniq}); addrs: {top_addrs}")
                    poll_counts.clear()
                    addr_counts.clear()
                last_report = now

            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        ser.close()
        print(f"Stopped. Total EVT frames seen: {evt_counts}")


if __name__ == "__main__":
    main()
