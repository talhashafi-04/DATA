#!/usr/bin/env python3
import os
import random
import struct

MAGIC = b"CPNPTRAV"

KIND_STRUCT = 0
KIND_LIST = 1

LIST_VOID = 0
LIST_BIT = 1
LIST_BYTE = 2
LIST_TWO_BYTES = 3
LIST_FOUR_BYTES = 4
LIST_EIGHT_BYTES = 5
LIST_POINTER = 6
LIST_COMPOSITE = 7


def pointer_list(offset_words, count):
    return list_pointer(offset_words, LIST_POINTER, count)


def _signed_offset(value):
    return value & 0x3FFFFFFF


def struct_pointer(offset_words, data_words, pointer_words):
    return (
        KIND_STRUCT
        | (_signed_offset(offset_words) << 2)
        | (data_words << 32)
        | (pointer_words << 48)
    )


def list_pointer(offset_words, element_size, count):
    return KIND_LIST | (_signed_offset(offset_words) << 2) | (element_size << 32) | (count << 35)


def text_pointer(offset_words, byte_count_with_nul):
    return list_pointer(offset_words, LIST_BYTE, byte_count_with_nul)


def pack_word(value):
    return struct.pack("<Q", value & 0xFFFFFFFFFFFFFFFF)


def pack_point(point):
    x = point["x"] & 0xFFFFFFFF
    y = point["y"] & 0xFFFFFFFF
    z = point["z"] & 0xFFFFFFFF
    signal = point["signal"] & 0xFFFFFFFF
    return pack_word(x | (y << 32)) + pack_word(z | (signal << 32))


def align8(data):
    return data + (b"\x00" * ((8 - (len(data) % 8)) % 8))


def make_message(message_index, segments):
    words = [0, 0]
    root_index = 0
    segments_pointer_index = 1

    segment_data_words = 1
    segment_pointer_words = 3
    segment_struct_words = segment_data_words + segment_pointer_words
    total_segment_words = len(segments) * segment_struct_words

    segment_list_start = len(words)
    words[segments_pointer_index] = list_pointer(
        segment_list_start - (segments_pointer_index + 1),
        LIST_COMPOSITE,
        total_segment_words,
    )
    words.append(struct_pointer(total_segment_words, segment_data_words, segment_pointer_words))

    segment_pointer_slots = []
    for _segment in segments:
        data_slot = len(words)
        point_slot = len(words) + 1
        label_slot = len(words) + 2
        tags_slot = len(words) + 3
        words.extend([0, 0, 0, 0])
        segment_pointer_slots.append((data_slot, point_slot, label_slot, tags_slot))

    for segment, (data_slot, point_slot, label_slot, tags_slot) in zip(segments, segment_pointer_slots):
        meta = (segment["ordinal"] & 0xFFFFFFFF) | ((segment["checksum"] & 0xFFFFFFFF) << 32)
        words[data_slot] = meta
        point_data_words = 2
        point_pointer_words = 0
        point_struct_words = point_data_words + point_pointer_words
        total_point_words = len(segment["points"]) * point_struct_words
        points_start = len(words)
        words[point_slot] = list_pointer(
            points_start - (point_slot + 1),
            LIST_COMPOSITE,
            total_point_words,
        )
        words.append(struct_pointer(total_point_words, point_data_words, point_pointer_words))
        for point in segment["points"]:
            packed = pack_point(point)
            words.append(struct.unpack("<Q", packed[:8])[0])
            words.append(struct.unpack("<Q", packed[8:])[0])

        label_bytes = segment["label"].encode("utf-8") + b"\x00"
        label_start = len(words)
        words[label_slot] = text_pointer(label_start - (label_slot + 1), len(label_bytes))
        for index in range(0, len(align8(label_bytes)), 8):
            words.append(struct.unpack("<Q", align8(label_bytes)[index : index + 8])[0])

        tags = segment.get("tags", [])
        tags_list_start = len(words)
        words[tags_slot] = pointer_list(tags_list_start - (tags_slot + 1), len(tags))
        tag_pointer_slots = list(range(len(words), len(words) + len(tags)))
        words.extend([0] * len(tags))
        for tag_slot, tag in zip(tag_pointer_slots, tags):
            tag_bytes = tag.encode("utf-8") + b"\x00"
            tag_start = len(words)
            words[tag_slot] = text_pointer(tag_start - (tag_slot + 1), len(tag_bytes))
            padded_tag = align8(tag_bytes)
            for index in range(0, len(padded_tag), 8):
                words.append(struct.unpack("<Q", padded_tag[index : index + 8])[0])

    words[root_index] = struct_pointer(0, 0, 1)
    segment_bytes = b"".join(pack_word(word) for word in words)
    header = struct.pack("<II", 0, len(words))
    message = header + segment_bytes
    decoded = {
        "message_id": f"message-{message_index:02d}",
        "segments": segments,
    }
    return message, decoded


