import importlib.util
import hashlib
import json
import re
import random
import struct
import subprocess
import sys
import tempfile
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

APP_DIR = Path("/app")
MESSAGES_PATH = APP_DIR / "data" / "messages.bin"
DECODER_PATH = APP_DIR / "capnp_decoder.py"
HIDDEN_CASES_PATH = Path(__file__).parent / "hidden_data" / "hidden_cases.json"
HIDDEN_MESSAGES_PATH = Path(__file__).parent / "hidden_data" / "messages.bin"
MAGIC = b"CPNPTRAV"

KIND_STRUCT = 0
KIND_LIST = 1
LIST_BYTE = 2
LIST_POINTER = 6
LIST_COMPOSITE = 7


def expected_message_count():
    raw = HIDDEN_MESSAGES_PATH.read_bytes()
    assert raw.startswith(MAGIC)
    return struct.unpack_from("<I", raw, len(MAGIC))[0]


def signed32(value):
    masked = value & 0xFFFFFFFF
    if masked & 0x80000000:
        return masked - (1 << 32)
    return masked


def segment_label(message_index, segment_index, point_count):
    base = f"segment-{message_index:02d}-{segment_index:02d}-pts-{point_count}"
    return base


def edge_segments(message_index):
    if message_index == 45:
        return []
    if message_index == 46:
        return [
            {
                "ordinal": 0xFFFFFFFF,
                "checksum": -2147483648,
                "label": "segment-46-edge-utf8-μ-long-label-spans-multiple-words",
                "points": [
                    {"x": -2147483648, "y": 2147483647, "z": 0, "signal": -1},
                    {"x": 2147483647, "y": -2147483648, "z": -2147483648, "signal": 2147483647},
                    {"x": 0, "y": 0, "z": 1, "signal": -2147483648},
                ],
                "tags": [
                    "",
                    "edge-tag-utf8-终",
                    "edge-tag-long-spans-more-than-one-capnp-word-0123456789",
                ],
            }
        ]
    if message_index == 47:
        dense_points = []
        for point_index in range(17):
            dense_points.append(
                {
                    "x": signed32(0x70000000 + point_index * 977),
                    "y": signed32(-0x70000000 - point_index * 619),
                    "z": signed32(point_index * point_index * 12345 - 2000000000),
                    "signal": signed32(0x80000000 + point_index),
                }
            )
        return [
            {
                "ordinal": 2147483648,
                "checksum": -1,
                "label": "segment-47-empty-points-with-pointer-tags",
                "points": [],
                "tags": ["", "tail", "tags-after-empty-points"],
            },
            {
                "ordinal": 2147483649,
                "checksum": 2147483647,
                "label": "segment-47-single-point-boundary",
                "points": [{"x": -1, "y": 1, "z": -2, "signal": 2}],
                "tags": [],
            },
            {
                "ordinal": 3000000000,
                "checksum": -123456789,
                "label": "segment-47-dense-points-and-wide-tags-αβγ",
                "points": dense_points,
                "tags": [
                    "dense-0",
                    "dense-1",
                    "dense-wide-مرحبا",
                    "dense-long-tag-spans-several-words-ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                ],
            },
        ]
    if message_index == 88:
        return []
    if message_index == 89:
        points = []
        for point_index in range(29):
            points.append(
                {
                    "x": signed32(0x7FFFF000 - point_index * 4099),
                    "y": signed32(-0x7FFF0000 + point_index * 8191),
                    "z": signed32((point_index * 65537) - 2147483648),
                    "signal": signed32(2147483647 - point_index * 17),
                }
            )
        return [
            {
                "ordinal": 4294967295,
                "checksum": -2147483648,
                "label": "segment-89-large-dense-message-with-long-label-κλμνξοπρστυφχψω",
                "points": points,
                "tags": [
                    f"segment-89-tag-{slot:02d}-long-text-spans-multiple-words-{slot * 37:04d}"
                    for slot in range(18)
                ],
            }
        ]
    if message_index == 90:
        segments = []
        point_counts = [0, 1, 2, 8, 16, 33]
        for segment_index, point_count in enumerate(point_counts):
            points = []
            for point_index in range(point_count):
                points.append(
                    {
                        "x": signed32(segment_index * 1000003 + point_index * 97),
                        "y": signed32(-segment_index * 999983 - point_index * 193),
                        "z": signed32((point_index - segment_index) * 1234567),
                        "signal": signed32(0x80000000 + segment_index * 257 + point_index),
                    }
                )
            segments.append(
                {
                    "ordinal": signed32(0xFFFFFF00 + segment_index) & 0xFFFFFFFF,
                    "checksum": signed32(0x7FFFFFFF - segment_index),
                    "label": f"segment-90-mixed-count-{segment_index:02d}-pts-{point_count:02d}",
                    "points": points,
                    "tags": [
                        "",
                        f"seg90-{segment_index}-tag-wide-עברית",
                        f"seg90-{segment_index}-long-tag-abcdefghijklmnopqrstuvwxyz-{point_count:02d}",
                    ][: 1 + (segment_index % 3)],
                }
            )
        return segments
    if message_index == 91:
        points = []
        for point_index in range(64):
            points.append(
                {
                    "x": signed32(-2147483648 + point_index * 65536),
                    "y": signed32(2147483647 - point_index * 32768),
                    "z": signed32((point_index * point_index * 4093) ^ 0xAAAAAAAA),
                    "signal": signed32(0x55555555 + point_index * 104729),
                }
            )
        return [
            {
                "ordinal": 4000000000,
                "checksum": -400000000,
                "label": "segment-91-sixty-four-points-and-wide-text-数据-проверка",
                "points": points,
                "tags": [
                    "bulk",
                    "bulk-empty-neighbor",
                    "",
                    "bulk-wide-данные",
                    "bulk-long-tag-" + ("xyz" * 20),
                ],
            }
        ]
    if message_index == 92:
        return [
            {
                "ordinal": 2147483650 + segment_index,
                "checksum": signed32(-2000000000 + segment_index * 123456),
                "label": f"segment-92-unicode-{segment_index}-東京-مرحبا-данные",
                "points": [
                    {
                        "x": signed32(1000 + segment_index * 10 + point_index),
                        "y": signed32(-1000 - segment_index * 10 - point_index),
                        "z": signed32(segment_index * point_index - 12345),
                        "signal": signed32(-2147483648 + segment_index * 100 + point_index),
                    }
                    for point_index in range(3 + segment_index)
                ],
                "tags": ["東京", "مرحبا", "данные", f"wide-{segment_index}-終"],
            }
            for segment_index in range(4)
        ]
    if message_index == 93:
        return [
            {
                "ordinal": 93,
                "checksum": 0,
                "label": "segment-93-many-empty-tags",
                "points": [],
                "tags": [""] * 12,
            }
        ]
    if message_index == 94:
        return [
            {
                "ordinal": 4294967290 + segment_index,
                "checksum": signed32(2147483647 - segment_index * 100000),
                "label": f"segment-94-boundary-row-{segment_index}",
                "points": [
                    {"x": -1, "y": 0, "z": 1, "signal": -2},
                    {"x": 2147483647, "y": -2147483648, "z": segment_index, "signal": -2147483648},
                ],
                "tags": [f"boundary-{segment_index}", f"boundary-long-{segment_index}-" + ("ab" * 16)],
            }
            for segment_index in range(5)
        ]
    if message_index == 95:
        return [
            {
                "ordinal": 0,
                "checksum": -1,
                "label": "segment-95-final-empty-everything",
                "points": [],
                "tags": [],
            },
            {
                "ordinal": 1,
                "checksum": 1,
                "label": "segment-95-final-single-point",
                "points": [{"x": 1, "y": -1, "z": 2, "signal": -2}],
                "tags": ["final"],
            },
        ]
    if 96 <= message_index < 128:
        segment_count = 2 + (message_index % 7)
        segments = []
        for segment_index in range(segment_count):
            if segment_index == 0 and message_index % 4 == 0:
                point_count = 0
            else:
                point_count = ((message_index * 11 + segment_index * 17) % 41) + 1
            points = []
            for point_index in range(point_count):
                points.append(
                    {
                        "x": signed32(0x7FFFFFFF - message_index * 4096 - segment_index * 257 - point_index * 31),
                        "y": signed32(-0x80000000 + message_index * 2048 + segment_index * 503 + point_index * 47),
                        "z": signed32((message_index - 96) * 100000 + segment_index * 1000 - point_index * 13),
                        "signal": signed32(0x80000000 + message_index * 313 + segment_index * 29 + point_index),
                    }
                )
            tag_count = (message_index + segment_index) % 9
            tags = []
            for tag_index in range(tag_count):
                if tag_index == 0 and segment_index % 3 == 0:
                    tags.append("")
                elif tag_index % 4 == 0:
                    tags.append(f"late-{message_index}-{segment_index}-{tag_index}-wide-数据-עברית-終")
                else:
                    tags.append(
                        f"late-{message_index:03d}-{segment_index:02d}-{tag_index:02d}-"
                        + ("longtext" * (1 + ((message_index + tag_index) % 5)))
                    )
            segments.append(
                {
                    "ordinal": (0x80000000 + (message_index - 96) * 64 + segment_index) & 0xFFFFFFFF,
                    "checksum": signed32(-2000000000 + message_index * 65537 + segment_index * 8191),
                    "label": f"segment-{message_index:03d}-late-edge-{segment_index:02d}-pts-{point_count:02d}-λ数据",
                    "points": points,
                    "tags": tags,
                }
            )
        return segments
    if 128 <= message_index < 256:
        segment_count = 4 + (message_index % 11)
        segments = []
        for segment_index in range(segment_count):
            if (message_index + segment_index) % 9 == 0:
                point_count = 0
            else:
                point_count = ((message_index * 19 + segment_index * 23) % 73) + 1
            points = []
            for point_index in range(point_count):
                points.append(
                    {
                        "x": signed32(0x7FFFFFFF - message_index * 8191 - segment_index * 4093 - point_index * 127),
                        "y": signed32(-0x80000000 + message_index * 4099 + segment_index * 2053 + point_index * 251),
                        "z": signed32((message_index - 128) * 250000 - segment_index * 17001 + point_index * 65537),
                        "signal": signed32(0x80000000 + message_index * 997 + segment_index * 131 + point_index * 7),
                    }
                )
            tag_count = ((message_index * 3) + segment_index) % 17
            tags = []
            for tag_index in range(tag_count):
                if tag_index in {0, 5, 11} and (message_index + segment_index) % 2 == 0:
                    tags.append("")
                elif tag_index % 5 == 0:
                    tags.append(f"bulk-{message_index}-{segment_index}-{tag_index}-wide-東京-数据-مرحبا-данные")
                else:
                    tags.append(
                        f"bulk-{message_index:03d}-{segment_index:02d}-{tag_index:02d}-"
                        + ("capnptext" * (2 + ((message_index + segment_index + tag_index) % 6)))
                    )
            segments.append(
                {
                    "ordinal": (0x90000000 + (message_index - 128) * 96 + segment_index) & 0xFFFFFFFF,
                    "checksum": signed32(1800000000 - message_index * 131071 - segment_index * 32749),
                    "label": f"segment-{message_index:03d}-bulk-edge-{segment_index:02d}-pts-{point_count:02d}-東京-λ",
                    "points": points,
                    "tags": tags,
                }
            )
        return segments
    return None


def normalize_label(value):
    return value.strip().strip("\x00").strip().casefold()


def _sample_message_indexes(total_count):
    if total_count == 0:
        return []
    if total_count <= 4:
        return list(range(total_count))
    return [0, 1, 2, total_count // 4, total_count // 2, (3 * total_count) // 4, total_count - 1]


def expected_reference(message_count=None):
    if message_count is None:
        message_count = expected_message_count()

    rng = random.Random(492917)
    messages = []
    for message_index in range(message_count):
        edge = edge_segments(message_index)
        if edge is not None:
            segments = edge
        else:
            segment_count = 1 + (message_index % 5)
            segments = []
            for segment_index in range(segment_count):
                if message_index == 0 and segment_index == 0:
                    point_count = 0
                else:
                    point_count = 1 + ((message_index * 7 + segment_index * 3) % 15)
                points = []
                for point_index in range(point_count):
                    x = rng.randint(-5000, 5000) + message_index * 17 + point_index
                    y = rng.randint(-5000, 5000) - segment_index * 31 - point_index
                    points.append(
                        {
                            "x": x,
                            "y": y,
                            "z": x - y + segment_index,
                            "signal": (message_index * 97 + segment_index * 13 + point_index * 5) & 0xFFFF,
                        }
                    )
                checksum = signed32(
                    message_index * 1009 + segment_index * 131 + point_count * 17
                )
                tag_count = (message_index + segment_index) % 3
                tags = [f"tag-{message_index:02d}-{segment_index:02d}-{slot}" for slot in range(tag_count)]
                segments.append(
                    {
                        "ordinal": message_index * 10 + segment_index,
                        "checksum": checksum,
                        "label": segment_label(message_index, segment_index, point_count),
                        "points": points,
                        "tags": tags,
                    }
                )
        messages.append({"message_id": f"message-{message_index:02d}", "segments": segments})
    return messages


def load_json_from_output(text):
    payload = text.strip()
    if not payload:
        raise AssertionError("decoder produced no output")
    # Be forgiving if stdout includes framing/log lines around the JSON array.
    match = re.search(r"\[[\s\S]*\]\s*$", payload)
    assert match is not None, "decoder output did not contain a top-level JSON array"
    return json.loads(match.group(0))


def load_decoder():
    spec = importlib.util.spec_from_file_location("capnp_decoder_under_test", DECODER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def decode_messages():
    module = load_decoder()
    with tempfile.NamedTemporaryFile(delete=True) as temp:
        temp.write(HIDDEN_MESSAGES_PATH.read_bytes())
        temp.flush()
        return module.decode_file(temp.name)


def decode_hidden_cases():
    module = load_decoder()
    cases = json.loads(HIDDEN_CASES_PATH.read_text(encoding="utf-8"))
    decoded = []
    for case in cases:
        encoded = encode_verifier_only_message(case["segments"])
        decoded.append(module.decode_message(encoded, case["message_id"]))
    return decoded, cases


def pack_word(value):
    return struct.pack("<Q", value & 0xFFFFFFFFFFFFFFFF)


def signed_offset(value):
    return value & 0x3FFFFFFF


def struct_pointer(offset_words, data_words, pointer_words):
    return (
        KIND_STRUCT
        | (signed_offset(offset_words) << 2)
        | (data_words << 32)
        | (pointer_words << 48)
    )


def list_pointer(offset_words, element_size, count):
    return KIND_LIST | (signed_offset(offset_words) << 2) | (element_size << 32) | (count << 35)


def align8(data):
    return data + (b"\x00" * ((8 - (len(data) % 8)) % 8))


def encode_verifier_only_message(segments):
    words = [0, 0]
    segment_pointer_index = 1
    segment_words_per_element = 4
    total_segment_words = len(segments) * segment_words_per_element
    segment_list_start = len(words)
    words[segment_pointer_index] = list_pointer(
        segment_list_start - (segment_pointer_index + 1),
        LIST_COMPOSITE,
        total_segment_words,
    )
    words.append(struct_pointer(total_segment_words + 19, 1, 3))

    segment_slots = []
    for segment in segments:
        data_slot = len(words)
        segment_slots.append((len(words) + 1, len(words) + 2, len(words) + 3))
        words.extend([0, 0, 0, 0])
        words[data_slot] = (segment["ordinal"] & 0xFFFFFFFF) | ((segment["checksum"] & 0xFFFFFFFF) << 32)

    for segment, (point_slot, label_slot, tags_slot) in zip(segments, segment_slots):
        total_point_words = len(segment["points"]) * 2
        point_list_start = len(words)
        words[point_slot] = list_pointer(
            point_list_start - (point_slot + 1),
            LIST_COMPOSITE,
            total_point_words,
        )
        words.append(struct_pointer(total_point_words + 11, 2, 0))
        for point in segment["points"]:
            x = point["x"] & 0xFFFFFFFF
            y = point["y"] & 0xFFFFFFFF
            z = point["z"] & 0xFFFFFFFF
            signal = point["signal"] & 0xFFFFFFFF
            words.append(x | (y << 32))
            words.append(z | (signal << 32))

        label_bytes = segment["label"].encode("utf-8") + b"\x00"
        label_start = len(words)
        words[label_slot] = list_pointer(label_start - (label_slot + 1), LIST_BYTE, len(label_bytes))
        padded_label = align8(label_bytes)
        for index in range(0, len(padded_label), 8):
            words.append(struct.unpack("<Q", padded_label[index : index + 8])[0])

        tags = segment.get("tags", [])
        tags_list_start = len(words)
        words[tags_slot] = list_pointer(tags_list_start - (tags_slot + 1), LIST_POINTER, len(tags))
        tag_pointer_slots = list(range(len(words), len(words) + len(tags)))
        words.extend([0] * len(tags))
        for tag_slot, tag in zip(tag_pointer_slots, tags):
            tag_bytes = tag.encode("utf-8") + b"\x00"
            tag_start = len(words)
            words[tag_slot] = list_pointer(tag_start - (tag_slot + 1), LIST_BYTE, len(tag_bytes))
            padded_tag = align8(tag_bytes)
            for index in range(0, len(padded_tag), 8):
                words.append(struct.unpack("<Q", padded_tag[index : index + 8])[0])

    words[0] = struct_pointer(0, 0, 1)
    segment_bytes = b"".join(pack_word(word) for word in words)
    return struct.pack("<II", 0, len(words)) + segment_bytes


def build_stream(messages):
    stream = bytearray(MAGIC)
    stream.extend(struct.pack("<I", len(messages)))
    for message in messages:
        stream.extend(struct.pack("<I", len(message)))
        stream.extend(message)
    return bytes(stream)


def _expected_metrics_from_reference(messages):
    segment_count = sum(len(message["segments"]) for message in messages)
    point_count = sum(len(segment["points"]) for message in messages for segment in message["segments"])
    max_points_in_message = max((sum(len(segment["points"]) for segment in message["segments"]) for message in messages), default=0)
    max_points_in_segment = max((len(segment["points"]) for message in messages for segment in message["segments"]), default=0)
    avg_points_per_message = (point_count / len(messages)) if messages else 0.0
    histogram = {}
    for message in messages:
        for segment in message["segments"]:
            key = str(len(segment["points"]))
            histogram[key] = histogram.get(key, 0) + 1
    return {
        "message_count": len(messages),
        "segment_count": segment_count,
        "point_count": point_count,
        "max_points_in_message": max_points_in_message,
        "max_points_in_segment": max_points_in_segment,
        "avg_points_per_message": avg_points_per_message,
        "segment_point_histogram": histogram,
    }


def _expected_outer_offsets(message_count):
    stream = HIDDEN_MESSAGES_PATH.read_bytes()
    cursor = len(MAGIC) + 4
    size_offsets = []
    starts = []
    ends = []
    for _ in range(message_count):
        size_offsets.append(cursor)
        size = struct.unpack_from("<I", stream, cursor)[0]
        cursor += 4
        start = cursor
        end = start + size
        starts.append(start)
        ends.append(end)
        cursor = end
    return size_offsets, starts, ends


def _canonical_diagnostics(diagnostics):
    event_keys = {
        "message_index",
        "message_id",
        "segment_count",
        "point_count",
        "max_points_in_segment",
        "segment_point_counts",
        "size_prefix_offset",
        "byte_start",
        "byte_end",
        "message_bytes",
        "message_crc32",
    }
    return {
        "api_version": diagnostics["api_version"],
        "raw_bytes": diagnostics["raw_bytes"],
        "message_count": diagnostics["message_count"],
        "segment_count": diagnostics["segment_count"],
        "point_count": diagnostics["point_count"],
        "max_points_in_message": diagnostics["max_points_in_message"],
        "max_points_in_segment": diagnostics["max_points_in_segment"],
        "avg_points_per_message": diagnostics["avg_points_per_message"],
        "segment_point_histogram": diagnostics["segment_point_histogram"],
        "point_count_per_message": diagnostics["point_count_per_message"],
        "stream_crc32": diagnostics["stream_crc32"],
        "events": [{key: event[key] for key in event_keys} for event in diagnostics["events"]],
    }


def test_stream_header_and_payload_integrity_is_self_consistent():
    """Validate the outer stream wrapper before any decoding assumptions are made."""
    raw = HIDDEN_MESSAGES_PATH.read_bytes()
    assert raw.startswith(MAGIC)
    count = struct.unpack_from("<I", raw, len(MAGIC))[0]
    assert count == expected_message_count()

    decoder = load_decoder()
    with tempfile.NamedTemporaryFile(delete=True) as temp:
        temp.write(raw)
        temp.flush()
        messages = decoder.read_message_stream(temp.name)
    assert len(messages) == count
    assert all(len(message) > 8 for message in messages)


def test_visible_message_stream_matches_verifier_copy():
    """Keep the agent-visible stream unchanged so verifier expectations come from trusted data."""
    visible = MESSAGES_PATH.read_bytes()
    trusted = HIDDEN_MESSAGES_PATH.read_bytes()
    assert hashlib.sha256(visible).digest() == hashlib.sha256(trusted).digest()


def test_decoded_output_matches_trusted_reference_shape():
    """Validate every visible message against the deterministic reference generated from the fixed seed."""
    expected = expected_reference()
    decoded = decode_messages()
    assert len(decoded) == len(expected)
    assert decoded == expected


def test_decode_pipeline_parity_and_diagnostics_path():
    """Keep legacy `decode_file` output aligned with the diagnostics pipeline API."""
    module = load_decoder()
    expected = expected_reference()
    legacy = decode_messages()
    staged = module.decode_file_with_metrics(str(HIDDEN_MESSAGES_PATH), max_workers=1)

    assert staged["messages"] == expected
    assert staged["messages"] == legacy
    diagnostics = staged["diagnostics"]
    assert isinstance(diagnostics, dict)
    expected_metrics = _expected_metrics_from_reference(expected)
    assert diagnostics["api_version"] == "2.0"
    assert diagnostics["raw_bytes"] == HIDDEN_MESSAGES_PATH.stat().st_size
    assert diagnostics["message_count"] == expected_metrics["message_count"]
    assert diagnostics["segment_count"] == expected_metrics["segment_count"]
    assert diagnostics["point_count"] == expected_metrics["point_count"]
    assert diagnostics["max_points_in_message"] == expected_metrics["max_points_in_message"]
    assert diagnostics["max_points_in_segment"] == expected_metrics["max_points_in_segment"]
    expected_point_counts = [sum(len(segment["points"]) for segment in message["segments"]) for message in expected]
    assert diagnostics["segment_point_histogram"] == expected_metrics["segment_point_histogram"]
    assert diagnostics["point_count_per_message"] == expected_point_counts
    assert abs(diagnostics["avg_points_per_message"] - expected_metrics["avg_points_per_message"]) < 1e-9
    assert diagnostics["point_count_per_message"] and sum(diagnostics["point_count_per_message"]) == expected_metrics["point_count"]
    assert diagnostics["decode_ms_per_message"] and len(diagnostics["decode_ms_per_message"]) == expected_metrics["message_count"]
    assert diagnostics["decode_ms_per_message"][0] <= diagnostics["max_decode_ms_per_message"]
    assert "elapsed_ms" in diagnostics and diagnostics["elapsed_ms"] >= 0
    assert diagnostics["stream_crc32"] == (zlib.crc32(HIDDEN_MESSAGES_PATH.read_bytes()) & 0xFFFFFFFF)
    assert diagnostics["worker_count"] == 1
    assert diagnostics["events"] and len(diagnostics["events"]) == len(expected)


def test_decode_pipeline_events_are_reproducible_and_structured():
    """Verify diagnostics are deterministic, ordered, and include stable per-message offsets."""
    module = load_decoder()
    expected = expected_reference()
    expected_by_id = {message["message_id"]: index for index, message in enumerate(expected)}
    staged = module.decode_file_with_metrics(str(HIDDEN_MESSAGES_PATH), max_workers=1)
    diagnostics = staged["diagnostics"]

    events = diagnostics["events"]
    assert len(events) == len(expected)
    starts = [event["byte_start"] for event in events]
    ends = [event["byte_end"] for event in events]
    assert starts == sorted(starts)
    assert all(end > start for start, end in zip(starts, ends))
    assert all(event["byte_end"] - event["byte_start"] == event["message_bytes"] for event in events)

    expected_size_offsets, expected_starts, expected_ends = _expected_outer_offsets(len(expected))

    assert [event["size_prefix_offset"] for event in events] == expected_size_offsets
    assert [event["byte_start"] for event in events] == expected_starts
    assert [event["byte_end"] for event in events] == expected_ends
    raw_stream = HIDDEN_MESSAGES_PATH.read_bytes()
    assert [event["message_crc32"] for event in events] == [
        zlib.crc32(raw_stream[start:end]) & 0xFFFFFFFF for start, end in zip(expected_starts, expected_ends)
    ]
    assert [event["segment_point_counts"] for event in events] == [
        [len(segment["points"]) for segment in message["segments"]] for message in expected
    ]

    for event in events:
        assert event["message_index"] == expected_by_id[event["message_id"]]

    second = module.decode_file_with_metrics(str(HIDDEN_MESSAGES_PATH), max_workers=1)
    assert staged["messages"] == second["messages"]
    assert _canonical_diagnostics(staged["diagnostics"]) == _canonical_diagnostics(second["diagnostics"])


def test_decode_with_custom_message_ids_reports_diagnostics_state():
    """Validate override message identifiers and require unique ids for deterministic event ordering."""
    module = load_decoder()
    expected = decode_hidden_cases()
    cases = expected[1]
    encoded = [encode_verifier_only_message(case["segments"]) for case in cases]
    stream = build_stream(encoded)

    custom_ids = [f"custom-{index:02d}" for index in range(len(cases))]
    with tempfile.NamedTemporaryFile(delete=True) as temp:
        temp.write(stream)
        temp.flush()
        staged = module.decode_file_with_metrics(temp.name, message_ids=custom_ids, max_workers=2)
        assert [message["message_id"] for message in staged["messages"]] == custom_ids
        assert [event["message_id"] for event in staged["diagnostics"]["events"]] == custom_ids

        with pytest.raises(module.DecodeError):
            module.decode_file_with_metrics(temp.name, message_ids=["dup-id"] * len(cases))


def test_decode_file_with_metrics_reports_actual_crc32_for_custom_stream_messages():
    """Per-message CRC32 diagnostics should be computed from each encoded message, not filled with placeholders."""
    module = load_decoder()
    _decoded, cases = decode_hidden_cases()
    selected_cases = [cases[index] for index in (0, 4, 7, 10)]
    encoded = [encode_verifier_only_message(case["segments"]) for case in selected_cases]
    stream = build_stream(encoded)

    with tempfile.NamedTemporaryFile(delete=True) as temp:
        temp.write(stream)
        temp.flush()
        staged = module.decode_file_with_metrics(temp.name, max_workers=3)

    assert staged["diagnostics"]["stream_crc32"] == (zlib.crc32(stream) & 0xFFFFFFFF)
    assert [event["message_crc32"] for event in staged["diagnostics"]["events"]] == [
        zlib.crc32(message) & 0xFFFFFFFF for message in encoded
    ]
    assert all(event["message_crc32"] != 0 for event in staged["diagnostics"]["events"])


def test_decode_with_parallel_and_single_worker_produce_identical_output_and_metrics_profile():
    """Demand full parity between worker counts while still reflecting concurrency in diagnostics."""
    module = load_decoder()

    staged_single = module.decode_file_with_metrics(str(HIDDEN_MESSAGES_PATH), max_workers=1)
    staged_multi = module.decode_file_with_metrics(str(HIDDEN_MESSAGES_PATH), max_workers=3)

    assert staged_single["messages"] == staged_multi["messages"]
    assert staged_multi["diagnostics"]["worker_count"] == 3
    assert staged_multi["diagnostics"]["message_count"] == staged_single["diagnostics"]["message_count"]
    assert staged_multi["diagnostics"]["point_count"] == staged_single["diagnostics"]["point_count"]
    assert [event["message_id"] for event in staged_single["diagnostics"]["events"]] == [
        event["message_id"] for event in staged_multi["diagnostics"]["events"]
    ]
    assert staged_multi["diagnostics"]["max_decode_ms_per_message"] >= 0.0


def test_decode_with_worker_id_matrix_preserves_payload_and_event_invariants():
    """Exercise worker-count and message-id matrix combinations without changing parsed content."""
    module = load_decoder()
    expected = expected_reference()
    expected_size_offsets, expected_starts, expected_ends = _expected_outer_offsets(len(expected))
    expected_point_counts = [sum(len(segment["points"]) for segment in message["segments"]) for message in expected]
    expected_segments = [message["segments"] for message in expected]
    default_ids = [message["message_id"] for message in expected]

    observed_payloads = None
    for worker_count in (1, 2, 4):
        for custom_ids in (None, [f"matrix-{index:02d}" for index in range(len(expected))]):
            staged = module.decode_file_with_metrics(str(HIDDEN_MESSAGES_PATH), max_workers=worker_count, message_ids=custom_ids)
            diagnostics = staged["diagnostics"]
            messages = staged["messages"]

            assert diagnostics["worker_count"] == worker_count
            assert diagnostics["message_count"] == len(expected)
            assert diagnostics["point_count"] == sum(expected_point_counts)
            assert diagnostics["point_count_per_message"] == expected_point_counts
            assert [event["segment_count"] for event in diagnostics["events"]] == [len(segments) for segments in expected_segments]
            assert [event["point_count"] for event in diagnostics["events"]] == expected_point_counts
            assert [event["size_prefix_offset"] for event in diagnostics["events"]] == expected_size_offsets
            assert [event["byte_start"] for event in diagnostics["events"]] == expected_starts
            assert [event["byte_end"] for event in diagnostics["events"]] == expected_ends
            assert [event["message_index"] for event in diagnostics["events"]] == list(range(len(expected)))

            event_ids = [event["message_id"] for event in diagnostics["events"]]
            message_ids = [message["message_id"] for message in messages]
            if custom_ids is None:
                assert message_ids == default_ids
                assert event_ids == default_ids
            else:
                assert message_ids == custom_ids
                assert event_ids == custom_ids
                assert any(message_id != default_id for message_id, default_id in zip(message_ids, default_ids))

            payloads = [message["segments"] for message in messages]
            assert payloads == expected_segments

            if observed_payloads is None:
                observed_payloads = payloads
            else:
                assert payloads == observed_payloads

            assert len(diagnostics["decode_ms_per_message"]) == len(expected)
            assert all(entry >= 0.0 for entry in diagnostics["decode_ms_per_message"])


def test_decoded_messages_are_well_formed_with_critical_field_coverage():
    """Validate shape invariants without rejecting minor string-format differences."""
    decoded = decode_messages()
    expected_count = expected_message_count()
    assert len(decoded) == expected_count

    for index, message in enumerate(decoded):
        assert message["message_id"].strip().casefold() == f"message-{index:02d}"
        assert isinstance(message["segments"], list)
        for segment in message["segments"]:
            assert isinstance(segment["ordinal"], int)
            assert isinstance(segment["checksum"], int)
            assert "label" in segment and isinstance(segment["label"], str)
            assert "points" in segment and isinstance(segment["points"], list)
            assert "tags" in segment and isinstance(segment["tags"], list)
            assert all(isinstance(tag, str) for tag in segment["tags"])
            for point in segment["points"]:
                assert {"x", "y", "z", "signal"}.issubset(point.keys())


def test_segment_label_text_is_normalized():
    """Handle minor trailing whitespace/casing variation while still validating decoded text semantics."""
    decoded = decode_messages()
    for message_index, message in enumerate(decoded[: min(6, len(decoded))]):
        for segment_index, segment in enumerate(message["segments"]):
            expected = segment_label(message_index, segment_index, len(segment["points"]))
            assert normalize_label(segment["label"]) == normalize_label(expected)


def test_messages_are_consistent_and_sequentially_identified():
    """Ensure IDs and message ordering are fully preserved from the stream."""
    decoded = decode_messages()
    assert len(decoded) == expected_message_count()
    expected_ids = [f"message-{index:02d}" for index in range(len(decoded))]
    assert [message["message_id"] for message in decoded] == expected_ids


def test_decode_file_is_stable_across_imports():
    """Decoder output should be deterministic and independent of repeated module execution."""
    assert decode_messages() == decode_messages()


def test_point_composite_lists_keep_exact_element_counts():
    """Keep exact nested point counts for representative messages with wider, deeper payloads."""
    decoded = decode_messages()
    expected = expected_reference()
    for message_index in (1, 6, 11, 19, 24, 47):
        for segment_index, segment in enumerate(expected[message_index]["segments"]):
            assert decoded[message_index]["segments"][segment_index]["points"] == segment["points"]
            assert len(decoded[message_index]["segments"][segment_index]["points"]) == len(segment["points"])


def test_multi_word_segment_composite_lists_use_total_words_divided_by_struct_size():
    """Use list total-word semantics to recover segment element counts instead of trusting raw count fields."""
    decoded = decode_messages()
    expected = expected_reference()
    for message_index in (4, 10, 16, 23, 31):
        assert len(decoded[message_index]["segments"]) == len(expected[message_index]["segments"])
        assert [segment["label"] for segment in decoded[message_index]["segments"]] == [
            segment["label"] for segment in expected[message_index]["segments"]
        ]


def test_nested_point_field_values_are_preserved():
    """Verify representative nested Point scalar values because list counts alone miss struct-word corruption."""
    decoded = decode_messages()
    expected = expected_reference()
    checks = [(6, 1, 0), (7, 1, 5), (13, 3, 9), (23, 1, 14), (34, 4, 0)]
    for message_index, segment_index, point_index in checks:
        assert (
            decoded[message_index]["segments"][segment_index]["points"][point_index]
            == expected[message_index]["segments"][segment_index]["points"][point_index]
        )


def test_text_labels_decode_as_utf8_without_nul_padding():
    """Ensure Text fields decode as clean UTF-8 labels and include the variable-width payload cases."""
    decoded = decode_messages()
    expected = expected_reference()
    for message, expected_message in zip(decoded, expected):
        for segment, expected_segment in zip(message["segments"], expected_message["segments"]):
            assert segment["label"] == expected_segment["label"]
            assert "\x00" not in segment["label"]


def test_visible_corpus_covers_boundary_scalars_and_multword_text():
    """Validate generated edge messages with scalar boundaries, dense point lists, and multi-word text."""
    decoded = decode_messages()
    expected = expected_reference()

    assert decoded[45] == {"message_id": "message-45", "segments": []}
    assert decoded[46] == expected[46]
    assert decoded[47] == expected[47]
    for message_index in range(88, 96):
        assert decoded[message_index] == expected[message_index]
    for message_index in (96, 103, 111, 119, 127):
        assert decoded[message_index] == expected[message_index]
    for message_index in (128, 149, 173, 211, 255):
        assert decoded[message_index] == expected[message_index]

    edge_segment = decoded[46]["segments"][0]
    assert edge_segment["ordinal"] == 0xFFFFFFFF
    assert edge_segment["checksum"] == -2147483648
    assert edge_segment["points"][1] == {
        "x": 2147483647,
        "y": -2147483648,
        "z": -2147483648,
        "signal": 2147483647,
    }
    assert edge_segment["tags"][0] == ""
    assert "终" in edge_segment["tags"][1]
    assert len(edge_segment["tags"][2].encode("utf-8")) > 40

    dense_segment = decoded[47]["segments"][2]
    assert dense_segment["ordinal"] == 3000000000
    assert len(dense_segment["points"]) == 17
    assert dense_segment["points"][-1]["signal"] == signed32(0x80000000 + 16)
    assert any("مرحبا" in tag for tag in dense_segment["tags"])

    large_segment = decoded[89]["segments"][0]
    assert len(large_segment["points"]) == 29
    assert len(large_segment["tags"]) == 18
    assert large_segment["points"][0]["signal"] == 2147483647
    assert "κλμν" in large_segment["label"]

    mixed_message = decoded[90]
    assert [len(segment["points"]) for segment in mixed_message["segments"]] == [0, 1, 2, 8, 16, 33]
    assert mixed_message["segments"][0]["tags"] == [""]
    assert mixed_message["segments"][5]["points"][-1]["signal"] == signed32(0x80000000 + 5 * 257 + 32)

    bulk_segment = decoded[91]["segments"][0]
    assert len(bulk_segment["points"]) == 64
    assert bulk_segment["ordinal"] == 4000000000
    assert bulk_segment["tags"][2] == ""
    assert "数据" in bulk_segment["label"]

    assert decoded[93]["segments"][0]["tags"] == [""] * 12
    assert decoded[94]["segments"][-1]["ordinal"] == 4294967294

    late_message = decoded[127]
    assert len(late_message["segments"]) == 3
    assert late_message["segments"][0]["ordinal"] > 0x80000000
    assert any(tag == "" for segment in late_message["segments"] for tag in segment["tags"])
    assert any("数据" in segment["label"] for segment in late_message["segments"])

    point_heavy = decoded[255]
    assert len(point_heavy["segments"]) == 6
    assert point_heavy["segments"][0]["ordinal"] > 0x90000000
    assert any(len(segment["points"]) > 60 for segment in point_heavy["segments"])

    tag_heavy = decoded[254]
    assert any(len(segment["tags"]) > 10 for segment in tag_heavy["segments"])
    assert any(tag == "" for segment in tag_heavy["segments"] for tag in segment["tags"])


def test_empty_segment_lists_are_supported():
    """Decoder must support messages where segments can be empty, not just non-empty defaults."""
    module = load_decoder()
    encoded = encode_verifier_only_message([])
    decoded = module.decode_message(encoded, "empty-message")
    assert decoded["message_id"] == "empty-message"
    assert decoded["segments"] == []


def test_hidden_cases_are_decoded_correctly():
    """Validate hidden verifier cases that are stored outside agent-visible paths."""
    decoded, expected = decode_hidden_cases()
    assert len(decoded) == len(expected)

    for decoded_message, expected_message in zip(decoded, expected):
        assert decoded_message == expected_message


def test_hidden_cases_and_visible_reference_pass_exhaustive_shape_audit():
    """Cross-validate every known shape value for both visible and hidden verification fixtures."""
    expected = expected_reference()
    decoded = decode_messages()
    hidden_decoded, hidden_expected = decode_hidden_cases()
    assert decoded == expected
    assert hidden_decoded == hidden_expected


def test_round_trip_stream_and_message_reconstruction_is_stable():
    """Round-trip hidden fixtures through encoded streams and single-message decodes to enforce parser stability."""
    module = load_decoder()
    expected = expected_reference()
    for message_index in _sample_message_indexes(len(expected)):
        source = expected[message_index]
        encoded = encode_verifier_only_message(source["segments"])
        reconstructed = module.decode_message(encoded, source["message_id"])
        assert reconstructed == source


def test_decoded_payload_is_reused_without_mutation_leaks():
    """Confirm returned payloads are not shared across call boundaries and can be mutated safely."""
    first = decode_messages()
    first[1]["segments"][0]["points"][0]["x"] = 7_777_777

    second = decode_messages()
    assert second[1]["segments"][0]["points"][0]["x"] != 7_777_777


def test_decode_with_parallel_workers_preserves_output_and_updates_diagnostics():
    """Parallel decode must preserve exact output order and include worker-aware diagnostics."""
    module = load_decoder()

    staged_single = module.decode_file_with_metrics(str(HIDDEN_MESSAGES_PATH), max_workers=1)
    staged_multi = module.decode_file_with_metrics(str(HIDDEN_MESSAGES_PATH), max_workers=4)

    assert staged_multi["messages"] == staged_single["messages"]
    assert staged_multi["diagnostics"]["worker_count"] == 4
    assert staged_multi["diagnostics"]["message_count"] == staged_single["diagnostics"]["message_count"]
    assert staged_multi["diagnostics"]["point_count"] == staged_single["diagnostics"]["point_count"]


def test_decode_path_is_thread_safe_when_reused_concurrently():
    """Shared module usage across threads should remain stateless and deterministic."""
    module = load_decoder()
    baseline = expected_message_count()

    def worker_run():
        result = module.decode_file_with_metrics(str(HIDDEN_MESSAGES_PATH), max_workers=2)
        return result["diagnostics"]["message_count"]

    with ThreadPoolExecutor(max_workers=4) as executor:
        counts = [future.result() for future in [executor.submit(worker_run) for _ in range(4)]]

    assert all(count == baseline for count in counts)


def test_decode_pipeline_resource_metadata_matches_payload_shape():
    """Validate resource-related diagnostics through corpus-derived counts instead of wall-clock timing."""
    module = load_decoder()
    expected = expected_reference()
    expected_metrics = _expected_metrics_from_reference(expected)

    result = module.decode_file_with_metrics(str(HIDDEN_MESSAGES_PATH), max_workers=2)

    assert result["diagnostics"]["message_count"] == expected_metrics["message_count"]
    assert result["diagnostics"]["max_points_in_message"] == expected_metrics["max_points_in_message"]
    assert result["diagnostics"]["segment_point_histogram"] == expected_metrics["segment_point_histogram"]
    assert result["diagnostics"]["worker_count"] == 2
    assert len(result["diagnostics"]["decode_ms_per_message"]) == expected_metrics["message_count"]
    assert result["diagnostics"]["max_decode_ms_per_message"] >= 0.0


def test_hidden_cases_cover_empty_and_unicode_edges():
    """Spot-check hidden cases include empty segment lists and non-ascii labels."""
    decoded, _ = decode_hidden_cases()
    assert any(message["message_id"] == "hidden-03" and message["segments"] == [] for message in decoded)
    assert any(
        any("μ" in segment["label"] for segment in message["segments"]) for message in decoded
    )
    dense = next(message for message in decoded if message["message_id"] == "hidden-06")
    assert dense["segments"][0]["ordinal"] == 4294967294
    assert dense["segments"][0]["checksum"] == -2147483647
    assert len(dense["segments"][0]["points"]) == 5
    assert dense["segments"][0]["points"][0]["x"] == -2147483648
    assert dense["segments"][0]["tags"][0] == ""
    assert any("タグ" in tag for tag in dense["segments"][0]["tags"])

    large = next(message for message in decoded if message["message_id"] == "hidden-07")
    assert large["segments"][0]["ordinal"] == 4000000001
    assert len(large["segments"][0]["points"]) == 13
    assert len(large["segments"][0]["tags"]) == 6
    assert large["segments"][0]["points"][-1]["signal"] == -2147483648

    mixed = next(message for message in decoded if message["message_id"] == "hidden-08")
    assert [len(segment["points"]) for segment in mixed["segments"]] == [0, 1, 8]
    assert mixed["segments"][2]["ordinal"] == 4294967295
    assert mixed["segments"][2]["tags"][2] == ""

    heavy_text = next(message for message in decoded if message["message_id"] == "hidden-09")
    assert heavy_text["segments"][0]["ordinal"] == 4294967295
    assert len(heavy_text["segments"][0]["points"]) == 10
    assert len(heavy_text["segments"][1]["tags"]) == 6
    assert all(tag == "" for tag in heavy_text["segments"][1]["tags"])

    dense_tags = next(message for message in decoded if message["message_id"] == "hidden-10")
    assert len(dense_tags["segments"][1]["tags"]) == 16
    assert dense_tags["segments"][0]["tags"][2] == ""
    assert "東京" in dense_tags["segments"][0]["tags"][3]

    wide_bulk = next(message for message in decoded if message["message_id"] == "hidden-11")
    assert len(wide_bulk["segments"][0]["points"]) == 16
    assert len(wide_bulk["segments"][0]["tags"]) == 9
    assert wide_bulk["segments"][0]["tags"][0] == ""
    assert wide_bulk["segments"][1]["tags"] == [""] * 8

    varied = next(message for message in decoded if message["message_id"] == "hidden-12")
    assert [len(segment["points"]) for segment in varied["segments"]] == [0, 1, 4]
    assert len(varied["segments"][2]["tags"]) == 15
    assert varied["segments"][2]["tags"][13] == ""

    layered = next(message for message in decoded if message["message_id"] == "hidden-13")
    assert len(layered["segments"]) == 7
    assert layered["segments"][0]["tags"] == [""]
    assert len(layered["segments"][6]["points"]) == 18
    assert "数据" in layered["segments"][3]["label"]

    dense_extra = next(message for message in decoded if message["message_id"] == "hidden-14")
    assert len(dense_extra["segments"][0]["points"]) == 83
    assert len(dense_extra["segments"][0]["tags"]) == 25
    assert dense_extra["segments"][0]["tags"][0] == ""
    assert dense_extra["segments"][0]["points"][-1]["signal"] == signed32(0x80000000 + 82 * 97)

    mixed_extra = next(message for message in decoded if message["message_id"] == "hidden-15")
    assert len(mixed_extra["segments"]) == 12
    assert [len(mixed_extra["segments"][index]["points"]) for index in (0, 5, 9)] == [0, 0, 0]
    assert any("עברית" in tag for segment in mixed_extra["segments"] for tag in segment["tags"])


def test_read_message_stream_rejects_truncated_bytes():
    """Truncation in the outer stream should fail early and not yield silent partial payloads."""
    module = load_decoder()
    raw = bytearray(HIDDEN_MESSAGES_PATH.read_bytes())
    truncated = bytes(raw[:-7])

    with tempfile.NamedTemporaryFile(delete=True) as temp:
        temp.write(truncated)
        temp.flush()
        with pytest.raises(module.DecodeError):
            module.read_message_stream(temp.name)


def test_read_message_stream_rejects_wrong_magic():
    """Invalid magic bytes must not be interpreted as a valid stream."""
    module = load_decoder()
    raw = bytearray(HIDDEN_MESSAGES_PATH.read_bytes())
    raw[:3] = b"BAD"

    with tempfile.NamedTemporaryFile(delete=True) as temp:
        temp.write(raw)
        temp.flush()
        with pytest.raises(module.DecodeError):
            module.read_message_stream(temp.name)


def test_decode_empty_stream_reports_zero_diagnostics():
    """A valid stream with no entries should return empty payloads and coherent zero diagnostics."""
    module = load_decoder()
    raw = MAGIC + struct.pack("<I", 0)

    with tempfile.NamedTemporaryFile(delete=True) as temp:
        temp.write(raw)
        temp.flush()
        result = module.decode_file_with_metrics(temp.name, max_workers=3)

    assert result["messages"] == []
    diagnostics = result["diagnostics"]
    assert diagnostics["raw_bytes"] == len(raw)
    assert diagnostics["message_count"] == 0
    assert diagnostics["segment_count"] == 0
    assert diagnostics["point_count"] == 0
    assert diagnostics["max_points_in_message"] == 0
    assert diagnostics["max_points_in_segment"] == 0
    assert diagnostics["avg_points_per_message"] == 0.0
    assert diagnostics["segment_point_histogram"] == {}
    assert diagnostics["point_count_per_message"] == []
    assert diagnostics["decode_ms_per_message"] == []
    assert diagnostics["max_decode_ms_per_message"] == 0.0
    assert diagnostics["worker_count"] == 3
    assert diagnostics["events"] == []
    assert diagnostics["stream_crc32"] == (zlib.crc32(raw) & 0xFFFFFFFF)
    assert diagnostics["elapsed_ms"] >= 0.0


def test_decode_message_rejects_segment_list_not_composite():
    """Composing against a non-composite segment list should fail deterministically."""
    module = load_decoder()
    message = bytearray(encode_verifier_only_message([]))
    # mutate the segment list pointer at word 1 from composite to byte list
    corrupted_pointer = KIND_LIST | (1 << 2) | (LIST_BYTE << 32) | (4 << 35)
    message[16:24] = struct.pack("<Q", corrupted_pointer)
    with pytest.raises(module.DecodeError):
        module.decode_message(bytes(message))


def test_decode_message_rejects_composite_lists_with_partial_struct_words():
    """Composite list word budgets must divide exactly by the struct stride to avoid silent truncation."""
    module = load_decoder()

    two_segments = [
        {"ordinal": 4100, "checksum": -123, "label": "budget-check-a", "points": [{"x": 1, "y": -2, "z": 3, "signal": 4}], "tags": []},
        {"ordinal": 9001, "checksum": 55, "label": "budget-check-b", "points": [{"x": 9, "y": -9, "z": 9, "signal": 9}], "tags": []},
    ]
    segment_budget_corruption = bytearray(encode_verifier_only_message(two_segments))
    segment_pointer = struct.unpack_from("<Q", segment_budget_corruption, 16)[0]
    segment_budget_corruption[16:24] = struct.pack(
        "<Q",
        (segment_pointer & ~(((1 << 29) - 1) << 35)) | (5 << 35),
    )
    with pytest.raises(module.DecodeError):
        module.decode_message(bytes(segment_budget_corruption))

    two_points = [
        {
            "ordinal": 1,
            "checksum": 1,
            "label": "p",
            "points": [
                {"x": 1, "y": 1, "z": 1, "signal": 1},
                {"x": 2, "y": 2, "z": 2, "signal": 2},
            ],
            "tags": [],
        }
    ]
    point_budget_corruption = bytearray(encode_verifier_only_message(two_points))
    point_pointer_offset = 8 + (4 * 8)
    point_pointer = struct.unpack_from("<Q", point_budget_corruption, point_pointer_offset)[0]
    point_budget_corruption[point_pointer_offset : point_pointer_offset + 8] = struct.pack(
        "<Q",
        (point_pointer & ~(((1 << 29) - 1) << 35)) | (3 << 35),
    )
    with pytest.raises(module.DecodeError):
        module.decode_message(bytes(point_budget_corruption))


def test_decode_message_rejects_non_struct_root_pointer():
    """A non-struct root pointer should fail with DecodeError rather than partial decoding."""
    module = load_decoder()
    message = bytearray(encode_verifier_only_message([]))
    # flip root pointer to a list pointer (low two bits = 1) while keeping the stream shape otherwise valid
    message[8:16] = struct.pack("<Q", 1)
    with pytest.raises(module.DecodeError):
        module.decode_message(bytes(message))


def test_decode_message_rejects_wrong_struct_layouts_inside_composite_lists():
    """Composite tags with the wrong inline struct layouts should fail before field traversal."""
    module = load_decoder()
    source = [
        {
            "ordinal": 99,
            "checksum": -99,
            "label": "layout-check",
            "points": [{"x": 1, "y": 2, "z": 3, "signal": 4}],
            "tags": ["layout-tag"],
        }
    ]

    segment_layout_corruption = bytearray(encode_verifier_only_message(source))
    segment_tag_offset = 8 + (2 * 8)
    segment_tag = struct.unpack_from("<Q", segment_layout_corruption, segment_tag_offset)[0]
    segment_layout_corruption[segment_tag_offset : segment_tag_offset + 8] = struct.pack(
        "<Q",
        (segment_tag & ~((0xFFFF << 32) | (0xFFFF << 48))) | (2 << 32) | (2 << 48),
    )
    with pytest.raises(module.DecodeError):
        module.decode_message(bytes(segment_layout_corruption))

    point_layout_corruption = bytearray(encode_verifier_only_message(source))
    point_tag_offset = 8 + (7 * 8)
    point_tag = struct.unpack_from("<Q", point_layout_corruption, point_tag_offset)[0]
    point_layout_corruption[point_tag_offset : point_tag_offset + 8] = struct.pack(
        "<Q",
        (point_tag & ~((0xFFFF << 32) | (0xFFFF << 48))) | (1 << 32) | (1 << 48),
    )
    with pytest.raises(module.DecodeError):
        module.decode_message(bytes(point_layout_corruption))

    extra_segment_pointer_words = bytearray(encode_verifier_only_message(source))
    segment_tag = struct.unpack_from("<Q", extra_segment_pointer_words, segment_tag_offset)[0]
    extra_segment_pointer_words[segment_tag_offset : segment_tag_offset + 8] = struct.pack(
        "<Q",
        (segment_tag & ~(0xFFFF << 48)) | (4 << 48),
    )
    with pytest.raises(module.DecodeError):
        module.decode_message(bytes(extra_segment_pointer_words))

    extra_point_data_word = bytearray(encode_verifier_only_message(source))
    point_tag = struct.unpack_from("<Q", extra_point_data_word, point_tag_offset)[0]
    extra_point_data_word[point_tag_offset : point_tag_offset + 8] = struct.pack(
        "<Q",
        (point_tag & ~(0xFFFF << 32)) | (3 << 32),
    )
    with pytest.raises(module.DecodeError):
        module.decode_message(bytes(extra_point_data_word))


def test_decode_message_rejects_short_segment_table():
    """Single-message decoding should reject payloads too short for a Cap'n Proto segment table."""
    module = load_decoder()
    with pytest.raises(module.DecodeError):
        module.decode_message(b"\x00" * 7)


def test_decode_message_rejects_malformed_segment_label_text():
    """Segment labels should reject malformed text instead of returning padded or partial strings."""
    module = load_decoder()
    source = [
        {
            "ordinal": 88,
            "checksum": -88,
            "label": "label-shape",
            "points": [{"x": 5, "y": -5, "z": 10, "signal": -10}],
            "tags": [],
        }
    ]
    message = bytearray(encode_verifier_only_message(source))
    label_pointer_offset = 8 + (5 * 8)
    label_pointer = struct.unpack_from("<Q", message, label_pointer_offset)[0]
    label_text_start = 5 + 1 + ((label_pointer >> 2) & 0x3FFFFFFF)
    label_text_byte_offset = 8 + (label_text_start * 8)
    message[label_text_byte_offset + len("label-shape")] = ord("!")

    with pytest.raises(module.DecodeError):
        module.decode_message(bytes(message))

    utf8_corruption = bytearray(encode_verifier_only_message(source))
    utf8_label_pointer = struct.unpack_from("<Q", utf8_corruption, label_pointer_offset)[0]
    utf8_label_text_start = 5 + 1 + ((utf8_label_pointer >> 2) & 0x3FFFFFFF)
    utf8_label_text_byte_offset = 8 + (utf8_label_text_start * 8)
    utf8_corruption[utf8_label_text_byte_offset] = 0x80

    with pytest.raises(module.DecodeError):
        module.decode_message(bytes(utf8_corruption))


def test_decode_message_rejects_segment_label_text_pointer_shape_and_budget():
    """Segment labels should fail when their Text pointer shape or byte budget is malformed."""
    module = load_decoder()
    source = [
        {
            "ordinal": 188,
            "checksum": -188,
            "label": "label-budget",
            "points": [{"x": 11, "y": -11, "z": 22, "signal": -22}],
            "tags": [],
        }
    ]
    label_pointer_offset = 8 + (5 * 8)

    wrong_element_size = bytearray(encode_verifier_only_message(source))
    label_pointer = struct.unpack_from("<Q", wrong_element_size, label_pointer_offset)[0]
    wrong_element_size[label_pointer_offset : label_pointer_offset + 8] = struct.pack(
        "<Q",
        (label_pointer & ~(0x7 << 32)) | (LIST_POINTER << 32),
    )
    with pytest.raises(module.DecodeError):
        module.decode_message(bytes(wrong_element_size))

    byte_budget_overrun = bytearray(encode_verifier_only_message(source))
    label_pointer = struct.unpack_from("<Q", byte_budget_overrun, label_pointer_offset)[0]
    byte_budget_overrun[label_pointer_offset : label_pointer_offset + 8] = struct.pack(
        "<Q",
        (label_pointer & ~(((1 << 29) - 1) << 35)) | ((len("label-budget") + 80) << 35),
    )
    with pytest.raises(module.DecodeError):
        module.decode_message(bytes(byte_budget_overrun))

    wrong_pointer_kind = bytearray(encode_verifier_only_message(source))
    label_pointer = struct.unpack_from("<Q", wrong_pointer_kind, label_pointer_offset)[0]
    wrong_pointer_kind[label_pointer_offset : label_pointer_offset + 8] = struct.pack(
        "<Q",
        (label_pointer & ~0x3) | 0x2,
    )
    with pytest.raises(module.DecodeError):
        module.decode_message(bytes(wrong_pointer_kind))


def test_decode_message_rejects_malformed_tag_lists():
    """Segment tag fields should reject non-pointer lists and malformed text entries."""
    module = load_decoder()
    source = [
        {
            "ordinal": 77,
            "checksum": -77,
            "label": "tag-shape",
            "points": [{"x": 4, "y": -4, "z": 8, "signal": 16}],
            "tags": ["alpha", "beta"],
        }
    ]

    tag_list_corruption = bytearray(encode_verifier_only_message(source))
    tags_pointer_offset = 8 + (6 * 8)
    tag_list_corruption[tags_pointer_offset : tags_pointer_offset + 8] = struct.pack(
        "<Q",
        KIND_LIST | (1 << 2) | (LIST_BYTE << 32) | (4 << 35),
    )
    with pytest.raises(module.DecodeError):
        module.decode_message(bytes(tag_list_corruption))

    tag_list_budget_corruption = bytearray(encode_verifier_only_message(source))
    tags_pointer = struct.unpack_from("<Q", tag_list_budget_corruption, tags_pointer_offset)[0]
    tag_list_budget_corruption[tags_pointer_offset : tags_pointer_offset + 8] = struct.pack(
        "<Q",
        (tags_pointer & ~(((1 << 29) - 1) << 35)) | (4 << 35),
    )
    with pytest.raises(module.DecodeError):
        module.decode_message(bytes(tag_list_budget_corruption))

    tag_text_corruption = bytearray(encode_verifier_only_message(source))
    tags_pointer = struct.unpack_from("<Q", tag_text_corruption, tags_pointer_offset)[0]
    tag_list_target = 6 + 1 + ((tags_pointer >> 2) & 0x3FFFFFFF)
    first_tag_pointer_offset = 8 + (tag_list_target * 8)
    first_tag_pointer = struct.unpack_from("<Q", tag_text_corruption, first_tag_pointer_offset)[0]
    tag_text_start = tag_list_target + 1 + ((first_tag_pointer >> 2) & 0x3FFFFFFF)
    tag_text_byte_offset = 8 + (tag_text_start * 8)
    tag_text_corruption[tag_text_byte_offset + len("alpha")] = ord("!")
    with pytest.raises(module.DecodeError):
        module.decode_message(bytes(tag_text_corruption))


def test_decode_message_rejects_tag_text_utf8_and_pointer_shape_errors():
    """Every tag entry should be a valid UTF-8 Text pointer, not merely a traversable pointer."""
    module = load_decoder()
    source = [
        {
            "ordinal": 177,
            "checksum": -177,
            "label": "tag-text-shape",
            "points": [{"x": 6, "y": -6, "z": 12, "signal": 18}],
            "tags": ["gamma", "delta"],
        }
    ]
    tags_pointer_offset = 8 + (6 * 8)

    invalid_utf8_tag = bytearray(encode_verifier_only_message(source))
    tags_pointer = struct.unpack_from("<Q", invalid_utf8_tag, tags_pointer_offset)[0]
    tag_list_target = 6 + 1 + ((tags_pointer >> 2) & 0x3FFFFFFF)
    second_tag_pointer_offset = 8 + ((tag_list_target + 1) * 8)
    second_tag_pointer = struct.unpack_from("<Q", invalid_utf8_tag, second_tag_pointer_offset)[0]
    second_tag_text_start = tag_list_target + 2 + ((second_tag_pointer >> 2) & 0x3FFFFFFF)
    second_tag_text_byte_offset = 8 + (second_tag_text_start * 8)
    invalid_utf8_tag[second_tag_text_byte_offset] = 0xFF
    with pytest.raises(module.DecodeError):
        module.decode_message(bytes(invalid_utf8_tag))

    wrong_tag_pointer_shape = bytearray(encode_verifier_only_message(source))
    tags_pointer = struct.unpack_from("<Q", wrong_tag_pointer_shape, tags_pointer_offset)[0]
    tag_list_target = 6 + 1 + ((tags_pointer >> 2) & 0x3FFFFFFF)
    first_tag_pointer_offset = 8 + (tag_list_target * 8)
    first_tag_pointer = struct.unpack_from("<Q", wrong_tag_pointer_shape, first_tag_pointer_offset)[0]
    wrong_tag_pointer_shape[first_tag_pointer_offset : first_tag_pointer_offset + 8] = struct.pack(
        "<Q",
        (first_tag_pointer & ~(0x7 << 32)) | (LIST_POINTER << 32),
    )
    with pytest.raises(module.DecodeError):
        module.decode_message(bytes(wrong_tag_pointer_shape))

    wrong_tag_pointer_kind = bytearray(encode_verifier_only_message(source))
    tags_pointer = struct.unpack_from("<Q", wrong_tag_pointer_kind, tags_pointer_offset)[0]
    tag_list_target = 6 + 1 + ((tags_pointer >> 2) & 0x3FFFFFFF)
    first_tag_pointer_offset = 8 + (tag_list_target * 8)
    first_tag_pointer = struct.unpack_from("<Q", wrong_tag_pointer_kind, first_tag_pointer_offset)[0]
    wrong_tag_pointer_kind[first_tag_pointer_offset : first_tag_pointer_offset + 8] = struct.pack(
        "<Q",
        (first_tag_pointer & ~0x3) | 0x2,
    )
    with pytest.raises(module.DecodeError):
        module.decode_message(bytes(wrong_tag_pointer_kind))


def test_decode_message_rejects_tag_null_pointer_and_count_overrun():
    """Tag lists should reject null Text entries and pointer counts that overrun the encoded list body."""
    module = load_decoder()
    source = [
        {
            "ordinal": 277,
            "checksum": -277,
            "label": "tag-list-overrun",
            "points": [{"x": 7, "y": -7, "z": 14, "signal": 21}],
            "tags": ["one", "two", "three"],
        }
    ]
    tags_pointer_offset = 8 + (6 * 8)

    null_tag_pointer = bytearray(encode_verifier_only_message(source))
    tags_pointer = struct.unpack_from("<Q", null_tag_pointer, tags_pointer_offset)[0]
    tag_list_target = 6 + 1 + ((tags_pointer >> 2) & 0x3FFFFFFF)
    null_tag_pointer[8 + ((tag_list_target + 1) * 8) : 8 + ((tag_list_target + 2) * 8)] = b"\x00" * 8
    with pytest.raises(module.DecodeError):
        module.decode_message(bytes(null_tag_pointer))

    tag_count_overrun = bytearray(encode_verifier_only_message(source))
    tags_pointer = struct.unpack_from("<Q", tag_count_overrun, tags_pointer_offset)[0]
    tag_count_overrun[tags_pointer_offset : tags_pointer_offset + 8] = struct.pack(
        "<Q",
        (tags_pointer & ~(((1 << 29) - 1) << 35)) | (24 << 35),
    )
    with pytest.raises(module.DecodeError):
        module.decode_message(bytes(tag_count_overrun))


def test_decode_message_rejects_multibyte_text_without_complete_utf8_or_nul():
    """UTF-8 Text validation should catch incomplete multi-byte characters and missing terminators independently."""
    module = load_decoder()
    source = [
        {
            "ordinal": 288,
            "checksum": -288,
            "label": "wide-label-终",
            "points": [{"x": 8, "y": -8, "z": 16, "signal": 24}],
            "tags": ["wide-tag-δ"],
        }
    ]
    label_pointer_offset = 8 + (5 * 8)

    truncated_multibyte = bytearray(encode_verifier_only_message(source))
    label_pointer = struct.unpack_from("<Q", truncated_multibyte, label_pointer_offset)[0]
    label_text_start = 5 + 1 + ((label_pointer >> 2) & 0x3FFFFFFF)
    label_text_byte_offset = 8 + (label_text_start * 8)
    terminator_index = label_text_byte_offset + len("wide-label-终".encode("utf-8"))
    truncated_multibyte[terminator_index - 1] = 0x00
    with pytest.raises(module.DecodeError):
        module.decode_message(bytes(truncated_multibyte))

    tag_unterminated = bytearray(encode_verifier_only_message(source))
    tags_pointer_offset = 8 + (6 * 8)
    tags_pointer = struct.unpack_from("<Q", tag_unterminated, tags_pointer_offset)[0]
    tag_list_target = 6 + 1 + ((tags_pointer >> 2) & 0x3FFFFFFF)
    tag_pointer = struct.unpack_from("<Q", tag_unterminated, 8 + (tag_list_target * 8))[0]
    tag_text_start = tag_list_target + 1 + ((tag_pointer >> 2) & 0x3FFFFFFF)
    tag_text_byte_offset = 8 + (tag_text_start * 8)
    tag_unterminated[tag_text_byte_offset + len("wide-tag-δ".encode("utf-8"))] = ord("x")
    with pytest.raises(module.DecodeError):
        module.decode_message(bytes(tag_unterminated))


def test_diagnostics_api_rejects_invalid_worker_count_and_id_overrides():
    """API-level guardrails should reject invalid execution settings and mismatch data."""
    module = load_decoder()

    for bad_worker_count in (0, -2, 1.5, "2", True):
        with pytest.raises(module.DecodeError):
            module.decode_file_with_metrics(str(HIDDEN_MESSAGES_PATH), max_workers=bad_worker_count)

    with pytest.raises(module.DecodeError):
        module.decode_file_with_metrics(str(HIDDEN_MESSAGES_PATH), message_ids=["x", "y"])

    ids_with_bad_type = [f"typed-{index:02d}" for index in range(expected_message_count())]
    ids_with_bad_type[2] = 7
    with pytest.raises(module.DecodeError):
        module.decode_file_with_metrics(str(HIDDEN_MESSAGES_PATH), message_ids=ids_with_bad_type)

    with pytest.raises(module.DecodeError):
        module.decode_file_with_metrics(str(HIDDEN_MESSAGES_PATH), message_ids="x" * expected_message_count())

    first_message = module.read_message_stream(str(HIDDEN_MESSAGES_PATH))[0]
    with pytest.raises(module.DecodeError):
        module.decode_message(first_message, message_id=7)


def test_cli_decodes_message_stream_to_valid_json_and_preserves_shape():
    """Ensure CLI output is stable JSON matching in-module decoding behavior."""
    result = subprocess.run(
        [sys.executable, str(DECODER_PATH), str(MESSAGES_PATH)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0
    decoded_cli = load_json_from_output(result.stdout)
    decoded_module = decode_messages()
    assert decoded_cli == decoded_module
    assert len(decoded_cli) == expected_message_count()
    for index, message in enumerate(decoded_cli):
        assert message["message_id"] == f"message-{index:02d}"
        assert isinstance(message["segments"], list)
        for segment in message["segments"]:
            assert {"ordinal", "checksum", "label", "points", "tags"}.issubset(segment.keys())
            assert isinstance(segment["label"], str)
            assert not segment["label"].endswith("\x00")
            for point in segment["points"]:
                assert {"x", "y", "z", "signal"}.issubset(point.keys())
