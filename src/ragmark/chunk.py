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

from collections.abc import Callable

from ragmark.model import Chunk, NoteMeta

# The embedding window is 512 tokens for the seed model family; the ceiling is
# HARD — the chunker refuses to emit past it regardless of model, because the
# defect class this kills was "the model will handle it".
HARD_TOKEN_CEILING = 512

# Packing target, carried from the proven heading-split pattern.
CHUNK_TARGET_TOKENS = 300


def chunk_note(
    note_path: str,
    body: str,
    meta: NoteMeta,
    count_tokens: Callable[[str], int],
) -> list[Chunk]:
    """Chunk one note into embeddable units per the contract above.

    `count_tokens` is the *embedder's* tokenizer (injected so the ceiling is
    measured in the same units the model truncates in — a character-proxy
    ceiling is how the original defect stayed invisible).
    """
    raise NotImplementedError("build slice: hardened chunker (the-vault#140 d1)")