def _checksum(raw_value):
    masked = raw_value & 0xFFFFFFFF
    if masked & 0x80000000:
        return masked - (1 << 32)
    return masked


def _segment_label(message_index, segment_index, point_count):
    return f"segment-{message_index:02d}-{segment_index:02d}-pts-{point_count}"


def _edge_segments(message_index):
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
                    "x": _checksum(0x70000000 + point_index * 977),
                    "y": _checksum(-0x70000000 - point_index * 619),
                    "z": _checksum(point_index * point_index * 12345 - 2000000000),
                    "signal": _checksum(0x80000000 + point_index),
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
                    "x": _checksum(0x7FFFF000 - point_index * 4099),
                    "y": _checksum(-0x7FFF0000 + point_index * 8191),
                    "z": _checksum((point_index * 65537) - 2147483648),
                    "signal": _checksum(2147483647 - point_index * 17),
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
                        "x": _checksum(segment_index * 1000003 + point_index * 97),
                        "y": _checksum(-segment_index * 999983 - point_index * 193),
                        "z": _checksum((point_index - segment_index) * 1234567),
                        "signal": _checksum(0x80000000 + segment_index * 257 + point_index),
                    }
                )
            segments.append(
                {
                    "ordinal": _checksum(0xFFFFFF00 + segment_index) & 0xFFFFFFFF,
                    "checksum": _checksum(0x7FFFFFFF - segment_index),
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
                    "x": _checksum(-2147483648 + point_index * 65536),
                    "y": _checksum(2147483647 - point_index * 32768),
                    "z": _checksum((point_index * point_index * 4093) ^ 0xAAAAAAAA),
                    "signal": _checksum((0x55555555 + point_index * 104729)),
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
                "checksum": _checksum(-2000000000 + segment_index * 123456),
                "label": f"segment-92-unicode-{segment_index}-東京-مرحبا-данные",
                "points": [
                    {
                        "x": _checksum(1000 + segment_index * 10 + point_index),
                        "y": _checksum(-1000 - segment_index * 10 - point_index),
                        "z": _checksum(segment_index * point_index - 12345),
                        "signal": _checksum(-2147483648 + segment_index * 100 + point_index),
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
                "checksum": _checksum(2147483647 - segment_index * 100000),
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
                        "x": _checksum(0x7FFFFFFF - message_index * 4096 - segment_index * 257 - point_index * 31),
                        "y": _checksum(-0x80000000 + message_index * 2048 + segment_index * 503 + point_index * 47),
                        "z": _checksum((message_index - 96) * 100000 + segment_index * 1000 - point_index * 13),
                        "signal": _checksum(0x80000000 + message_index * 313 + segment_index * 29 + point_index),
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
                    "checksum": _checksum(-2000000000 + message_index * 65537 + segment_index * 8191),
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
                        "x": _checksum(0x7FFFFFFF - message_index * 8191 - segment_index * 4093 - point_index * 127),
                        "y": _checksum(-0x80000000 + message_index * 4099 + segment_index * 2053 + point_index * 251),
                        "z": _checksum((message_index - 128) * 250000 - segment_index * 17001 + point_index * 65537),
                        "signal": _checksum(0x80000000 + message_index * 997 + segment_index * 131 + point_index * 7),
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
                    "checksum": _checksum(1800000000 - message_index * 131071 - segment_index * 32749),
                    "label": f"segment-{message_index:03d}-bulk-edge-{segment_index:02d}-pts-{point_count:02d}-東京-λ",
                    "points": points,
                    "tags": tags,
                }
            )
        return segments
    return None


def make_segments(rng, message_index):
    edge = _edge_segments(message_index)
    if edge is not None:
        return edge

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
        checksum = _checksum(message_index * 1009 + segment_index * 131 + point_count * 17)
        tag_count = (message_index + segment_index) % 3
        tags = [f"tag-{message_index:02d}-{segment_index:02d}-{slot}" for slot in range(tag_count)]
        segments.append(
            {
                "ordinal": message_index * 10 + segment_index,
                "checksum": checksum,
                "label": _segment_label(message_index, segment_index, point_count),
                "points": points,
                "tags": tags,
            }
        )
    return segments


def build_dataset(message_count=256):
    rng = random.Random(492917)
    messages = []
    reference = []
    for message_index in range(message_count):
        message, decoded = make_message(message_index, make_segments(rng, message_index))
        messages.append(message)
        reference.append(decoded)
    return messages, reference


def write_dataset(output_dir="/app/data"):
    os.makedirs(output_dir, exist_ok=True)
    messages, reference = build_dataset()
    with open(os.path.join(output_dir, "messages.bin"), "wb") as f:
        f.write(MAGIC)
        f.write(struct.pack("<I", len(messages)))
        for message in messages:
            f.write(struct.pack("<I", len(message)))
            f.write(message)


if __name__ == "__main__":
    write_dataset(os.environ.get("CAPNP_DATA_DIR", "/app/data"))
