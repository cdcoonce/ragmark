"""Legacy note presentation and read-only index status (ragmark#94).

For note_results, callers supply already-gated, ranked SearchHits; that pure
adapter does not query, refresh, load models, read files, or apply gating.
The separate status wrapper performs read-only filesystem/index inspection.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from ragmark.model import ModelIdentity, SearchHit

if TYPE_CHECKING:
    from ragmark.config import RagmarkConfig
    from ragmark.store import IndexStore

# Match search.MAX_RESULTS without importing the retrieval engine here.
_MAX_RESULTS = 25


def note_results(hits: Sequence[SearchHit], k: int = 8) -> list[dict]:
    """Present each note using its first (highest-ranked supplied) chunk.

    Preserve the supplied ranking, fused score, and snippet without a score
    threshold. The legacy shape contains only note_path, score, and snippet;
    keep the original SearchHits when chunk-ID citations are needed.

    As in core search, nonpositive k returns no results and k above 25 is
    clamped. Fewer distinct supplied notes yield a truthful shorter result.
    """
    effective_k = min(k, _MAX_RESULTS)
    if effective_k <= 0:
        return []
    results = []
    seen = set()
    for hit in hits:
        if hit.note_path in seen:
            continue
        seen.add(hit.note_path)
        results.append({"note_path": hit.note_path, "score": hit.score, "snippet": hit.snippet})
        if len(results) == effective_k:
            break
    return results


def status(
    config: RagmarkConfig, store: IndexStore, expected_identity: ModelIdentity
) -> dict[str, object]:
    """Return the read-only compatibility status without reinterpreting it.

    Missing, stale, corrupt, or mismatched states stay explicit. No timestamp
    is invented, and this call neither initializes nor refreshes an index.
    """
    from ragmark._compat_status import inspect_status

    return inspect_status(config, store, expected_identity)
