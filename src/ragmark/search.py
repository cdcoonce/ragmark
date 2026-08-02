"""Search — hybrid retrieval and the note-level similarity view (owed to slices).

Decided behavior:

- **Hybrid v1** (the-vault#140, decision 4): a BM25-style lexical leg fused
  with vector scores by rank fusion, pure Python over the same chunk store —
  exact identifiers ("trunk_branch", "afk#1089") stop whiffing.
- **Gating in core** (decision 8): hits are context-filtered HERE, before any
  surface sees them. The server-side caps live here too, because the caller
  is the untrusted party: k is clamped to `MAX_RESULTS`, and the index is
  over-fetched by `OVERFETCH` before filtering so an out-of-context top-k
  cannot under-deliver.
- **Auto-refresh** (decision 7): every search runs the mtime gate first;
  callers never see or manage staleness.
- **One artifact, two views** (the-vault#143): chunk-level `search` plus the
  DOCUMENTED note-level `similar_notes` (mean-pooled chunk vectors, or the
  slice's measured successor). The predecessor's private `_load_index()`
  reach dies with this module.
- Graph-awareness is NOT here (decision 5): no graph boost in ranking, ever.
  Widening is the caller's explicit choice via `ragmark.neighbors`.
"""

from __future__ import annotations

from ragmark.config import RagmarkConfig
from ragmark.embed import Embedder
from ragmark.model import SearchHit
from ragmark.store import IndexStore

MAX_RESULTS = 25
DEFAULT_RESULTS = 8
OVERFETCH = 4


def search(
    query: str,
    k: int = DEFAULT_RESULTS,
    *,
    config: RagmarkConfig,
    store: IndexStore,
    embedder: Embedder,
) -> list[SearchHit]:
    """Hybrid search returning up to *k* context-visible chunk hits.

    `config` is required rather than defaulted: it is where the machine
    context comes from, and an optional scoping argument would fail open in
    the one place that must fail closed.
    """
    raise NotImplementedError("build slice: hybrid search (the-vault#140 d4)")


def similar_notes(
    note_path: str,
    k: int = DEFAULT_RESULTS,
    *,
    config: RagmarkConfig,
    store: IndexStore,
) -> list[tuple[str, float]]:
    """Note-level similarity: (note_path, score), context-filtered.

    This is the public view /connect-class consumers use; its pooling
    semantics are documented API, not an implementation reach.
    """
    raise NotImplementedError("build slice: note-level view (the-vault#143 d1)")
