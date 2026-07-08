# Corpus Layout

The stream starts with a fixed ASCII signature and then a stream header. After that come raw message payloads: each entry includes a byte length followed by the bytes for a single Cap'n Proto message.

The encoded messages are single-segment, but pointer and list details can still shift the apparent element boundaries in non-obvious ways once traversal dives into nested data.

Generator outputs intentionally include:

* empty point lists
* varying segment and point counts
* label strings at different byte lengths (including UTF-8 edge cases)
* mixed traversal depths before nested points and text fields resolve

The objective is to correct traversal behavior for the whole shape, not to patch around a specific message number.
