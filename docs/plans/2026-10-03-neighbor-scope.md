# Neighbor graph static scope correction

Date: 2026-10-03. Local implementation against `5737aa8`; not committed or published.

## Problem and inherited scope

`vault_neighbors` passed only the vault root to `graphmark.build`. Graphmark therefore
catalogued hidden checkout copies and configured excluded directories before ragmark's
per-neighbor gate ran. Duplicate stems could make a live link ambiguous; a hidden alias
could take precedence over a visible alias. Filtering graph results afterward cannot
recover the missing edge.

The reproducer uses an ordinary `origin.md -> hop1.md` chain with a backlink to the
origin. Adding same-named notes under `.claude/worktrees/copy` or `notes/.drafts/copy`
changed the six-neighbor result to an empty result. Adding `.hidden.md` with the same
alias as a visible target removed that target from the result.

This change inherits only the static exclusions already used by `index._walk_notes`
and `gate.is_indexable_note`: dot directories, `config.excluded_dirs`, and dot-prefixed
Markdown filenames. It adds no vault-specific folder policy. Context visibility
continues to be checked by `gate.resolve_note` at neighbor discovery, before traversal.

## Implementation

`neighbors._graph_config` projects those exclusions into graphmark's public
`VaultConfig`. Graphmark accepts exact directory and rules-file names, so a pruned
`os.walk` discovers dot names before graph construction. Configured exclusions seed
the directory list; hidden Markdown names extend the default rules-file exclusions.
`vault_neighbors` then calls `graphmark.build` with this configuration.

This uses the existing graphmark interface and preserves its default rules-file
exclusions. BFS depth, ordering, ambiguity among visible notes, content budgeting,
and the public ragmark interfaces are unchanged. This is not a graph traversal
performance fix: graphmark still enumerates paths with its existing walker. Symlink
behavior, filename-case behavior, origin canonicalization, and whole-note budgeting
are outside this change.

## Test evidence

Each behavioral correction followed a failing test before its implementation:

| Reproducer | Observed red | Correction |
| --- | --- | --- |
| Hidden root and nested checkout copies | 2 failures: empty neighborhood instead of six live neighbors | Exclude dot directories before catalogue construction |
| Copies under configured `snapshots` exclusion | 1 failure: empty neighborhood instead of six live neighbors | Preserve configured directory exclusions |
| Hidden Markdown file sharing a visible alias | 1 failure: outgoing visible target missing | Exclude dot Markdown filenames before alias resolution |

A control test confirms that two visible notes with the same stem remain ambiguous.
Existing context-discovery tests remain unchanged, including the test that a hidden
context note cannot be traversed to reveal a downstream note.

Validation used the existing development environment with this worktree's `src` on
`PYTHONPATH`; no dependency installation, model load, corpus indexing, or golden run:

```sh
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider -m 'not model'
RUFF_NO_CACHE=true ruff check .
RUFF_NO_CACHE=true ruff format --check .
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' python scripts/teeth_check.py
git diff --check
```

Results: **244 passed, 6 model tests deselected, 1 existing xfail**. Ruff and format
checks passed. Gating teeth check passed: **14 armed tests passed; defanging produced
11 failures and 3 passes**, as required by the detector. The model tests were excluded
under the explicit no-model authorization, so this is not a claim that the full
publish gate or the owner-held golden oracle ran.

## Follow-up specifications

- **ragmark #149:** the current gaps specification requires the literal positional
  call `graphmark.build(config.vault_root)` and a spy assertion forbidding keyword
  configuration. Reusing that call would recreate this scope defect. Before gaps is
  implemented, revise that specification to require correct static graph scope and
  permit a `VaultConfig`; review whether the adapter should then become shared. The
  gaps stub and seeded interfaces are untouched here. A fresh October 3 check found
  #149 already stamped BUILD (exempt) with CLEAN coverage
  (issue comment 5972386334); its earlier waiver/coverage hold is no longer current.
  The graph-construction contract conflict remains a separate follow-up.
- Existing integration work in **#94, #95, #26, and #173** remains separate. This
  change does not register ragmark, replace shims, alter live configuration, or prove
  installed consumers use the new code.
- Working-tree activity visibility (**#182**), origin canonicalization (**#150**),
  and budgeting (**#175**) are not addressed.

No source version bump is needed for this local uncommitted change; release versioning
remains with the repository's existing release process. No golden data, installed
plugin cache, live configuration, or source checkout outside this worktree was changed.
