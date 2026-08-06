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

How the two legs meet:

- The lexical leg is **BM25 in pure Python** over `chunks.text` (k1=1.2,
  b=0.75, corpus statistics per CHUNK). No FTS5 virtual table: SQLite here
  supports one, but adding it would change the decided store layout.
- Its tokenizer is the leg's whole reason to exist: lowercase, then
  `[a-z0-9_#/.-]+`, no stemming and no stopwords, so `trunk_branch` and
  `afk#1089` each survive as ONE token. A `\\w+` tokenizer splits `afk#1089`
  and silently defeats the feature.
- Fusion is **reciprocal rank fusion** (`RRF_K`), legs equal-weighted, on
  1-based ranks; a chunk missing from a leg contributes nothing from that leg.
  Ordering breaks ties on `chunk_id` so a run is reproducible across machines.
- Gating runs LAST, over the fused candidates, through `gate.filter_visible`.
  If gating leaves fewer than `k` hits the result comes back SHORT: refilling
  from a wider fetch would make the result count a function of hidden
  material, which is an inference channel.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from ragmark import gate, index
from ragmark.config import RagmarkConfig
from ragmark.embed import Embedder
from ragmark.model import SearchHit
from ragmark.store import IndexStore

MAX_RESULTS = 25
DEFAULT_RESULTS = 8
OVERFETCH = 4

# Reciprocal rank fusion's damping constant (Cormack et al.'s 60): large
# enough that the top of one leg cannot bulldoze the other leg entirely.
RRF_K = 60

# BM25 saturation and length-normalization, the decided values.
BM25_K1 = 1.2
BM25_B = 0.75

_TOKEN_RE = re.compile(r"[a-z0-9_#/.-]+")

