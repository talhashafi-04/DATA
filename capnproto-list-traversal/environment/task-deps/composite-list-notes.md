# Composite List Notes

Composite lists start with a normal list pointer whose element-size code is `7`. The list pointer's count field describes the payload that follows the tag word.

The target word is a struct tag. It uses the struct-pointer layout to describe each element's data-word and pointer-word sections. Older captures in this corpus carry tag bits inherited from a prior writer generation, so treat the tag as a layout descriptor rather than as the sole source of traversal length.

For this corpus, `Point` elements carry scalar data only, while `Segment` elements carry scalar data followed by a pointer section.
