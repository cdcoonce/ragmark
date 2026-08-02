"""Gap detection — the policy migrates INTO ragmark (the-vault#143, decision 2).

ragmark owns gap/weak-connection detection end-to-end. What moves here from
graphmark's `metrics.py`: the banding constants below (verbatim), the
already-linked / transient-prefix filtering, the (non-hub, cross-folder,
score-desc) ranking, and the content-hash dismissal-store semantics
(`connect-dismissed.json` — a dismissed pair stays suppressed only while both
notes exist with unchanged content).

What stays in graphmark: the deterministic graph itself — this module
consumes graphmark for structure (degree/hub facts, linked-pair queries) and
ragmark's own note-level similarity for scores. graphmark's `gaps()`
deprecates only AFTER this lands (absorption staging puts the two-repo step
LAST — the-vault#140, decision 10; deprecation path recorded on graphmark's
ROADMAP, graphmark#197).
"""

from __future__ import annotations

from pathlib import Path

from ragmark.config import RagmarkConfig

# Banding policy, verbatim from graphmark metrics.py at migration decision time.
GAPS_DEFAULT_THRESHOLD = 0.6
GAPS_DEFAULT_MAX_SCORE = 0.92
GAPS_DEFAULT_K = 8
GAPS_DEFAULT_HUB_DEGREE = 40


def gaps(
    *,
    config: RagmarkConfig,
    threshold: float = GAPS_DEFAULT_THRESHOLD,
    max_score: float = GAPS_DEFAULT_MAX_SCORE,
    k: int = GAPS_DEFAULT_K,
    hub_degree: int = GAPS_DEFAULT_HUB_DEGREE,
    dismissal_store: Path | None = None,
) -> list[tuple[str, str, float]]:
    """Ranked unlinked-but-similar note pairs (see module contract)."""
    raise NotImplementedError("build slice: gap policy migration (the-vault#143 d2)")
