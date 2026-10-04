# Literal absorption reference check (#173)

Build the standalone mechanical check requested by ragmark #173, against the
current upstream layout recorded in `docs/ROADMAP.md` Track D. The Vault and
Workshop roots must both be supplied explicitly; no local path, environment
discovery, registration, or installation is inferred.

Scan regular text files recursively in both roots, including hidden, ignored,
untracked and historical Markdown files. Only Git metadata and NUL-marked
binary files are outside this textual check. Symlinks and unreadable entries
make a scan incomplete and must not produce a pass.

The only allowed relative paths are the two named shim slots in each layout:

- Vault: `.claude/scripts/semantic_index.py`, `.claude/scripts/vault_mcp.py`.
- Workshop: `plugins/workbench/machinery/engine/semantic_index.py`,
  `plugins/workbench/machinery/engine/vault_mcp.py`.

This preserves recognition of historical vendored shim paths while requiring
the current Workshop engine root. The allowlist has no caller override or glob.
Matching is the literal case-sensitive substring `fastembed`; each offending
line is reported by file and line number without printing note contents.

TDD slices: clean fixture; stray references in both roots and historical/hidden
files; exact allowlist and near-miss names; missing/wrong roots; binary handling;
incomplete scans. Tests invoke the standalone script against temporary trees,
with no Git, models, embeddings, indexes, registrations, or source note writes.

A pass certifies only reference locations in the scanned trees. It does not
prove that an allowlisted file is already a thin shim, that old engines were
deleted, that retrieval quality passes, or that activation occurred. Historical
mentions are deliberately not silently exempted; they can keep this literal
criterion red pending an owner decision about a different exit criterion.

## Validation (2026-10-03)

Observed failing tests before implementing each behavior: the absent standalone
script; stray references; allowlisted references; invalid roots; metadata/binary
scope; symlinks; unreadable files/directories and a blocking FIFO; identical
roots. Each was made green before advancing. All fixtures live in temporary
directories; permission errors are injected for deterministic tests.

- Focused checker suite: 18 passed.
- Full non-model suite: 257 passed, 6 deselected, 1 xfailed.
- Ruff check and format check: passed (78 Python files).
- Existing context-gating teeth check: 14 armed tests passed; defanged gate
  produced 11 expected failures and 3 passes; checker exited 0.
- `git diff --check`: passed.

The new script is included in the source distribution because its tests and
README invoke it by path. No seeded core, CLI, MCP, configuration, gate, golden
queries, model weights, live indexes, installed caches, or registration changed.
This validates the checker implementation only; no actual absorption-complete
claim or source-tree pass is made. Traversal is not an atomic filesystem
snapshot; run it against stable checkouts.
