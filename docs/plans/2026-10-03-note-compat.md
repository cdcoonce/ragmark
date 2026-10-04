# Note-level compatibility presentation

Date: 2026-10-03
Status: local implementation; not wired into production
Authority: ragmark#94 permits a `ragmark.compat` module; the owner delegated
this bounded presentation adapter separately from retrieval and scope changes.

## Contract

`ragmark.compat.note_results(hits: Sequence[SearchHit], k: int = 8) -> list[dict]`
consumes already-gated, ranked chunk hits. It uses the first supplied chunk for
each distinct `note_path`, preserves that order (including ties), and returns
exactly the legacy `note_path`, `score`, and `snippet` fields. The supplied score
and snippet remain unchanged. Fused scores are not calibrated similarities, so
the predecessor's 0.2 cutoff does not apply.

The limit counts distinct notes after deduplication. As in core search, an
integer `k <= 0` returns an empty list; values above 25 are silently capped;
the default is 8. A local private cap avoids importing the retrieval engine
into this module. Fixture tests compare the cap and default with the existing
core constants to expose future drift. The integer type contract is unchanged;
the adapter adds no separate coercion policy.

Fewer unique supplied notes produce fewer results. The adapter neither refills
results nor queries, refreshes an index, loads a model, reads files, or applies
gating. The caller remains responsible for supplying context-visible hits.
There is no CLI, MCP, configuration, metadata, or production-search change.

## Citation boundary

Legacy dictionaries do not contain a chunk ID. They are a note presentation,
not sufficient evidence for the future generation citation contract. Callers
requiring exact source citations must retain the original `SearchHit` values
and their `chunk_id` fields. The adapter does not mutate those hits, fabricate
a note-level chunk ID, or extend the legacy dictionary shape.

## Validation

TDD was applied in small cycles: the first behavior failed with the absent
module, the distinct-note limit failed with an extra result, nonpositive limits
failed with a nonempty result, and the core cap failed at 30 versus 25. Each
failure was observed before its corresponding implementation. Additional
fixtures confirm the already-implemented ordering, unchanged low fused scores
and long snippets, default limit, preserved source hits, and truthful short or
empty results.

The subsequent Workshop shim integration adds `compat.status(config, store,
expected_identity)`, a public wrapper around the separate read-only inspector.
It forwards states, unknown counts, and remediation unchanged; it does not
initialize or refresh indexes. The no-files purity contract above applies to
`note_results`, not this status operation.

Focused validation: 12 non-model tests in `tests/test_compat.py` pass; Ruff lint
and format checks pass for the adapter and its tests. Tests use synthetic hits,
not protected golden data, an index, or a model. The combined repository gate
remains the parent task's responsibility before any publication. No retrieval
quality, production integration, or context-gating claim follows from these
presentation tests.
