#!/usr/bin/env bash
set -euo pipefail

cat > /app/capnp_decoder.py <<'PY'
import argparse
import json
import struct
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

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
API_VERSION = "2.0"


class DecodeError(ValueError):
    pass


def _u32(data, offset):
    if offset + 4 > len(data):
        raise DecodeError("stream ended while reading u32")
    return struct.unpack_from("<I", data, offset)[0]


def _word(data, index):
    offset = index * 8
    if offset + 8 > len(data):
        raise DecodeError(f"word index {index} is outside the segment")
    return struct.unpack_from("<Q", data, offset)[0]


def _signed30(value):
    value &= 0x3FFFFFFF
    if value & (1 << 29):
        value -= 1 << 30
    return value


def _kind(pointer):
    return pointer & 0x3


def _target_index(pointer_index, pointer):
    return pointer_index + 1 + _signed30(pointer >> 2)


def _struct_layout(pointer):
    return (pointer >> 32) & 0xFFFF, (pointer >> 48) & 0xFFFF


def _list_layout(pointer):
    return (pointer >> 32) & 0x7, (pointer >> 35) & 0x1FFFFFFF


def _int32_from_word(word, lane):
    raw = (word >> (lane * 32)) & 0xFFFFFFFF
    if raw & 0x80000000:
        raw -= 0x100000000
    return raw


