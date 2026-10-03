# Reconcile approved retrieval changes with current dev

Base: `5e85b367c3cabba711326150a4f67f6a6c5688c8` (current dev at assembly).
The previously reviewed 30-file change set from `0261a085` applied cleanly.
Preserve upstream PRs #192/#193: fenced-code chunk handling, stronger gaps
tests, clean missing-index CLI errors, and #164's store vector cache. No model,
golden-query, public CLI or MCP contract changes belong to this reconciliation.

Issue [#194](https://github.com/cdcoonce/ragmark/issues/194) reproduces APFS
alternate-spelling aliases that bypass context or directory exclusions. Four
new cases failed on the bare current base, then passed with the reviewed exact
filesystem spelling boundary. The boundary refuses aliases opaquely; it does
not rewrite the configured literal path policy. Added controls cover canonical
shared/in-context reads and physically uppercase directories with explicit
literal ownership/exclusion configuration. Case-insensitive alias cases skip
only when the filesystem cannot reproduce them. The context cases are marked
`gating` and assert the canonical private path is denied as well.

The upstream vector cache revealed one necessary status adjustment. A fixture
warmed a store's cache, wrote same-size NaN vectors, then restored the old mtime:
status incorrectly reported ready. The private helper now opens a fresh public
store reader for vectors, so status checks the current artifact without changing
the supplied store cache or redesigning #164. Its regression now reports corrupt.

Validation uses the cached Python environment and temporary fixture corpora only:
Ruff check/format, the full nonmodel suite, and the armed/defanged gating check.
No live vault, index, embedding model, cache installation or golden data is used.
Commit, exact-source packaging, installation and runtime acceptance remain with
the supervising task after this source is frozen.

Final local results: 525 passed, 6 model tests deselected, 1 existing upstream
xfail; Ruff check and format-check pass (96 Python files); `git diff --check`
passes. Teeth: 34 pass armed, 31 fail/3 pass defanged. The original reviewed
source still matches all 30 recorded hashes; upstream chunk/fence/store source
and their dedicated tests remain byte-for-byte identical to the new base.
