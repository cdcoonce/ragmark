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
class GoldenRegression:
    """One query's recall change between a baseline and current report."""

    query: str
    baseline_recall: float
    current_recall: float
    delta: float


@dataclass(frozen=True, slots=True)
class GoldenProvenance:
    """The inputs a saved report was measured against — attribution, not math.

    `evaluate` never constructs this; the CLI gathers the values (oracle
    bytes, corpus counts, model identity, vault git state) and attaches it,
    per the module's FORMAT/MATH-vs-gathering split.
    """

    oracle_path: str
    oracle_sha256: str
    query_count: int
    vault_revision: str | None
    vault_dirty: bool | None
    note_count: int
    chunk_count: int
    model_name: str
    model_dim: int
    model_version: str
    fusion: str
    ragmark_version: str | None


@dataclass(frozen=True, slots=True)
class GoldenReport:
    """Aggregate evaluation of a golden set."""

    rows: tuple[GoldenRow, ...]
    mean_recall: float
    provenance: GoldenProvenance | None = None


def load_golden(path: Path, vault_root: Path | None = None) -> list[GoldenQuery]:
    """Load and validate a golden-query file.

    If *vault_root* is given, every 'expect' path is additionally checked to
    resolve to an existing file under it, failing fast on the first offending
    entry (query order, then 'expect' order). Without *vault_root*, existence
    is not checked — today's behavior.
    """
    if not path.exists():
        raise FileNotFoundError(f"golden file not found: {path}")
    if vault_root is not None and not vault_root.exists():
        raise ValueError(f"vault_root not found: {vault_root}")
    resolved_root = vault_root.resolve() if vault_root is not None else None
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
        if resolved_root is not None:
            for expect_path in expect:
                prefix = f"query #{position}: 'expect' path {expect_path!r}"
                if not isinstance(expect_path, str):
                    raise ValueError(f"{prefix} must be a string")
                if Path(expect_path).is_absolute():
                    raise ValueError(f"{prefix} must be relative to vault_root")
                candidate = (resolved_root / expect_path).resolve()
                try:
                    candidate.relative_to(resolved_root)
                except ValueError:
                    raise ValueError(f"{prefix} escapes vault_root") from None
                if not candidate.is_file():
                    raise ValueError(f"{prefix} does not exist under vault_root")
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


def diff_reports(baseline: GoldenReport, current: GoldenReport) -> tuple[GoldenRegression, ...]:
    """Pair rows from *baseline* and *current* by query text.

    One `GoldenRegression` per query present in both reports, in
    `baseline.rows` order. Queries present in only one report are excluded.
    Includes improvements and unchanged queries, not only regressions —
    callers filter for `delta < 0` themselves.
    """
    current_by_query = {row.query: row for row in current.rows}
    regressions: list[GoldenRegression] = []
    for baseline_row in baseline.rows:
        current_row = current_by_query.get(baseline_row.query)
        if current_row is None:
            continue
        regressions.append(
            GoldenRegression(
                query=baseline_row.query,
                baseline_recall=baseline_row.recall,
                current_recall=current_row.recall,
                delta=current_row.recall - baseline_row.recall,
            )
        )
    return tuple(regressions)
