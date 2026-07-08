# Decoder Incident Runbook

The corpus in `/app/data/messages.bin` is a single-segment stream with a fixed top-level shape, but the brittle behavior appears only after deeper pointer walks.

Start by probing the stream in a way that preserves signal:

1. Decode once and compare where the parser diverges versus where the stream was successfully decoded before.
2. Only then trace back through pointer indirections to find the first wrong stride.
3. Keep fixes structural; avoid single-message patches.

`decode_message()` is also used directly by callers, so module and CLI behavior must remain consistent.