def _decode_primitive_list(words, start, element_size, count):
    if element_size == LIST_VOID:
        return [None for _ in range(count)]
    if element_size == LIST_BIT:
        end_word = start + ((count + 63) // 64)
        if end_word * 8 > len(words):
            raise DecodeError("bit list runs past the end of the segment")
        return [bool((_word(words, start + (index // 64)) >> (index % 64)) & 1) for index in range(count)]
    byte_width = {
        LIST_BYTE: 1,
        LIST_TWO_BYTES: 2,
        LIST_FOUR_BYTES: 4,
        LIST_EIGHT_BYTES: 8,
    }.get(element_size)
    if byte_width is None:
        raise DecodeError(f"unsupported primitive list element size {element_size}")
    raw = words[start * 8 : start * 8 + count * byte_width]
    if len(raw) != count * byte_width:
        raise DecodeError("primitive list runs past the end of the segment")
    values = []
    for index in range(count):
        begin = index * byte_width
        values.append(int.from_bytes(raw[begin : begin + byte_width], "little", signed=False))
    return values


def _decode_text(words, pointer_index, pointer):
    if pointer == 0 or _kind(pointer) != KIND_LIST:
        raise DecodeError("text fields must be byte lists")
    element_size, count = _list_layout(pointer)
    if element_size != LIST_BYTE:
        raise DecodeError("text fields must be byte lists")
    start = _target_index(pointer_index, pointer)
    if start < 0:
        raise DecodeError("text field target is outside the segment")
    raw = words[start * 8 : start * 8 + count]
    if len(raw) != count:
        raise DecodeError("text field runs past the end of the segment")
    if raw.endswith(b"\x00") is False:
        raise DecodeError("text field is missing nul termination")
    try:
        return raw[:-1].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DecodeError(f"text field is not valid UTF-8: {exc}") from exc


def _decode_text_list(words, pointer_index, pointer):
    if pointer == 0 or _kind(pointer) != KIND_LIST:
        raise DecodeError("tag lists must be pointer lists")
    element_size, count = _list_layout(pointer)
    if element_size != LIST_POINTER:
        raise DecodeError("tag lists must be pointer lists")
    start = _target_index(pointer_index, pointer)
    if start < 0 or start + count > len(words) // 8:
        raise DecodeError("tag list runs past the end of the segment")
    tags = []
    for index in range(count):
        tag_pointer_index = start + index
        tag_pointer = _word(words, tag_pointer_index)
        tags.append(_decode_text(words, tag_pointer_index, tag_pointer))
    return tags


def _decode_point_inline(words, element_start, data_words, pointer_words):
    if data_words != 2 or pointer_words != 0:
        raise DecodeError("Point elements must have two data words and zero pointer words")
    packed = _word(words, element_start)
    packed_extra = _word(words, element_start + 1)
    return {
        "x": _int32_from_word(packed, 0),
        "y": _int32_from_word(packed, 1),
        "z": _int32_from_word(packed_extra, 0),
        "signal": _int32_from_word(packed_extra, 1),
    }


def _decode_segment_inline(words, element_start, data_words, pointer_words):
    if data_words != 1 or pointer_words != 3:
        raise DecodeError("Segment elements must have one data word and three pointer words")
    meta = _word(words, element_start)
    points_pointer_index = element_start + data_words
    label_pointer_index = points_pointer_index + 1
    tags_pointer_index = points_pointer_index + 2
    points_pointer = _word(words, points_pointer_index)
    label_pointer = _word(words, label_pointer_index)
    tags_pointer = _word(words, tags_pointer_index)
    return {
        "ordinal": meta & 0xFFFFFFFF,
        "checksum": _int32_from_word(meta, 1),
        "label": _decode_text(words, label_pointer_index, label_pointer),
        "points": _decode_composite_list(words, points_pointer_index, points_pointer, "Point"),
        "tags": _decode_text_list(words, tags_pointer_index, tags_pointer),
    }


def _decode_generic_struct(words, data_start, data_words, pointer_words):
    data = [_word(words, data_start + index) for index in range(data_words)]
    pointer_start = data_start + data_words
    pointers = [_decode_pointer(words, pointer_start + index) for index in range(pointer_words)]
    return {"data": data, "pointers": pointers}


def _decode_composite_list(words, pointer_index, pointer, element_type):
    if pointer == 0 or _kind(pointer) != KIND_LIST:
        raise DecodeError("expected a composite list pointer")
    element_size, total_words = _list_layout(pointer)
    if element_size != LIST_COMPOSITE:
        raise DecodeError("expected a composite list pointer")
    tag_index = _target_index(pointer_index, pointer)
    if tag_index < 0:
        raise DecodeError("composite list target is outside the segment")
    tag = _word(words, tag_index)
    if _kind(tag) != KIND_STRUCT:
        raise DecodeError("composite list tag must describe struct elements")
    data_words, pointer_words = _struct_layout(tag)
    struct_size_words = data_words + pointer_words
    if struct_size_words == 0:
        raise DecodeError("composite list element size cannot be zero words")
    if total_words % struct_size_words != 0:
        raise DecodeError("composite list word budget does not match struct stride")
    element_count = total_words // struct_size_words
    elements_start = tag_index + 1
    end_word = elements_start + total_words
    if end_word * 8 > len(words):
        raise DecodeError("composite list runs past the end of the segment")
    values = []
    for index in range(element_count):
        element_start = elements_start + index * struct_size_words
        if element_type == "Segment":
            values.append(_decode_segment_inline(words, element_start, data_words, pointer_words))
        elif element_type == "Point":
            values.append(_decode_point_inline(words, element_start, data_words, pointer_words))
        else:
            values.append(_decode_generic_struct(words, element_start, data_words, pointer_words))
    return values


def _decode_pointer_list(words, pointer_index, pointer):
    if pointer == 0 or _kind(pointer) != KIND_LIST:
        raise DecodeError("expected a pointer list")
    element_size, count = _list_layout(pointer)
    if element_size != LIST_POINTER:
        raise DecodeError("expected a pointer list")
    start = _target_index(pointer_index, pointer)
    if start < 0 or start + count > len(words) // 8:
        raise DecodeError("pointer list runs past the end of the segment")
    return [_decode_pointer(words, start + index) for index in range(count)]


def _decode_struct_pointer(words, pointer_index, pointer):
    data_words, pointer_words = _struct_layout(pointer)
    data_start = _target_index(pointer_index, pointer)
    return _decode_generic_struct(words, data_start, data_words, pointer_words)


def _decode_pointer(words, pointer_index):
    pointer = _word(words, pointer_index)
    if pointer == 0:
        return None
    kind = _kind(pointer)
    if kind == KIND_STRUCT:
        return _decode_struct_pointer(words, pointer_index, pointer)
    if kind == KIND_LIST:
        element_size, count = _list_layout(pointer)
        if element_size == LIST_POINTER:
            return _decode_pointer_list(words, pointer_index, pointer)
        return _decode_primitive_list(words, _target_index(pointer_index, pointer), element_size, count)
    raise DecodeError(f"unsupported pointer kind {kind}")


def _segment_payload(message):
    if len(message) < 8:
        raise DecodeError("message is too short for a segment table")
    segment_count = _u32(message, 0) + 1
    if segment_count != 1:
        raise DecodeError("this decoder supports single-segment messages")
    segment_words = _u32(message, 4)
    data_start = 8 + (8 if segment_count % 2 == 0 else 0)
    data_end = data_start + segment_words * 8
    if data_end != len(message):
        raise DecodeError("segment table size does not match message length")
    return message[data_start:data_end]


def decode_message(message, message_id=None):
    if message_id is not None and type(message_id) is not str:
        raise DecodeError("message_id must be a string")
    segment = _segment_payload(message)
    root = _word(segment, 0)
    if _kind(root) != KIND_STRUCT:
        raise DecodeError("root pointer must be a struct pointer")
    data_words, pointer_words = _struct_layout(root)
    if data_words != 0 or pointer_words < 1:
        raise DecodeError("root struct must contain the segment list pointer")
    root_data = _target_index(0, root)
    segments_pointer_index = root_data + data_words
    segments_pointer = _word(segment, segments_pointer_index)
    decoded = {"segments": _decode_composite_list(segment, segments_pointer_index, segments_pointer, "Segment")}
    if message_id is not None:
        decoded = {"message_id": message_id, **decoded}
    return decoded


def _decode_message_with_event(message, index, message_id, size_prefix_offset, byte_start, byte_end):
    start_ns = time.perf_counter()
    decoded = decode_message(message, message_id)
    elapsed_ms = (time.perf_counter() - start_ns) * 1000.0
    point_count = sum(len(segment["points"]) for segment in decoded["segments"])
    max_points_in_segment = max((len(segment["points"]) for segment in decoded["segments"]), default=0)
    segment_point_counts = [len(segment["points"]) for segment in decoded["segments"]]
    return index, decoded, {
        "message_index": index,
        "message_id": message_id,
        "segment_count": len(decoded["segments"]),
        "point_count": point_count,
        "max_points_in_segment": max_points_in_segment,
        "segment_point_counts": segment_point_counts,
        "size_prefix_offset": size_prefix_offset,
        "byte_start": byte_start,
        "byte_end": byte_end,
        "message_bytes": byte_end - byte_start,
        "decode_ms": elapsed_ms,
        "message_crc32": zlib.crc32(message) & 0xFFFFFFFF,
    }


def read_message_stream(path):
    return [record[3] for record in _read_message_stream_with_offsets(path)]


def _read_message_stream_with_offsets(path):
    data = Path(path).read_bytes()
    if data.startswith(MAGIC) is False:
        raise DecodeError("message stream has the wrong magic header")
    offset = len(MAGIC)
    count = _u32(data, offset)
    offset += 4
    records = []
    for _index in range(count):
        size_offset = offset
        size = _u32(data, offset)
        offset += 4
        if size == 0:
            raise DecodeError("message stream contains zero-length message")
        if size % 8 != 0:
            raise DecodeError("message byte length must be aligned to 8")
        start = offset
        end = start + size
        if end > len(data):
            raise DecodeError("message stream truncates message payload")
        records.append((size_offset, start, end, data[start:end]))
        offset = end
    if offset != len(data):
        raise DecodeError("message stream has trailing bytes")
    return records


def decode_file(path):
    return decode_file_with_metrics(path)["messages"]


def decode_file_with_metrics(path, max_workers=1, message_ids=None):
    if type(max_workers) is not int or max_workers < 1:
        raise DecodeError("max_workers must be a positive integer")
    records = _read_message_stream_with_offsets(path)
    message_count = len(records)
    if message_ids is not None and not isinstance(message_ids, (list, tuple)):
        raise DecodeError("message_ids must be a list of strings")
    if message_ids is not None and len(message_ids) != message_count:
        raise DecodeError("message_ids length must match message count")
    if message_ids is not None and any(type(message_id) is not str for message_id in message_ids):
        raise DecodeError("message_ids must be strings")
    if message_ids is not None and len(set(message_ids)) != len(message_ids):
        raise DecodeError("message_ids must be unique")
    start = time.perf_counter()
    if max_workers == 1:
        results = []
        for index, (size_offset, start_offset, end_offset, message) in enumerate(records):
            message_id = message_ids[index] if message_ids else f"message-{index:02d}"
            results.append(_decode_message_with_event(message, index, message_id, size_offset, start_offset, end_offset))
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for index, (size_offset, start_offset, end_offset, message) in enumerate(records):
                message_id = message_ids[index] if message_ids else f"message-{index:02d}"
                futures.append(executor.submit(_decode_message_with_event, message, index, message_id, size_offset, start_offset, end_offset))
            results = [future.result() for future in futures]
    decoded = [None] * message_count
    events = []
    for index, payload, event in sorted(results, key=lambda item: item[0]):
        decoded[index] = payload
        events.append(event)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    if any(event["byte_end"] <= event["byte_start"] for event in events):
        raise DecodeError("decoded message byte offsets are invalid")
    byte_starts = [event["byte_start"] for event in events]
    if byte_starts != sorted(byte_starts):
        raise DecodeError("message byte offsets are out of order")
    segment_counts = [event["segment_count"] for event in events]
    point_counts = [event["point_count"] for event in events]
    segment_point_histogram = {}
    for event in events:
        for segment_point_count in event["segment_point_counts"]:
            histogram_key = str(segment_point_count)
            segment_point_histogram[histogram_key] = segment_point_histogram.get(histogram_key, 0) + 1
    diagnostics = {
        "api_version": API_VERSION,
        "raw_bytes": Path(path).stat().st_size,
        "message_count": message_count,
        "segment_count": sum(segment_counts),
        "point_count": sum(point_counts),
        "max_points_in_message": max(point_counts, default=0),
        "max_points_in_segment": max((event["max_points_in_segment"] for event in events), default=0),
        "avg_points_per_message": (sum(point_counts) / message_count) if message_count else 0.0,
        "segment_point_histogram": segment_point_histogram,
        "point_count_per_message": [event["point_count"] for event in events],
        "decode_ms_per_message": [event["decode_ms"] for event in events],
        "max_decode_ms_per_message": max((event["decode_ms"] for event in events), default=0.0),
        "worker_count": max_workers,
        "elapsed_ms": elapsed_ms,
        "events": events,
        "message_byte_ranges": [[event["byte_start"], event["byte_end"]] for event in events],
        "message_crc32s": [event["message_crc32"] for event in events],
        "stream_crc32": zlib.crc32(Path(path).read_bytes()) & 0xFFFFFFFF,
    }
    return {"messages": decoded, "diagnostics": diagnostics}


def main():
    parser = argparse.ArgumentParser(description="Decode the synthetic Cap'n Proto message stream.")
    parser.add_argument("messages", nargs="?", default="/app/data/messages.bin")
    args = parser.parse_args()
    print(json.dumps(decode_file(args.messages), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
PY
