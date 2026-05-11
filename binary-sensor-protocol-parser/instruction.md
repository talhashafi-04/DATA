# Binary Sensor Protocol Parser

I want you to write a Python script at `/solution/parser.py`. This script will take two positional arguments: the input binary file path and the output JSON path.

Your solution will be invoked as:

```
python3 /solution/parser.py <input_path> <output_path>
```

Read from `/app/data/sensor_dump.bin`, write output to `/app/output/results.json`. You need to parse every packet you find, deal with broken ones gracefully, then dump the results.


## Packet Structure

Packets start with the magic bytes `0xAB 0xCD`. Anything that doesn't line up with that isn't a packet boundary — just skip ahead byte by byte until you find the next `0xAB 0xCD` or run out of file.

After the magic comes a **packet length** field — a big-endian `uint16`. It tells you how many bytes follow it, from the sensor ID all the way through the final checksum byte.

The remaining fields, all big-endian:

- Sensor ID: `uint16`, identifies which sensor sent this.
- Timestamp: `uint32`, Unix epoch seconds.
- Sensor type: `uint8`, tells you what kind of data is in the payload.
- Payload: variable length, structure depends on sensor type.
- Checksum: `uint16` at the very end. CRC-16/CCITT-FALSE over all bytes from Sensor ID through the last payload byte — not the magic, not the length field.

CRC-16/CCITT-FALSE: polynomial `0x1021`, init `0xFFFF`, no reflection on input or output, XOR-out `0x0000`.

---

## Sensor Types

Five types, all payloads are big-endian IEEE 754 single-precision floats:

- **0 / temperature** — one `float32`, degrees Celsius. Output key `"value"`, unit `"celsius"`.
- **1 / humidity** — one `float32`, percentage. Output key `"value"`, unit `"percent"`.
- **2 / pressure** — one `float32`, hectopascals. Output key `"value"`, unit `"hPa"`.
- **3 / accelerometer** and **4 / gyroscope** both use three `float32`s for X, Y, Z axes with output keys `"x"`, `"y"`, `"z"`. Unit is `"m/s2"` for accelerometer and `"rad/s"` for gyroscope.

Anything outside 0–4 is an unknown type.

---

## Errors

Never crash. Every broken packet still gets an entry in the output — just with an error status instead of data. There are four things that can go wrong:

`truncated_packet` — the file runs out of bytes before the packet is complete. This covers any case where you find the magic bytes but can't finish reading the packet — whether that's because there aren't enough bytes left to read the length field, or you read the length but the body is cut short. Still counts as a packet, still needs an entry.

`checksum_mismatch` — CRC you computed doesn't match what's stored.

`unknown_sensor_type` — type byte isn't 0–4.

`payload_length_mismatch` — payload byte count doesn't match what the type requires.

When a packet has multiple problems, only record the first one that applies. Priority goes: truncated → checksum → unknown type → payload length.

---

## Output

JSON file at the output path. Two keys: `packets` and `summary`.

`packets` is an array, one entry per packet in file order, zero-indexed. Valid ones look like:

```json
{
  "packet_index": 0,
  "status": "ok",
  "sensor_id": 1,
  "timestamp": 1700000000,
  "sensor_type": "temperature",
  "data": {"value": 23.5, "unit": "celsius"}
}
```

Error ones look like:

```json
{
  "packet_index": 5,
  "status": "error",
  "error": "checksum_mismatch"
}
```

`summary` needs five keys: `total_packets`, `valid_packets`, `error_packets` as integers, plus `by_sensor_type` and `by_error_type` as objects mapping names to counts. Skip any type or error that had zero occurrences.

Create the output directory if it doesn't exist yet.