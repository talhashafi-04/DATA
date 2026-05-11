#!/usr/bin/env python3
"""Binary sensor protocol parser — reference solution."""

import json
import os
import struct
import sys

MAGIC = b'\xab\xcd'

SENSOR_TYPES = {
    0: ("temperature", 4, "celsius"),
    1: ("humidity",    4, "percent"),
    2: ("pressure",    4, "hPa"),
    3: ("accelerometer", 12, "m/s2"),
    4: ("gyroscope",   12, "rad/s"),
}


def crc16_ccitt_false(data: bytes) -> int:
    """CRC-16/CCITT-FALSE: poly=0x1021, init=0xFFFF, no reflection, XOR-out=0x0000."""
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


def decode_payload(sensor_type: int, payload: bytes) -> dict:
    if sensor_type in (0, 1, 2):
        (val,) = struct.unpack(">f", payload)
        return {"value": round(float(val), 6), "unit": SENSOR_TYPES[sensor_type][2]}
    else:
        x, y, z = struct.unpack(">fff", payload)
        return {
            "x": round(float(x), 6),
            "y": round(float(y), 6),
            "z": round(float(z), 6),
            "unit": SENSOR_TYPES[sensor_type][2],
        }


def parse(filepath: str) -> dict:
    with open(filepath, "rb") as f:
        data = f.read()

    packets = []
    offset = 0
    packet_index = 0

    while offset < len(data):
        # Scan for magic bytes
        if data[offset:offset + 2] != MAGIC:
            offset += 1
            continue

        magic_offset = offset
        offset += 2  # consume magic

        # Read packet length (uint16 BE)
        if offset + 2 > len(data):
            packets.append({"packet_index": packet_index, "status": "error", "error": "truncated_packet"})
            packet_index += 1
            continue

        pkt_len = struct.unpack(">H", data[offset:offset + 2])[0]
        offset += 2

        # Read packet body
        if offset + pkt_len > len(data):
            packets.append({"packet_index": packet_index, "status": "error", "error": "truncated_packet"})
            packet_index += 1
            # Don't break — scan remaining bytes for any further packets
            continue

        body = data[offset:offset + pkt_len]
        offset += pkt_len

        # Minimum body: sensor_id(2) + timestamp(4) + type(1) + checksum(2) = 9
        if pkt_len < 9:
            packets.append({"packet_index": packet_index, "status": "error", "error": "truncated_packet"})
            packet_index += 1
            continue

        sensor_id = struct.unpack(">H", body[0:2])[0]
        timestamp = struct.unpack(">I", body[2:6])[0]
        sensor_type = body[6]
        payload = body[7:-2]
        stored_crc = struct.unpack(">H", body[-2:])[0]

        # Verify checksum
        computed_crc = crc16_ccitt_false(body[:-2])
        if computed_crc != stored_crc:
            packets.append({"packet_index": packet_index, "status": "error", "error": "checksum_mismatch"})
            packet_index += 1
            continue

        # Validate sensor type
        if sensor_type not in SENSOR_TYPES:
            packets.append({"packet_index": packet_index, "status": "error", "error": "unknown_sensor_type"})
            packet_index += 1
            continue

        # Validate payload length
        expected_len = SENSOR_TYPES[sensor_type][1]
        if len(payload) != expected_len:
            packets.append({"packet_index": packet_index, "status": "error", "error": "payload_length_mismatch"})
            packet_index += 1
            continue

        packets.append({
            "packet_index": packet_index,
            "status": "ok",
            "sensor_id": sensor_id,
            "timestamp": timestamp,
            "sensor_type": SENSOR_TYPES[sensor_type][0],
            "data": decode_payload(sensor_type, payload),
        })
        packet_index += 1

    valid = sum(1 for p in packets if p["status"] == "ok")
    error = sum(1 for p in packets if p["status"] == "error")

    by_sensor_type = {}
    for p in packets:
        if p["status"] == "ok":
            st = p["sensor_type"]
            by_sensor_type[st] = by_sensor_type.get(st, 0) + 1

    by_error_type = {}
    for p in packets:
        if p["status"] == "error":
            e = p["error"]
            by_error_type[e] = by_error_type.get(e, 0) + 1

    return {
        "packets": packets,
        "summary": {
            "total_packets": len(packets),
            "valid_packets": valid,
            "error_packets": error,
            "by_sensor_type": by_sensor_type,
            "by_error_type": by_error_type,
        },
    }


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.bin> <output.json>", file=sys.stderr)
        sys.exit(1)

    result = parse(sys.argv[1])
    os.makedirs(os.path.dirname(sys.argv[2]), exist_ok=True)
    with open(sys.argv[2], "w") as f:
        json.dump(result, f, indent=2)
