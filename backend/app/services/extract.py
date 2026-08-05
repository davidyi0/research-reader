"""PyMuPDF text extraction: PDF bytes -> one text string per page.

Reading order is the load-bearing part of this module. Neither obvious option
works on a two-column paper:

  * `get_text("text")` follows the PDF content stream, whose order is whatever
    the producing tool emitted.
  * `sort=True` sorts blocks top-to-bottom, which *interleaves* the two columns —
    alternating sentences from the left and right column. The model then receives
    scrambled prose and produces a confident, wrong explanation, with nothing
    anywhere to signal that it went wrong.

So blocks are ordered explicitly. A block that crosses the page midline spans
the full width (title, abstract, a wide figure) and acts as a band boundary;
blocks that sit entirely on one side are column content. Within each band the
whole left column is emitted before the whole right column.

This test also degrades correctly on single-column papers: their body text is
centered and wide, so every block crosses the midline, every block is a band
boundary, and the result is plain top-to-bottom order.
"""
from dataclasses import dataclass

import fitz  # PyMuPDF

# Below this many characters per page there is no text layer to work with — the
# PDF is a scan. Pages render fine and selection silently does nothing, so this
# has to be caught at ingest and reported, not discovered by a confused user.
_SCAN_CHARS_PER_PAGE = 100

# get_text("blocks") tuples: (x0, y0, x1, y1, text, block_no, block_type).
_X0, _Y0, _X1, _TEXT, _TYPE = 0, 1, 2, 4, 6
_TEXT_BLOCK = 0


@dataclass
class ExtractResult:
    pages: list[str]  # index i holds page i+1; pages are 1-indexed everywhere else
    page_count: int
    is_scanned: bool


def _ordered_page_text(page) -> str:
    blocks = [
        b for b in page.get_text("blocks")
        if b[_TYPE] == _TEXT_BLOCK and b[_TEXT].strip()
    ]
    if not blocks:
        return ""

    mid = page.rect.x0 + page.rect.width / 2
    ordered: list[tuple] = []
    left: list[tuple] = []
    right: list[tuple] = []

    def flush() -> None:
        # Everything buffered since the last full-width block sits above it:
        # emit the left column top-to-bottom, then the right.
        ordered.extend(sorted(left, key=lambda b: b[_Y0]))
        ordered.extend(sorted(right, key=lambda b: b[_Y0]))
        left.clear()
        right.clear()

    for b in sorted(blocks, key=lambda b: b[_Y0]):
        if b[_X0] < mid < b[_X1]:
            flush()
            ordered.append(b)
        elif b[_X1] <= mid:
            left.append(b)
        else:
            right.append(b)
    flush()

    text = "\n".join(b[_TEXT].strip() for b in ordered)
    # Malformed embedded fonts occasionally decode to NUL bytes, which
    # PostgreSQL's text type rejects outright (confirmed against a real paper).
    return text.replace("\x00", "")


def extract(pdf_bytes: bytes) -> ExtractResult:
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        pages = [_ordered_page_text(page) for page in doc]

    page_count = len(pages)
    total_chars = sum(len(p) for p in pages)
    is_scanned = page_count > 0 and (total_chars / page_count) < _SCAN_CHARS_PER_PAGE

    return ExtractResult(pages=pages, page_count=page_count, is_scanned=is_scanned)
