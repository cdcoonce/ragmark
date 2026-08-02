# Roadmap — ragmark (for `afk-driver --expand`)

> Read **verbatim** by `afk-driver --expand` and injected into the feature-proposing agent's
> prompt alongside the live code. Write at the altitude of **intent** — name directions and
> gaps; let the expander (and the code it reads) propose specifics. **Every proposal must
> state which Track it advances.**

## Vision

Local-first, headless **retrieval over the owner's whole vault** — hybrid chunk search,
note-level similarity, wikilink-aware context expansion, and a first-party MCP surface —
consumable by scripts/CI and by agents, with embeddings local and zero query-time egress.
Published on PyPI; absorbs the vault's proven-but-defective vendored machinery
(`semantic_index.py`, `vault_mcp.py`) into one tested package. Identity: personal
infrastructure with a public correctness story (graphmark's identity, applied to retrieval).

The central fact of this repo: **there is no parity oracle.** The cutover improves behavior
in the same motion as absorbing it (the-vault#143), so correctness is pinned by a
**quality oracle** instead — a hand-curated, executor-untouchable golden-query set
(vault-side) asserted as recall@k with the model pinned, plus permanent safety invariants
(no silent truncation, retrievability, chunk↔vector conservation, teeth-checked context
gating). The harness came WITH the seed; every retrieval-touching slice runs it.

## What's shipped (baseline — do not re-propose)

- **The seed** (hand-authored): packaging with deploy-on-promotion (semantic-release +
  PyPI Trusted Publishing, graphmark's machinery), the CI gate (2 OS × py3.11–3.13 +
  teeth-check), typed public interfaces for every module, the **gate implemented**
  (fail-closed machine-context scoping + resolve-then-contain boundary, migrated from
  `vault_mcp.py`), the **store's infrastructure** (SQLite schema, atomic writes, model
  identity check), the **golden harness** (loader, recall@k evaluator, CLI runner,
  `--min-recall` gate), the MCP face pinned by contract tests, and the CLI skeleton.
- **Decided constants**, pinned by `tests/test_contract.py`: 512 hard chunk ceiling, k≤25,
  overfetch ×4, neighbor budget 4000, gap banding (0.6 / 0.92 / 8 / 40).

## Direction

### Track A — Engine: from interfaces to a working index

The owed seams, in dependency order: real-YAML frontmatter parse + embedding normalization
(`parse.py`); the hardened chunker (`chunk.py` — the module docstring is the spec; the
conservation property is the point); the fastembed embedder with a durable model cache
(`embed.py` — the predecessor cached to OS-evictable $TMPDIR); incremental note→chunk→vector
writes and the **mtime-gated auto-refresh on the query path** (`index.py`). Exit: `ragmark
index` builds the reference vault and the conservation + retrievability invariants run green
as real tests, not owed markers.

### Track B — Retrieval: hybrid search and the note-level view

Vector leg (brute-force cosine over the flat matrix — measured fast enough through 50k
chunks; do not add an ANN dependency), BM25-style lexical leg over the same store, rank
fusion (`search.py`), then the documented note-level similarity view (the-vault#143 killed
the private `_load_index` reach). **The model bake-off gates this track's completion**: run
the golden set over candidate models, pick, pin — the harness exists before any of this by
construction. No graph boost in ranking, ever.

### Track C — Graph surfaces

`vault_neighbors` on graphmark reads (structure-complete, content-budgeted, backlinks
first-class) and git-log-backed `recent_activity`. Both context-gated in core. The MCP face
and CLI are already shaped and contract-pinned — these tracks light them up.

### Track D — Absorption: the vault cuts over (order is BINDING)

Risk-ascending staging (the-vault#140 d10): (1) `/find`'s `semantic_index.py` becomes a thin
ragmark shim; (2) `vault_mcp.py` becomes a shim registering the packaged server (name stays
`vault`); (3) **last**, the gaps-policy migration completes (`gaps.py`) and graphmark's
`gaps()` deprecation executes per the path recorded on graphmark's ROADMAP (graphmark#197) —
the only two-repo step. Falsifiable exit (the-vault#139, verbatim): a grep for `fastembed`
across the vault and vault-ops machinery hits only ragmark shims; the engine is deleted
upstream, not forked. Vault-side shim landings are hand-driven by the owner; package-side
work is afk-able.

### Track E — Judgment the harness can't cover (human-validated)

Golden-set curation (owner-only, by definition), the bake-off's model pick, public API
naming, packaging/release, documentation voice.

## Principles every proposal must respect

- **The golden set is the spec for quality.** Never edit golden data to pass; if a query
  looks wrong, flag it. There is no parity oracle to fall back to.
- **Teeth stay in.** The gating suite must fail when defanged; CI enforces it. Never weaken
  a `gating` test.
- **Implement within the seeded interfaces** (see CLAUDE.md; the MCP face is decided).
- **Fail closed.** Unknown context sees shared only; context is server-side; one opaque
  refusal message.
- **Dependency-light.** Runtime deps stay graphmark + fastembed + numpy + pyyaml; fastmcp
  only via the `mcp` extra. No ANN library, no sqlite-vec, no LLM calls in core.
- **TDD, tracer-bullet slices.** Single-purpose, independently testable; larger is
  `needs-decomposition`.

## Non-goals (decided — do not propose)

Generation until a concrete headless-answers consumer exists (then: citations are chunk-IDs
from the retriever, never model-asserted quotes; Ollama only via `ragmark[generate]`).
Cloud/API embeddings. Write surfaces over MCP. Interactive UI / Obsidian plugin.
Entity-extraction GraphRAG. Embeddings inside graphmark (reaffirmed both ways, 2026-08-02).
