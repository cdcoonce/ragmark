"""Chunking — hardened heading-split with a HARD sub-ceiling (owed to slices).

This module exists to make the predecessor's worst defect structurally
impossible. The vendored chunker's oversize-section escape hatch emitted any
section exceeding the window WHOLE and unbounded; the embedding model then
silently truncated at 512 tokens — 27.8% of corpus characters were never
embedded (measured, the-vault#137). The contract here (the-vault#140,
decision 1):

- Heading-split, then pack sections toward `CHUNK_TARGET_TOKENS`.
- A section that exceeds the window is SPLIT — at paragraph boundaries, then
  sentence boundaries — never emitted whole. Emitting a chunk over
  `HARD_TOKEN_CEILING` must be impossible by construction.
- The frontmatter `description` is emitted as standalone chunk 0 when present.
- Every chunk records `parent_ref` (its enclosing heading section) so
  retrieval can expand a small hit to its parent.

The permanent regression property (the-vault#144): total embedded characters
must equal total chunkable characters — no silent truncation, ever again.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from ragmark.model import Chunk, NoteMeta
from ragmark.parse import render_for_embedding

# The embedding window is 512 tokens for the seed model family; the ceiling is
# HARD — the chunker refuses to emit past it regardless of model, because the
# defect class this kills was "the model will handle it".
HARD_TOKEN_CEILING = 512

# Packing target, carried from the proven heading-split pattern.
CHUNK_TARGET_TOKENS = 300

# Heading detection on the RAW body, before parse.render_for_embedding strips
# heading markers — mirrors parse._HEADING_RE but anchored to one line (no
# MULTILINE) since it is matched line-by-line to track fence state.
_HEADING_LINE_RE = re.compile(r"^(#{1,6})[ \t]+(\S.*?)\s*$")
_FENCE_TOGGLE_RE = re.compile(r"^\s*```")

_BLANK_LINES_RE = re.compile(r"\n{2,}")
_SENTENCE_END_RE = re.compile(r"[.!?]+(?:\s+|$)")

_TokenCounter = Callable[[str], int]


def chunk_note(
    note_path: str,
    body: str,
    meta: NoteMeta,
    count_tokens: _TokenCounter,
) -> list[Chunk]:
    """Chunk one note into embeddable units per the contract above.

    `count_tokens` is the *embedder's* tokenizer (injected so the ceiling is
    measured in the same units the model truncates in — a character-proxy
    ceiling is how the original defect stayed invisible).
    """
    chunks: list[Chunk] = []
    index = 0

    if meta.description is not None:
        chunks.append(
            Chunk(
                chunk_id=f"{note_path}#{index}",
                note_path=note_path,
                chunk_index=index,
                heading=None,
                parent_ref=None,
                text=meta.description,
                token_count=count_tokens(meta.description),
            )
        )
        index += 1

    for heading, parent_ref, raw_section in _split_heading_sections(body):
        rendered = render_for_embedding(raw_section)
        for piece in _pack_section(rendered, count_tokens):
            chunks.append(
                Chunk(
                    chunk_id=f"{note_path}#{index}",
                    note_path=note_path,
                    chunk_index=index,
                    heading=heading,
                    parent_ref=parent_ref,
                    text=piece,
                    token_count=count_tokens(piece),
                )
            )
            index += 1

    return chunks


# --- heading split (raw body, fence-aware) -----------------------------------


def _split_heading_sections(body: str) -> list[tuple[str | None, str | None, str]]:
    """Split the RAW body into (heading, parent_ref, text) sections.

    A `#`-line inside a fenced code block is not a heading — matched
    line-by-line so fence state can be tracked and skipped (step 2 of the
    module contract). Sections partition `body` exactly: concatenating every
    section's text reproduces `body` byte-for-byte.
    """
    sections: list[tuple[str | None, str | None, str]] = []
    stack: list[tuple[int, str]] = []
    current_heading: str | None = None
    current_parent: str | None = None
    buffer: list[str] = []
    in_fence = False

    def flush() -> None:
        if buffer:
            sections.append((current_heading, current_parent, "".join(buffer)))
            buffer.clear()

    for line in body.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        if _FENCE_TOGGLE_RE.match(content):
            in_fence = not in_fence
            buffer.append(line)
            continue
        if not in_fence:
            match = _HEADING_LINE_RE.match(content)
            if match is not None:
                flush()
                level = len(match.group(1))
                text = match.group(2)
                while stack and stack[-1][0] >= level:
                    stack.pop()
                current_parent = " > ".join(t for _, t in stack) if stack else None
                stack.append((level, text))
                current_heading = text
                buffer.append(line)
                continue
        buffer.append(line)

    flush()
    return sections


# --- packing / hard-ceiling splitting -----------------------------------------


def _pack_section(text: str, count_tokens: _TokenCounter) -> list[str]:
    return _pack_units(
        _split_paragraphs(text), count_tokens, _split_oversized_paragraph, CHUNK_TARGET_TOKENS
    )


def _split_oversized_paragraph(text: str, count_tokens: _TokenCounter) -> list[str]:
    return _pack_units(_split_sentences(text), count_tokens, _split_oversized_sentence, None)


def _split_oversized_sentence(text: str, count_tokens: _TokenCounter) -> list[str]:
    return _pack_units(_split_words(text), count_tokens, _split_atomic, None)


def _split_atomic(text: str, count_tokens: _TokenCounter) -> list[str]:
    """Terminal tier: greedily grow by raw characters (step 5, DECIDED)."""
    return _pack_units(list(text), count_tokens, lambda unit, _ct: [unit], None)


def _pack_units(
    units: list[str],
    count_tokens: _TokenCounter,
    split_fn: Callable[[str, _TokenCounter], list[str]],
    target: int | None,
) -> list[str]:
    """Greedily pack `units` (an exact partition of some string) into pieces
    that never exceed `HARD_TOKEN_CEILING`, flushing early once `target` is
    reached when one is given. A unit that alone exceeds the ceiling is
    handed to `split_fn` for finer-grained splitting.
    """
    pieces: list[str] = []
    current = ""
    for unit in units:
        if count_tokens(unit) > HARD_TOKEN_CEILING:
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(split_fn(unit, count_tokens))
            continue
        candidate = current + unit
        if current and count_tokens(candidate) > HARD_TOKEN_CEILING:
            pieces.append(current)
            current = unit
        else:
            current = candidate
        if target is not None and count_tokens(current) >= target:
            pieces.append(current)
            current = ""
    if current:
        pieces.append(current)
    return pieces


def _split_paragraphs(text: str) -> list[str]:
    return _split_on_boundaries(text, _BLANK_LINES_RE)


def _split_sentences(text: str) -> list[str]:
    return _split_on_boundaries(text, _SENTENCE_END_RE)


def _split_on_boundaries(text: str, boundary_re: re.Pattern[str]) -> list[str]:
    """Split `text` right after each boundary match, keeping the matched
    separator attached to the piece before it — an exact partition."""
    if not text:
        return []
    matches = list(boundary_re.finditer(text))
    if not matches:
        return [text]
    pieces = []
    start = 0
    for match in matches:
        end = match.end()
        pieces.append(text[start:end])
        start = end
    if start < len(text):
        pieces.append(text[start:])
    return [p for p in pieces if p]


def _split_words(text: str) -> list[str]:
    """Whitespace-delimited words, each carrying its trailing whitespace —
    an exact partition of `text`."""
    words = []
    i = 0
    n = len(text)
    while i < n:
        j = i
        while j < n and not text[j].isspace():
            j += 1
        while j < n and text[j].isspace():
            j += 1
        words.append(text[i:j])
        i = j
    return words
