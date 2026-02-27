"""
Live raw hex logger to terminal.

Prints every read chunk from COM3@19200 with a timestamp; no decoding or filtering.
Use Ctrl+C to stop.
"""

import time
import serial

PORT = "COM3"
BAUD = 19200


def main():
    try:
        ser = serial.Serial(PORT, BAUD, 8, "N", 1, timeout=0)
    except Exception as exc:
        print(f"Could not open {PORT}: {exc}")
        return

    print(f"Listening raw on {PORT}@{BAUD}. Ctrl+C to stop.")
    try:
        while True:
            chunk = ser.read(4096)
            if chunk:
                ts = time.time()
                print(f"{ts:.3f} {chunk.hex(' ')}")
            else:
                time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        ser.close()
        print("Stopped.")


if __name__ == "__main__":
    main()
