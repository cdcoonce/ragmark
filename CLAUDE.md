# ragmark — Agent Operating Rules

`ragmark` is **local-first retrieval over markdown / `[[wikilink]]` vaults** — hybrid
(vector + lexical) chunk search, a documented note-level similarity view, wikilink-aware
context expansion, and a first-party MCP surface. Embeddings run locally (fastembed); the
package makes no network egress at query time. Sibling of `graphmark`, which it consumes for
deterministic graph reads.

This file governs autonomous (afk) work in this repo. It is the contract.

## Non-negotiables

- **The quality oracle is the golden-query set, and it is executor-untouchable.** The golden
  data file is hand-curated by the owner (it lives vault-side, never in this repo — vault note
  content never ships). You may run it (`ragmark golden`), you may never generate, edit, or
  "fix" golden data. It grows only by a human adding the reproducing query for a found defect.
  There is deliberately NO parity oracle against the predecessor (improve-during-cutover,
  the-vault#143) — this harness and the invariants below are the only safety mechanism.
- **Safety invariants are permanent.** No silent embedding truncation (total embedded chars ==
  total chunkable chars — the predecessor silently dropped 27.8%); every indexed note
  retrievable; chunk↔vector conservation; context gating never leaks. Assertions bind at
  rank/set level with the model pinned via the index manifest — never at vector bytes.
- **The gating suite is teeth-checked, in CI.** `scripts/teeth_check.py` re-runs the
  `gating`-marked tests with the filter defanged and requires red. A gating test that stays
  green with the filter off is a build failure. Never weaken a `gating` test to make teeth
  pass.
- **Implement within the seeded interfaces.** `model.py`, `config.py`, `gate.py`'s boundary,
  and the module seams define the shape; the MCP face (names, args, annotations) is a decided
  contract (the-vault#142) pinned by `tests/test_mcp_face.py`. Do not redesign boundaries or
  rename their types. Exception: an issue that explicitly directs a seeded-surface change (a
  human-triaged decision, recorded in the issue) wins — follow the issue.
- **Owed-behavior xfails are conductor-owned.** `tests/test_contract.py` marks unimplemented
  seams with strict xfails. When your slice implements one, the xfail XPASSes and fails the
  suite — the same PR must replace it with real behavior tests (pre-frozen by the conductor
  where the slice plan says so).
- **TDD, always.** Failing test first, watch it fail, minimum to pass, refactor. Small,
  single-purpose PRs. Conventional commits; stage explicitly.
- **Human merge gate.** Nothing merges without human review.

## The gate

A change is publishable only if this exits 0:

```
uv run --extra dev ruff check . && uv run --extra dev ruff format --check . \
  && uv run --extra dev pytest -q && uv run --extra dev python scripts/teeth_check.py
```

## Architecture (keep the layers separate)

1. **Engine** (`parse.py`, `chunk.py`, `embed.py`, `store.py`, `index.py`, `search.py`) —
   vault-agnostic; every behavior decided on the map is cited in its module docstring.
2. **Config** (`config.py`) — the domain seam. All vault-specific behavior is config;
   `configs/the-vault.toml` is the reference instance.
3. **Gate** (`gate.py`) — the security core. Fail-closed machine-context scoping and the
   single resolve-then-contain access boundary. EVERY surface routes through it; context is
   read server-side, never accepted from a caller.
4. **Surfaces** (`cli.py`, `mcp.py`) — thin faces over the same core. The MCP face is
   read-only and exposes no maintenance; `ragmark index` is CLI-only (deliberate asymmetry).
5. **Gaps** (`gaps.py`) — policy migrated from graphmark (constants verbatim); graphmark's
   `gaps()` deprecates only after this lands, and that two-repo step is staged LAST.

## Decided behavior (must match — provenance in each module docstring)

- Chunking: heading-split, HARD sub-512-token ceiling (split paragraph → sentence, never emit
  whole), frontmatter description as chunk 0, parent-section refs. Real YAML frontmatter;
  tags/aliases indexed; markup stripped for embedding.
- Store: flat `vectors.npy` + one SQLite file; all writes temp+rename atomic; model identity
  recorded and checked (mismatch = detected error prompting rebuild).
- Staleness: mtime-gated auto-refresh on the query path; `reindex --force` for rebuilds.
- Search: hybrid rank fusion; k clamped to 25; over-fetch ×4 before context filtering; no
  graph boost in ranking, ever — graph-awareness is only the explicit `vault_neighbors` tool.
- MCP face: `vault_search` / `vault_read` (bare text) / `vault_neighbors` (structure always
  complete, budget limits content only, backlinks first-class) / `recent_activity`
  (git-log-backed); all annotated read-only; registered under the name `vault`.

## Out of scope (do NOT build)

Generation (later phase; two contracts already bind it: citations must be chunk-IDs from the
retriever, and Ollama only ever via a `ragmark[generate]` extra). Cloud/API embeddings. Any
write surface over MCP. Interactive UI. Entity-extraction GraphRAG (wikilink-following won).

Provenance: blueprint map the-vault#136 (eight resolution tickets), epic the-vault#145,
MCP-face prototype `the-vault:proto/ragmark-mcp-142`.
