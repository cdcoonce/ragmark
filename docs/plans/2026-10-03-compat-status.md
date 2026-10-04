# Private compatibility status inspection — #94

Prepare a read-only inspector for the eventual legacy status adapter. This does
not add a Ragmark CLI verb, MCP tool, public model shape or config/gate option.
Production wiring belongs to the separate compatibility adapter slice. The
corpus-scope contract was approved in
[#94](https://github.com/cdcoonce/ragmark/issues/94#issuecomment-5973972945).

`_compat_status.inspect_status(config, store, expected_identity)` returns a JSON
dictionary retaining the legacy root/index/model/count/readiness fields. Added,
changed and deleted note counts are explicit; their sum is `stale_notes`.
Readiness requires a coherent built index, matching expected model identity and
no stale paths. A built empty corpus can be ready without a vectors file.
Unavailable counts are null. Missing/unbuilt, corrupt, identity mismatch and
inspection unavailable remain distinct states.

No build timestamp or vault-root identity is recorded by this store:
`index_built_at` stays null and `root_provenance` is `not_recorded`. No filesystem
mtime is presented as a build time, and naming the requested root is not a claim
that the index was built there.

The inspector uses an immutable read-only SQLite connection and public store
read methods. It refuses journal/WAL/SHM sidecars and snapshots that change while
being read. It never calls writable connect, refresh, reindex or model methods.
Tests construct synthetic databases/vectors and snapshot bytes, modification
times and directory entries before/after inspection. No live index or model is
used. Boundary tests cover absent, stale, empty, corrupt, mismatched and changing
artifacts, and preserve current static policy without inventing owner scope.

The scan calls the public path-only `gate.is_indexable_note` so approved policy
extensions apply when the source slices are assembled. It reports maintenance
counts for that configured corpus; it returns no note paths, content or search
results. It conservatively refuses indexable symlink/non-regular notes and
unreadable walks. Journal/WAL/SHM files are checked before opening SQLite and
again after inspecting it. Device/inode/size/mtime/ctime checks catch ordinary
index replacements and edits, and a second corpus scan checks added, changed
and deleted paths while hashing. This is a checked observation, not a lock or
promise that a writer cannot start after the final check.

TDD evidence: the missing/healthy, staleness, unbuilt/corrupt and identity cases
were exercised first; 8 sidecar/index/config tests and then 5 corpus-race/access
tests failed before their guards were added. An NPZ file disguised as the
vectors array also failed before explicit rejection/closure was added. Independent
review reproduced a truncated ZIP header raising `BadZipFile`; its red regression
now verifies that this malformed artifact reports corruption too. FIFO artifacts
also reproduced a blocking open in isolated child processes; regular-file checks
now refuse them before SQLite/NumPy access. Ordinary OS read/permission errors
report unavailable/retry instead of suggesting corruption/rebuild. Five further
red regressions cover a real mode-000 database and SQLite's translated
`CANTOPEN`, `PERM`, and `IOERR` families (including extended codes); these now
report unavailable too, while malformed metadata stays corrupt. Reconciliation
with upstream #164 added a red regression for a warmed vector cache followed by
a same-size/same-mtime corrupt rewrite. Status now uses a fresh public store
reader for the vector artifact, preserving truthful inspection without changing
the caller's cache or the upstream store. All 49
fixture tests pass. Every call forbids writable store connect, refresh, reindex
and embedding methods; byte/mtime/directory snapshots stay unchanged except for
explicit concurrent-writer fixture actions. No model weights or live vault
index were accessed.
