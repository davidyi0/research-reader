"""Assemble the scoped context for one explanation request.

Whole-paper context (~25k tokens) is only economical with explicit prompt
caching, which the provider-generic requirement rules out. So the window is
built locally instead: title + abstract, the text around the selection, and the
selection itself, marked. ~2-3k tokens total.

The subtle part is locating the selection. The query string comes out of pdf.js's
text layer in the browser; the haystack comes from PyMuPDF on the server. Those
are two different extractors and they disagree — on ligatures (`ﬁ` vs `fi`),
on hyphenation across line breaks (`ob-\\njective`), and on whitespace. Both
were confirmed present in real papers during Stage 1. A plain
`page_text.find(selected_text)` therefore misses far more often than it looks
like it should, so both sides are normalised before the search and the match
degrades to a prefix anchor rather than failing outright.
"""
import re
import unicodedata

from app.models import Paper
from app.services.llm import estimate_tokens

# Reserve room for the title/abstract header and the model's own reply; the rest
# of LLM_MAX_CONTEXT_TOKENS goes to the window around the selection.
_HEADER_TOKEN_ALLOWANCE = 400
# Fall back to matching this many leading characters when the full string misses.
_ANCHOR_LENGTHS = (60, 30)

_SOFT_HYPHEN = "­"
_LINEBREAK_HYPHEN_RE = re.compile(r"-\s*\n\s*")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Canonical form for both matching and prompt text.

    NFKC does the heavy lifting: it decomposes ligatures, so `ﬁt` and `fit`
    converge without a hand-maintained character table. What it does not do is
    rejoin words split across a line break, or drop soft hyphens, so those are
    handled explicitly.
    """
    text = unicodedata.normalize("NFKC", text)
    text = text.replace(_SOFT_HYPHEN, "")
    text = _LINEBREAK_HYPHEN_RE.sub("", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def locate(page_text: str, selection: str) -> int | None:
    """Index of `selection` within `page_text`. Both must already be normalised.

    Returns None when the selection genuinely isn't on this page — a real case,
    since a selection can span a page boundary.
    """
    haystack, needle = page_text.lower(), selection.lower()
    if not needle:
        return None

    idx = haystack.find(needle)
    if idx != -1:
        return idx

    # Anchor on the opening characters. A selection that starts cleanly but
    # diverges later (a footnote marker spliced mid-sentence, a column break)
    # still locates correctly, and the window is what we actually need.
    for n in _ANCHOR_LENGTHS:
        if len(needle) > n:
            idx = haystack.find(needle[:n])
            if idx != -1:
                return idx
    return None


def window_around(page_text: str, index: int | None, budget_chars: int) -> str:
    """`budget_chars` of page text centred on the match, snapped to word edges."""
    if len(page_text) <= budget_chars:
        return page_text
    if index is None:
        return page_text[:budget_chars]

    half = budget_chars // 2
    start = max(0, index - half)
    end = min(len(page_text), start + budget_chars)
    start = max(0, end - budget_chars)

    # Avoid opening or closing mid-word.
    if start > 0 and (space := page_text.find(" ", start)) != -1:
        start = space + 1
    if end < len(page_text) and (space := page_text.rfind(" ", start, end)) != -1:
        end = space
    return page_text[start:end].strip()


def build(paper: Paper, page_text: str, selected_text: str, max_tokens: int) -> str:
    """The user-role message for an explanation request.

    Sections and prior terms are deliberately absent: `sections` is populated at
    P3 and `terms` at P4. The window is the whole context until then.
    """
    page_text = normalize(page_text)
    selection = normalize(selected_text)
    index = locate(page_text, selection)

    header = [f"Paper title: {paper.title or 'Unknown'}"]
    if paper.abstract:
        header.append(f"Abstract: {normalize(paper.abstract)}")
    header_text = "\n\n".join(header)

    spare = max_tokens - estimate_tokens(header_text) - estimate_tokens(selection)
    budget_chars = max(0, (spare - _HEADER_TOKEN_ALLOWANCE)) * 4

    return (
        f"{header_text}\n\n"
        f"Surrounding text from the page the reader is on:\n"
        f"\"\"\"\n{window_around(page_text, index, budget_chars)}\n\"\"\"\n\n"
        f"The reader selected this and wants it explained:\n"
        f"\"\"\"\n{selection}\n\"\"\""
    )
