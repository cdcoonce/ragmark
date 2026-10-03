# Apply approved owner corpus scope before retrieval

Approved seeded-surface extension:
https://github.com/cdcoonce/ragmark/issues/94#issuecomment-5973972945

Add optional `scoped_folders`, `excluded_filenames`, and
`excluded_path_prefixes` to RagmarkConfig/TOML. Empty defaults preserve existing
consumer behavior. Validate collections and literal relative names/prefixes.
Apply corpus policy before embedding and graph name/alias resolution, and at
read/search/similarity/neighbors/recent boundaries. Existing machine-context
policy and opaque refusals remain unchanged.

The reference config mirrors the approved Vault policy. No live config,
registration, installed package, model call, index build, or golden oracle is
changed. Preserve the prerequisite hidden/excluded graph fix already in this
worktree. Tests use temporary corpora and stub embeddings; run the non-model
suite, formatting/lint, and context-gate teeth check before freezing changes.

## Implementation and evidence

- Config loading, validation, direct access, stored-result filtering, and
  pre-resolution stem/alias exclusions were developed with failing tests first.
- Refresh fixtures verify previously indexed exclusions are removed without
  re-embedding unchanged allowed notes. An empty-scope fixture reproduced
  leftover vectors; the empty index now clears that file.
- Index and scoped graph walks check both lexical and resolved contained paths
  before reading note content, deduplicating canonical paths. Tests reproduced
  and closed scope bypass through symlinks in both directions.
- Work and unknown contexts still fail closed across direct reads, search,
  similarity, neighbors and recent activity; school stays shared. Empty new
  fields retain Graphmark's original build path and root-note behavior.

Graphmark 0.9's `transient_prefixes` affects orphan metrics only. The bounded
integration decision is to assemble scoped neighbor structure with its public
`parse_document`, `build_catalog`, `build_aliases`, `diagnose`,
`WikilinkExtractor`, and `VaultGraph` APIs. Excluded content never enters that
catalog. This does not promise parity for Graphmark diagnostics outside the
existing neighbor contract or modify the separately planned gaps surface.

Final local validation:

- Full non-model suite after review corrections: **342 passed, 6 model tests
  deselected, 1 existing xfail**.
- Ruff check and format check: pass across the repository.
- Context teeth after review regressions: **25 armed tests pass; 22 fail when
  context gating is defanged**.
- `git diff --check`: pass.

All fixtures, stores and embeddings were temporary/stubbed. No live index,
golden data, installed package, hook registration, commit, push or model call.
Activation remains a separately reviewed package/source release and owner
configuration update; existing source-only Workshop adapters consume these
new fields but are not installed by this change.

Independent review found that resolving a cached personal path to a new shared
symlink target could lose the lexical context restriction. `resolve_note` now
requires both requested and canonical paths to be visible, reading the active
context once per decision. Nine new tests reproduced the failure and now pass:
direct reads with opaque errors, result filtering, stale-index similarity,
recent activity, and the default neighbor path, with allowed work aliases as
positive controls. These tests are included in the defanged context gate.

A second independent probe found that APFS accepts alternate case spellings
while `Path.resolve()` retains the request's casing. Literal filename, prefix,
and context checks could therefore be bypassed. Access now conservatively
requires actual filesystem spelling for both requested and canonical paths;
the index and scoped graph walks apply the canonical check before content is
read. Policy itself is not lowercased. Real-filesystem regressions cover
`AGENTS.md` versus `agents.md`, `tasks/` versus `TASKS/`, `personal/` versus
`PERSONAL/` and `Personal/`, and symlinks with alternate-case targets. Those
cases skip only when the filesystem does not resolve the alternate spelling.
Exact lowercase filenames, uppercase directories, and allowed symlinks remain
positive controls. No live files were used for these probes.
