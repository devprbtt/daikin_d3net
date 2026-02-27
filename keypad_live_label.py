"""
Live keypad decoder: prints button presses in real time.

Uses the mappings derived from guided capture:
  Btn1: payload word 0x0300 (keypad-> 02 80 ... 01 00 03 00 ...)
  Btn2: payload word 0x0C00 (02 80 ... 02 00 0C 00 ...)
  Btn3: payload word 0x3000 (02 80 ... 00 00 30 00 ...)
  Btn4: payload word 0xC000 (02 80 ... 08 00 C0 00 ...)
Direction:
  0x80 in byte1  => keypad -> gateway (press)
  0x00 in byte1  => gateway -> keypad/ack

Run: python keypad_live_label.py
Adjust PORT/BAUD below if needed.
"""

import binascii
import time
import serial

PORT = "COM3"
BAUD = 19200

# map payload word (bytes 4-5 after leading 02 80 12 0e) to label
PAYLOAD_TO_BTN = {
    # BTN1 primary variants (observed on addr 102)
    (0x00, 0x00, 0x03, 0x00): ("BTN1", "main"),  # KP->GW press
    (0x01, 0x00, 0x03, 0x00): ("BTN1", "main"),  # GW->KP release/ack
    # BTN2 primary variants
    (0x00, 0x00, 0x0C, 0x00): ("BTN2", "main"),
    (0x02, 0x00, 0x0C, 0x00): ("BTN2", "main"),
    # BTN3 primary variants
    (0x00, 0x00, 0x30, 0x00): ("BTN3", "main"),
    (0x04, 0x00, 0x30, 0x00): ("BTN3", "main"),
    # BTN4 primary variants
    (0x00, 0x00, 0xC0, 0x00): ("BTN4", "main"),
    (0x08, 0x00, 0xC0, 0x00): ("BTN4", "main"),
}


def crc16_ccitt(data: bytes) -> int:
    return binascii.crc_hqx(data, 0xFFFF) & 0xFFFF


def decode_frames(blob: bytearray):
    """Yield CRC-valid frames (len 4..39) framed on 0x02 start."""
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


def label_frame(frame: bytes):
    if len(frame) != 23:
        return None
    # frame layout observed: 02 [dir] 12 0e P0 P1 P2 P3 ... CRC
    dir_byte = frame[1]
    p = frame[4:8]
    key = tuple(p)
    btn_info = PAYLOAD_TO_BTN.get(key)

    # Heuristic event type:
    # - dir 0x80 (keypad->gateway) with BTN payload -> PRESS
    # - dir 0x00 (gateway->keypad) with BTN payload -> RELEASE/ACK
    # - otherwise label as OTHER with payload

    if btn_info:
        btn, _variant = btn_info
        if dir_byte == 0x80:
            etype = "PRESS"
        elif dir_byte == 0x00:
            etype = "RELEASE"
        else:
            etype = f"dir={dir_byte:02X}"
        return f"{btn} {etype}"

    direction = "KP->GW" if dir_byte == 0x80 else "GW->KP" if dir_byte == 0x00 else f"dir={dir_byte:02X}"
    return f"OTHER {direction} p={p.hex()}"


def main():
    ser = serial.Serial(PORT, BAUD, bytesize=8, parity="N", stopbits=1, timeout=0)
    print(f"Listening on {PORT}@{BAUD}. Press buttons; Ctrl+C to stop.")
    buf = bytearray()
    try:
        while True:
            buf.extend(ser.read(4096))
            frames = decode_frames(buf)
            if frames:
                buf.clear()  # consume
            ts = time.time()
            for fr in frames:
                label = label_frame(fr)
                if label:
                    print(f"{ts:.3f} {label}  {fr.hex(' ')}")
    except KeyboardInterrupt:
        pass
    finally:
        ser.close()


if __name__ == "__main__":
    main()
