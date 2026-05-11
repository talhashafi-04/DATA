#!/usr/bin/env python3
"""Generates a hidden test binary for anti-cheating verification.

This binary uses completely different sensor IDs, timestamps, and payload values
from the main fixture at /app/data/sensor_dump.bin. It verifies that the agent's
parser is a genuine general-purpose implementation rather than a solution that
hardcodes or derives answers solely from the known fixture.

Packet layout (7 packets total, 2 valid, 5 errors):
  idx 0: temperature ok          — sensor_id=100, ts=1800000000, value=15.0
  idx 1: checksum_mismatch       — pressure packet with corrupted CRC
  idx 2: unknown_sensor_type     — type byte 0xAA (undefined), valid CRC
  [junk: 0xBE 0xEF 0xCA 0xFE]
  idx 3: payload_length_mismatch — type=4 (gyroscope, expects 12 bytes) with 4-byte payload, CRC valid
  idx 4: humidity ok             — sensor_id=104, ts=1800000004, value=80.5
  idx 5: checksum_mismatch       — type byte 0xBB (undefined) AND corrupted CRC; must be
                                   classified as checksum_mismatch (not unknown_sensor_type),
                                   verifying that CRC is checked before sensor type.
  idx 6: truncated_packet        — magic bytes only, no length field

Expected summary:
  total=7, valid=2, error=5
  by_sensor_type: {temperature: 1, humidity: 1}
  by_error_type:  {checksum_mismatch: 2, unknown_sensor_type: 1,
                   payload_length_mismatch: 1, truncated_packet: 1}
"""

import os
import struct
import sys


def crc16_ccitt_false(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc


MAGIC = b'\xab\xcd'


def make_packet(sensor_id, timestamp, sensor_type, payload_bytes, corrupt_crc=False):
    crc_data = struct.pack('>HI', sensor_id, timestamp) + bytes([sensor_type]) + payload_bytes
    crc = crc16_ccitt_false(crc_data)
    if corrupt_crc:
        crc = (crc ^ 0x00FF) & 0xFFFF
    pkt_len = len(crc_data) + 2
    return MAGIC + struct.pack('>H', pkt_len) + crc_data + struct.pack('>H', crc)


data = b''
# idx 0: temperature ok
data += make_packet(100, 1800000000, 0, struct.pack('>f', 15.0))
# idx 1: checksum_mismatch (pressure, corrupted CRC)
data += make_packet(101, 1800000001, 2, struct.pack('>f', 950.0), corrupt_crc=True)
# idx 2: unknown_sensor_type (0xAA, valid CRC) — type unknown but CRC is fine
data += make_packet(102, 1800000002, 0xAA, b'\x00\x00\x00\x00')
# --- junk bytes ---
data += b'\xBE\xEF\xCA\xFE'
# idx 3: payload_length_mismatch — type=4 (gyroscope expects 12 bytes) but only 4-byte payload, CRC valid
data += make_packet(103, 1800000003, 4, struct.pack('>f', 0.5))
# idx 4: humidity ok
data += make_packet(104, 1800000004, 1, struct.pack('>f', 80.5))
# idx 5: both corrupted CRC AND unknown type byte (0xBB) — must be classified as
#         checksum_mismatch, not unknown_sensor_type, proving CRC is checked first
data += make_packet(105, 1800000005, 0xBB, b'\x00\x00\x00\x00', corrupt_crc=True)
# idx 6: truncated_packet — magic only, no length field follows
data += MAGIC

out_path = sys.argv[1] if len(sys.argv) > 1 else '/tmp/hidden_dump.bin'
os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
with open(out_path, 'wb') as f:
    f.write(data)
