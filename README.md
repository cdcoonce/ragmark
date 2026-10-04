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

## Corpus scope

`RagmarkConfig` and its TOML loader accept three optional owner-corpus fields:

| Field | Meaning | Empty default |
| --- | --- | --- |
| `scoped_folders` | Allowed literal top-level folder names | All folders and root notes |
| `excluded_filenames` | Excluded literal basenames anywhere | No additional filename exclusions |
| `excluded_path_prefixes` | Excluded literal vault-relative POSIX prefixes | No additional prefix exclusions |

Values must be collections of strings. Absolute paths, traversal, backslashes,
and glob patterns are rejected. Prefix matching is literal `startswith`: use a
trailing `/` for a directory, such as `personal/tasks/`. The existing
`excluded_dirs` setting excludes directory basenames; hidden files and folders
remain excluded regardless of these settings. See `configs/the-vault.toml` for
the approved reference policy.

Corpus scope applies before embedding and graph name/alias resolution, as well
as at every retrieval boundary. Refresh removes previously indexed notes that
are now excluded. Stored similarity results are filtered even without a refresh.
Requests must use the filesystem's exact path spelling, including on
case-insensitive filesystems; alternate spellings cannot bypass literal scope
or machine-context restrictions. Both a symlink path and its target must pass.
Machine-context visibility remains a separate, unchanged restriction: unknown
contexts see shared notes only, and `school` remains shared.

With empty new fields, neighbors and gaps use Graphmark's build path with the
existing static exclusions applied before name resolution.
Explicit corpus scope uses Graphmark's public parsing and resolution APIs on
the filtered notes, because Graphmark 0.9's `transient_prefixes` filters orphan
metrics, not its graph catalog. The shared structural helper does not replace
Graphmark's diagnostic/reporting surface.

## MCP registration

```bash
claude mcp add --transport stdio vault -- ragmark --config ~/path/to/vault.toml mcp
```

The registration name `vault` keeps existing `mcp__vault__*` tool names stable. Use
`ragmark --vault ~/path/to/vault mcp` instead to serve with the default configuration.

## Configuration

Global options go **before** the verb:

```bash
ragmark --config path/to/vault.toml search "query"
ragmark --config path/to/vault.toml read brain/note.md
ragmark --vault path/to/vault recent
```

`--config` loads the explicit TOML file through `RagmarkConfig.from_toml`; see
[`configs/the-vault.toml`](configs/the-vault.toml) for the reference shape. It honors
`vault_root`, `index_dir`, `excluded_dirs`, `context_dirs`, and `visible_scopes` on every
verb, including MCP startup. Paths inside the file resolve relative to its directory.
The machine context still comes from the selected vault's `.vault-context` file.

Explicit `--config` and `--vault` are mutually exclusive. With `--config`,
`RAGMARK_VAULT` is ignored. Without `--config`, the root comes from `--vault`, then
`RAGMARK_VAULT`, with the existing default configuration. There is no configuration-file
autodiscovery. Configuration load errors exit with usage code 2 before a store or
embedder is constructed.

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

## Track D absorption reference check

Run the standalone, standard-library-only checker against both explicitly selected
source checkouts:

```bash
python scripts/check_absorption_exit.py \
  --vault-root /path/to/the-vault \
  --workshop-root /path/to/the-workshop
```

Both roots are mandatory, existing, distinct directories. The Workshop root must
contain `plugins/workbench/machinery/engine`, where the upstream machinery now lives.
The historical Vault shim paths remain recognized, but there is no Vault-only pass
mode, environment fallback, or inferred checkout path.

The check finds the case-sensitive literal substring `fastembed` in regular text
files, including hidden, ignored, untracked, and historical Markdown files. Only
entries named `.git` (Git metadata) and files containing NUL bytes (binary for this
check) are excluded. The fixed allowlist contains exactly these relative paths:

| Root | Allowed file |
| --- | --- |
| Vault | `.claude/scripts/semantic_index.py` |
| Vault | `.claude/scripts/vault_mcp.py` |
| Workshop | `plugins/workbench/machinery/engine/semantic_index.py` |
| Workshop | `plugins/workbench/machinery/engine/vault_mcp.py` |

No basename patterns, archive exemptions, or caller overrides broaden that list.
Offenders are printed as `file:line`, without note contents. Exit `0` means no
references outside the allowlist; exit `1` means offending references; exit `2`
means invalid inputs or an incomplete scan (unreadable entries, symlinks, or
nonregular files). Findings still print when an incomplete scan also finds them.
Use stable checkouts: this read-only traversal is not an atomic snapshot.

This is the literal reference-location check from
[#173](https://github.com/cdcoonce/ragmark/issues/173), not a certification that an
allowlisted file is a thin shim, the old engine was deleted, retrieval quality
passes, or cutover has been activated. Historical mentions intentionally keep the
criterion red until removed or the owner explicitly changes the criterion. No
index, model, registration, installation, or source mutation occurs.