_ChunkRow = tuple[str, str, str | None, str, int]


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

    Order of operations is load-bearing: refresh, clamp, over-fetch, fuse,
    gate, truncate. Clamping BEFORE over-fetching bounds the candidate pool at
    `MAX_RESULTS * OVERFETCH` per leg however large a `k` the caller asks for,
    and an out-of-range `k` is clamped silently rather than rejected. An
    incoherent index raises `IndexCorruptionError` from the refresh.
    """
    index.refresh(config, store, embedder)

    effective_k = min(k, MAX_RESULTS)
    if effective_k <= 0:
        return []

    conn = store.connect()
    rows = store.read_chunk_rows(conn)
    if not rows:
        return []

    limit = effective_k * OVERFETCH
    fused = _fuse(
        _vector_leg(query, rows, store, embedder, limit),
        _lexical_leg(query, rows, limit),
    )
    ranked = sorted(fused.items(), key=lambda item: (-item[1], item[0]))

    by_id = {
        chunk_id: (note_path, heading, text)
        for chunk_id, note_path, heading, text, _vector_row in rows
    }
    visible = set(gate.filter_visible([by_id[chunk_id][0] for chunk_id, _ in ranked], config))

    hits: list[SearchHit] = []
    for chunk_id, score in ranked:
        note_path, heading, text = by_id[chunk_id]
        if note_path not in visible:
            continue
        hits.append(
            SearchHit(
                chunk_id=chunk_id,
                note_path=note_path,
                heading=heading,
                score=score,
                snippet=text,
            )
        )
        if len(hits) == effective_k:
            break
    return hits


def similar_notes(
    note_path: str,
    k: int = DEFAULT_RESULTS,
    *,
    config: RagmarkConfig,
    store: IndexStore,
) -> list[tuple[str, float]]:
    """Note-level similarity: (note_path, score), context-filtered.

    This is the public view /connect-class consumers use; its pooling
    semantics are documented API, not an implementation reach:

    - A note's vector is the ARITHMETIC MEAN of its chunk vectors, then
      L2-normalized. A note with no chunk rows (or a pooled vector of length
      zero) is omitted entirely rather than scored as `nan`.
    - The metric is COSINE, so scores land in [-1, 1] — the band a downstream
      consumer applies ([0.6, 0.92]) is only meaningful on that scale.
    - `note_path` never appears in its own results.

    Unlike `search`, this does NOT auto-refresh: its signature takes no
    `Embedder`, deliberately, so it cannot embed anything and must read the
    index as it stands. Callers wanting fresh vectors run `search` or
    `ragmark index` first.

    The source note is gated FIRST, through `gate.resolve_note`, so an
    out-of-context or missing source raises the same opaque `VaultAccessError`
    every other reader raises.
    """
    import numpy as np

    resolved = gate.resolve_note(note_path, config)
    origin_path = resolved.relative_to(config.vault_root.resolve()).as_posix()

    effective_k = min(k, MAX_RESULTS)
    if effective_k <= 0:
        return []

    matrix = store.load_vectors()
    rows = store.read_chunk_rows(store.connect())
    if matrix is None or not rows:
        return []

    grouped: dict[str, list[int]] = {}
    for _chunk_id, chunk_note_path, _heading, _text, vector_row in rows:
        if 0 <= vector_row < matrix.shape[0]:
            grouped.setdefault(chunk_note_path, []).append(vector_row)

    pooled: dict[str, Any] = {}
    for path, vector_rows in grouped.items():
        vector = matrix[vector_rows].mean(axis=0)
        norm = float(np.linalg.norm(vector))
        if norm == 0.0:
            continue
        pooled[path] = vector / norm

    origin = pooled.get(origin_path)
    if origin is None:
        return []

    scored = [
        (path, float(vector @ origin)) for path, vector in pooled.items() if path != origin_path
    ]
    visible = set(gate.filter_visible([path for path, _ in scored], config))
    ranked = sorted(
        ((path, score) for path, score in scored if path in visible),
        key=lambda item: (-item[1], item[0]),
    )
    return ranked[:effective_k]


# --- the two legs ------------------------------------------------------------


def _tokenize(text: str) -> list[str]:
    """Lowercase, then `[a-z0-9_#/.-]+` — no stemming, no stopwords.

    Identifiers survive whole: `trunk_branch`, `afk#1089`, `docs/plan.md`.
    """
    return _TOKEN_RE.findall(text.lower())


def _vector_leg(
    query: str,
    rows: list[_ChunkRow],
    store: IndexStore,
    embedder: Embedder,
    limit: int,
) -> list[str]:
    """Top-*limit* `chunk_id`s by cosine, brute force over the full matrix."""
    import numpy as np

    matrix = store.load_vectors()
    if matrix is None or matrix.shape[0] == 0:
        return []

    query_vector = np.asarray(embedder.embed([query]), dtype=np.float32)[0]
    query_norm = float(np.linalg.norm(query_vector))
    if query_norm == 0.0:
        return []

    norms = np.linalg.norm(matrix, axis=1)
    scored: list[tuple[float, str]] = []
    for chunk_id, _note_path, _heading, _text, vector_row in rows:
        if not 0 <= vector_row < matrix.shape[0]:
            continue
        norm = float(norms[vector_row])
        if norm == 0.0:
            similarity = 0.0
        else:
            similarity = float(matrix[vector_row] @ query_vector) / (norm * query_norm)
        scored.append((-similarity, chunk_id))

    scored.sort()
    return [chunk_id for _score, chunk_id in scored[:limit]]


def _lexical_leg(query: str, rows: list[_ChunkRow], limit: int) -> list[str]:
    """Top-*limit* `chunk_id`s by BM25 over `chunks.text`, pure Python.

    Each chunk row is one document, so corpus statistics (document frequency,
    average length) are per CHUNK. Only chunks a query term actually hits are
    returned: a zero-scoring chunk is absent from this leg, and absence is how
    rank fusion learns the leg had nothing to say about it.
    """
    query_terms = set(_tokenize(query))
    if not query_terms:
        return []

    documents = [(chunk_id, Counter(_tokenize(text))) for chunk_id, _, _, text, _ in rows]
    lengths = [sum(counts.values()) for _chunk_id, counts in documents]
    total_length = sum(lengths)
    count = len(documents)
    if count == 0 or total_length == 0:
        return []
    average_length = total_length / count

    document_frequency = Counter(
        term for _chunk_id, counts in documents for term in query_terms if counts[term]
    )
    idf = {
        term: math.log(1 + (count - frequency + 0.5) / (frequency + 0.5))
        for term, frequency in document_frequency.items()
    }

    scored: list[tuple[float, str]] = []
    for (chunk_id, counts), length in zip(documents, lengths, strict=True):
        score = 0.0
        for term, weight in idf.items():
            frequency = counts[term]
            if not frequency:
                continue
            denominator = frequency + BM25_K1 * (1 - BM25_B + BM25_B * length / average_length)
            score += weight * frequency * (BM25_K1 + 1) / denominator
        if score > 0.0:
            scored.append((-score, chunk_id))

    scored.sort()
    return [chunk_id for _score, chunk_id in scored[:limit]]


def _fuse(*legs: list[str]) -> dict[str, float]:
    """Reciprocal rank fusion over 1-based ranks, legs equal-weighted."""
    fused: dict[str, float] = {}
    for leg in legs:
        for rank, chunk_id in enumerate(leg, start=1):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)
    return fused
