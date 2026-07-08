The python file located at /app/capnp_decoder.py needs to be fixed so that it can read /app/data/messages.bin and give the required JSON output.

You need to work in /app. The fixed /app/capnp_decoder.py needs to be able to run from the command line and be used as a module.

Use these requirements for the project:

1. If you run `python3 capnp_decoder.py /app/data/messages.bin` in the command line, it should finish cleanly and give valid JSON output.

2. The `decode_file` function should return a JSON array of message objects in the order they appear in the file. Each message object should have a `message_id` string in the format `message-{index:02d}` and a `segments` array.

3. Each item in a message `segments` array should include `ordinal`, `checksum`, `label`, `points`, and `tags`. The `points` field should be an array. The `tags` field should be an ordered list of strings, and it can be empty.

4. Each item in a segment `points` array should include `x`, `y`, `z`, and `signal`. The order of the points should be the same as in the file.

5. The `decode_file_with_metrics(path, max_workers=1, message_ids=None)` function should return an object with `messages` and `diagnostics`. The `messages` should be the same as what `decode_file` returns for the file.

6. If the file is malformed the function should raise `DecodeError` instead of trying to return partial JSON. Composite lists whose encoded word budget leaves a remainder after division by the element struct size should also raise `DecodeError`. Text fields should be valid UTF-8 and NUL-terminated.

7. The diagnostics `worker_count` should equal the `max_workers` value. When `message_ids` is provided, the message IDs in `messages` and diagnostics events should equal those strings in order.

8. Each diagnostics event should include `message_index`, `message_id`, `size_prefix_offset`, `byte_start`, `byte_end`, `message_bytes`, `message_crc32`, `segment_count`, `point_count`, `max_points_in_segment`, and `segment_point_counts`.

9. The diagnostics should include `api_version`, `raw_bytes`, `message_count`, `segment_count`, `point_count`, `max_points_in_message`, `max_points_in_segment`, `avg_points_per_message`, `segment_point_histogram`, `point_count_per_message`, `decode_ms_per_message`, `max_decode_ms_per_message`, `worker_count`, `elapsed_ms`, `events`, and `stream_crc32`. `segment_point_histogram` should map point-count strings to integer segment counts.

10. The `api_version` should be `2.0`. The `worker_count` should be the same as the number of workers used to read the file. The worker count should be an `int`, excluding `bool`, and strictly positive. Message-id overrides should be strings. A bad worker count, duplicate message IDs, a message ID with another type, or a message-id list with the wrong length should raise `DecodeError`.

11. The `decode_message(message, message_id=None)` function should take one encoded message and an optional message-id string, then return one decoded message. The `read_message_stream` function should take a file path and return the encoded messages in the file.

12. The numbers in the output should be JSON numbers. They should match the Cap'n Proto scalar signedness: `ordinal` is `UInt32`, `checksum` is `Int32`, and `x`, `y`, `z`, and `signal` are `Int32`. CRC32 values are unsigned 32-bit integers. Counts and byte offsets are zero or positive integers. Timing fields are zero or positive numbers in milliseconds.

13. If a valid stream has zero entries, the function should return an empty message list and diagnostics with all zero counts.

14. Reading the same file many times should return the same output. Returned payloads should stay isolated between calls, and concurrent reads through the metrics API should be thread-safe.

15. Keep `/app/data/messages.bin` unchanged.
