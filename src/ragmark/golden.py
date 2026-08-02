"""Golden-query harness — the quality oracle (implemented in the seed).

The correctness contract (the-vault#144): a frozen, hand-curated set of real
queries with expected-note hits, asserted as recall@k. It is the yardstick
for the model bake-off and for every retrieval-touching slice — and with
improve-during-cutover (the-vault#143) there is no parity oracle, so this
harness is the cutover's primary safety mechanism.

Discipline, stated where the executor will read it: **the golden data file is
hand-curated and executor-untouchable.** The set grows only by a human adding
the reproducing query for a found defect (graphmark's defect-class ratchet
applied to retrieval). This module owns the FORMAT and the MATH; it never
generates or edits golden data.

File format (TOML)::

    [[query]]
    text = "what did we decide about branch protection"
    expect = ["reference/git-conventions.md", "brain/Key Decisions.md"]
    k = 8          # optional, defaults to 8

Assertions bind at rank/set level with the model pinned — never vector bytes
(the-vault#144, decision 2), so cross-platform float drift cannot flake the
suite.
"""

from __future__ import annotations

import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

DEFAULT_K = 8


@dataclass(frozen=True, slots=True)
class GoldenQuery:
    """One hand-curated query with its expected notes."""

    text: str
    expect: tuple[str, ...]
    k: int


@dataclass(frozen=True, slots=True)
class GoldenRow:
    """One query's evaluation: which expected notes were retrieved at k."""

    query: str
    recall: float
    found: tuple[str, ...]
    missed: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GoldenReport:
    """Aggregate evaluation of a golden set."""

    rows: tuple[GoldenRow, ...]
    mean_recall: float


def load_golden(path: Path) -> list[GoldenQuery]:
    """Load and validate a golden-query file."""
    if not path.exists():
        raise FileNotFoundError(f"golden file not found: {path}")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    entries = data.get("query")
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"golden file has no [[query]] entries: {path}")

    queries: list[GoldenQuery] = []
    for position, entry in enumerate(entries):
        text = entry.get("text", "")
        expect = entry.get("expect", [])
        k = entry.get("k", DEFAULT_K)
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"query #{position}: 'text' must be a non-empty string")
        if not isinstance(expect, list) or not expect:
            raise ValueError(f"query #{position}: 'expect' must be a non-empty list of paths")
        if not isinstance(k, int) or k <= 0:
            raise ValueError(f"query #{position}: 'k' must be a positive integer")
        queries.append(GoldenQuery(text=text.strip(), expect=tuple(expect), k=k))
    return queries


def evaluate(
    queries: list[GoldenQuery],
    search_notes: Callable[[str, int], list[str]],
) -> GoldenReport:
    """Run every query through *search_notes* and score recall@k.

    *search_notes* takes (query text, k) and returns ranked note paths —
    note-level, deduplicated. Recall@k for one query is
    |expected ∩ retrieved| / |expected|.
    """
    rows: list[GoldenRow] = []
    for query in queries:
        retrieved = search_notes(query.text, query.k)
        retrieved_set = set(retrieved)
        found = tuple(p for p in query.expect if p in retrieved_set)
        missed = tuple(p for p in query.expect if p not in retrieved_set)
        rows.append(
            GoldenRow(
                query=query.text,
                recall=len(found) / len(query.expect),
                found=found,
                missed=missed,
            )
        )
    mean = sum(r.recall for r in rows) / len(rows) if rows else 0.0
    return GoldenReport(rows=tuple(rows), mean_recall=mean)
