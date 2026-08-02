# ragmark

Local-first retrieval over markdown / `[[wikilink]]` vaults — hybrid (vector + lexical)
chunk search, note-level similarity, wikilink-aware context expansion, and a first-party
[MCP](https://modelcontextprotocol.io) surface. Embeddings run locally (fastembed); the
package makes no network egress at query time. Sibling of
[graphmark](https://github.com/cdcoonce/graphmark), which it consumes for deterministic
graph reads.

**Status: seeded, pre-release.** The public interfaces, security gate, correctness harness,
and release machinery are in place; the engine behavior lands slice by slice against them.

## Surfaces (one core, two faces)

| MCP tool                                     | CLI                           |                                                                     |
| -------------------------------------------- | ----------------------------- | ------------------------------------------------------------------- |
| `vault_search(query, k)`                     | `ragmark search "query" -k 8` | hybrid chunk hits with `chunk_id` citation handles                  |
| `vault_read(path)`                           | `ragmark read path.md`        | bare note text                                                      |
| `vault_neighbors(path, depth, token_budget)` | `ragmark neighbors path`      | wikilink BFS; structure always complete, budget limits content only |
| `recent_activity(days, limit)`               | `ragmark recent`              | git-log-backed "what moved lately"                                  |
| —                                            | `ragmark index [--force]`     | index maintenance is CLI-only, deliberately                         |

Every surface routes through the same fail-closed machine-context gate; an unmarked vault
reveals shared notes only.

## MCP registration

```bash
claude mcp add --transport stdio vault -- ragmark mcp --vault ~/path/to/vault
```

The registration name `vault` keeps existing `mcp__vault__*` tool names stable. The vault
root always comes from `--vault` or `$RAGMARK_VAULT` — never inferred.

## Correctness story

No parity oracle — the package improves on its predecessor in the same motion as absorbing
it. Instead: a hand-curated, executor-untouchable **golden-query set** asserted as recall@k
with the embedding model pinned, plus permanent **safety invariants** — no silent embedding
truncation (the predecessor silently dropped 27.8% of corpus characters), chunk↔vector
conservation, and context-gating tests that CI re-runs with the filter defanged and
requires to FAIL (`scripts/teeth_check.py`). Quality is measured, leaks are impossible to
test around, and a green gate means something.

Decision provenance: [the-vault#136](https://github.com/cdcoonce/the-vault/issues/136)
(blueprint map) and [the-vault#145](https://github.com/cdcoonce/the-vault/issues/145)
(build epic).
