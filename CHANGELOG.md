# CHANGELOG


## v0.2.0 (2026-10-04)

### Bug Fixes

- Enforce scoped vault retrieval contracts ([#210](https://github.com/cdcoonce/ragmark/pull/210),
  [`bde07f8`](https://github.com/cdcoonce/ragmark/commit/bde07f889e3147b344b859edf82d233898cdad12))

- **cli**: Serialize slots dataclasses with asdict
  ([#17](https://github.com/cdcoonce/ragmark/pull/17),
  [`7fbc6a9`](https://github.com/cdcoonce/ragmark/commit/7fbc6a94eb862e3661b6382dd5dff3fd4c0b5ab1))

* fix(cli): serialize slots dataclasses with asdict

Every engine result type is `@dataclass(frozen=True, slots=True)` and so has no instance `__dict__`.
  All four printing verbs read `__dict__` anyway, raising `AttributeError` straight past the error
  boundary as a raw traceback. `ragmark index` was broken on dev the moment its seam landed;
  `search`, `neighbors` and `recent` would have broken the same way as their slices land.

Route all four through one `_json_dump` helper built on `dataclasses.asdict`, which supports slots
  types and recurses into nested dataclasses, so a `Neighborhood`'s `neighbors` tuple renders as
  plain dicts. Tuples serialize as JSON arrays natively, so the old `default=` hooks are gone. A
  single helper means no verb can regress alone.

This shipped green because the CLI suite only exercised `_build_parser()` and never called `main()`.
  Add the first test that runs a verb end to end, plus a parametrized case covering all four result
  types.

Closes #16

* fix(cli): route the golden report through the same helper

The first pass missed `_run_golden`, which dumped its result with the same `default=lambda o:
  o.__dict__` hook. `GoldenReport` is `slots=True` too, and its `rows` hold
  `GoldenRow`/`GoldenQuery` — also slots — so `ragmark golden` would have kept raising
  `AttributeError` after the other four verbs were fixed.

Extend the parametrized case to `GoldenReport` and assert two levels of nesting resolve, which is
  what the one-helper design is for: the fifth call site could not have regressed silently once
  every verb shares it.

- **gaps**: Port dismiss/gaps parity to graphmark 0.10.0 and move the lock
  ([#206](https://github.com/cdcoonce/ragmark/pull/206),
  [`8c4fc29`](https://github.com/cdcoonce/ragmark/commit/8c4fc2998204acd6026cb880cf890e5e4e33fa86))

* chore(deps): lock graphmark 0.10.0 and raise floor to >=0.10

Intermediate commit: the gate is red here until the dismiss and gaps ports land.

* fix(dismiss): re-sync dismissal store with graphmark 0.10.0

Byte-for-byte with v0.10.0 below the provenance header: vault-root containment, ValueError on a
  missing note, load_dismissed read, atomic temp-and-rename write, and malformed or out-of-vault
  records skipped. Tests that pinned the 0.9.1 TypeError/KeyError behaviour now pin 0.10.0's.

* fix(gaps): match graphmark 0.10.0 cross-folder ranking

Root-level notes have no top-level folder, equal-score duplicate pairs are stored sorted, and gaps()
  skips malformed or out-of-vault dismissal records.

* test(gaps): give out-of-vault, directory and tie cases real teeth

- **parse**: Protect fenced blocks with the shared fence scanner
  ([#207](https://github.com/cdcoonce/ragmark/pull/207),
  [`b2bde38`](https://github.com/cdcoonce/ragmark/commit/b2bde3806069a00dec7778ad7d31f2d95a1b2222))

### Chores

- Ignore afk shadow-parity telemetry
  ([`460cf32`](https://github.com/cdcoonce/ragmark/commit/460cf3223add7593788b2d891b5f3291b5995418))

afk's shadow-parity harness (afk#1149/#1155) writes per-run node decision records to
  .afk/parity/*.jsonl. They accumulate toward a LOCAL N=10 agreement bar that
  shadow_parity.cutover_active reads off the local file, so they are machine-local build artifacts
  by construction and must never be committed.

afk-agent-system already ignores them in its own repo; the enrollment path never seeded the entry
  into enrolled repos, so ragmark had two untracked ledgers sitting one 'git add -A' away from
  landing.

- **afk**: Gate auto-promotion on a cold-read pass
  ([`8bc4d43`](https://github.com/cdcoonce/ragmark/commit/8bc4d439146b18fc33b46a5c70ac66dda97dade0))

auto_promote goes ON with `cold-read:pass` as a required label, so the policy can only pick issues a
  fresh reader has cleared. `cold-read:rewrite` and `cold-read:blocked` issues can never be picked
  up.

This repo is the argument for it: on 2026-08-08 #9, #10 and #11 were cold-read independently and all
  three returned blocking findings — the same one, each removing an xfail that the owed-behaviour
  contract guard asserts still exists while also demanding a green gate.

Measured before enabling: 1 issue qualifies (#9, already promoted and landed).

- **afk**: Ignore the per-machine daily cycle counter
  ([#119](https://github.com/cdcoonce/ragmark/pull/119),
  [`42e612f`](https://github.com/cdcoonce/ragmark/commit/42e612f1cd3aac9aeab44308eb3488d249a166ea))

- **afk**: Require a current cold-read stamp before auto-promotion
  ([`e4233fd`](https://github.com/cdcoonce/ragmark/commit/e4233fd8f82bdc93538e92857253bceedcc5c8f7))

### Continuous Integration

- **release**: Attach the wheel, sdist and SHA256SUMS to the GitHub release (#209)
  ([#211](https://github.com/cdcoonce/ragmark/pull/211),
  [`ef9ab36`](https://github.com/cdcoonce/ragmark/commit/ef9ab36a62fa944ba7f01aff94a32e4e22f4157b))

v0.1.0 shipped with no assets, so a consumer with no package index had nothing to pin by URL and
  hash. After a release is cut the workflow now builds the dist once, refuses a wheel that is not
  the released version, writes SHA256SUMS outside dist/ (PyPI rejects it there) and uploads wheel,
  sdist and checksums to the tagged release. This runs before the PyPI publish, so a failing publish
  (Trusted Publishing is still pending) cannot take the assets down. The same dist is then
  published.

### Documentation

- **golden**: Record the 2026-09-26 re-baseline on the reviewed oracle
  ([`24c5d14`](https://github.com/cdcoonce/ragmark/commit/24c5d148a7c3d2cabd8c1ca281dea881c54f1d0a))

### Features

- **gaps**: Wire gaps() over rank_pairs and the dismissal store with context gating
  ([#186](https://github.com/cdcoonce/ragmark/pull/186),
  [`0261a08`](https://github.com/cdcoonce/ragmark/commit/0261a08581a671b3645bc3ee346d0227bda90c54))

* feat(gaps): wire gaps() over rank_pairs and the dismissal store with context gating

Build the graph with graphmark.build, open the index (FileNotFoundError naming index_dir and
  `ragmark index` when ragmark.db or vectors.npy is missing), gate targets, similarity candidates
  and dismissal records through gate.filter_visible, skip targets the gate refuses, and rank with
  the caller's banding arguments. Retire the owed-gaps contract marker and the NotImplementedError
  test.

Closes #149

* test(gaps): tighten missing-index and error-propagation tests

Assert the full run-instruction in the missing-index message, make the must-not-run search stub
  raise so the check-before-search order is guarded directly, parametrize the non-gate error over
  four exception types, drop the seed_config helper left unused by test_owed_gaps' removal, and keep
  docstring item 3 inside the numbered list.

- **search**: Carry leg relevance magnitudes into fusion, with a measured score-fusion alternative
  ([#117](https://github.com/cdcoonce/ragmark/pull/117),
  [`3cdab90`](https://github.com/cdcoonce/ragmark/commit/3cdab90f790c831afe016f4e665a235314bb5de8))

* feat(search): carry leg relevance magnitudes into fusion

Both legs computed a real relevance number and discarded the magnitude: `_vector_leg` scored a
  cosine and returned bare chunk_ids, `_lexical_leg` did the same with its BM25 score. `_fuse`
  therefore had only rank position to work with, so position stood in for relevance because position
  was all it was given.

The legs now return `(chunk_id, score)` pairs, and fusion takes a `mode`:

- `Fusion.RRF` — unchanged reciprocal rank fusion, still the default and still the decided behavior.
  Magnitude is ignored deliberately: cosine and BM25 are incommensurable, and not reconciling them
  is RRF's whole point. - `Fusion.SCORE` — CombSUM, each leg min-max normalized over the fetched
  pool, summed equal-weighted.

A zero-width leg range normalizes to 1.0, not 0.0. A leg with one hit is exactly what an
  exact-identifier query produces, and mapping it to 0.0 would silently delete the only leg that can
  see `afk#1089`.

Tests are teeth-checked by re-injection: dropping either magnitude, fusing SCORE on rank, zeroing
  the degenerate range, and making the `fusion` argument inert each turn the predicted test red.

* feat(cli): select the leg-fusion mode on search and golden

The golden-query set is the only instrument that can compare the two fusion modes, and it is driven
  from the CLI, so the mode has to be reachable here. `--fusion {rrf,score}` defaults to rrf on both
  verbs.

The MCP face deliberately does not expose it: that face is a pinned contract
  (tests/test_mcp_face.py) and its behavior stays the default.

* docs: record the first golden-oracle baseline

The golden set has been the stated quality oracle since the seed and had never been run to a
  recorded number — nothing numeric existed in docs, CI, transcripts or history, and CI still does
  not invoke it.

Baseline over the-vault (955 notes, 12,971 chunks, bge-small-en-v1.5): mean recall@k 0.7778 under
  the shipped RRF default, 0.8222 under CombSUM score fusion.

The +4.4pp does NOT justify flipping the default: it rests on four discordant queries 3-1, an exact
  sign test gives p = 0.625, and recall@k is a set metric that cannot see the ordering score fusion
  is supposed to improve. RRF stays the default; score fusion is opt-in.

Also records two things the run exposed independently of fusion: four expect-paths are stale
  renames, so the achievable ceiling is 0.9167 rather than 1.0, and several genuine retrieval misses
  including an exact-identifier query scoring zero.

* docs(golden): record the afk#1105 diagnosis and the tokenizer defect (#118)

* docs(golden): correct the reproduction recipe and state what it cannot reproduce

The "Reproducing" section told the reader to build the index into a scratch dir because
  <vault>/.ragmark is "untracked but NOT gitignored" in an auto-committing vault. That was already
  false when this file was committed: the-vault added .ragmark/ to .gitignore in 57f74e83 at
  12:11:23, and this file landed at 12:24:52. It is also unactionable, since there is no
  --index-path flag and the CLI never calls RagmarkConfig.from_toml, so index_dir is always
  <vault>/.ragmark.

The cost consequence is the point. index.refresh() is mtime-gated and incremental, so against the
  live vault the full build is paid once and each arm costs ~22s after; the old advice pays the full
  build every run for no benefit, which is most of why this oracle went unrun for so long.

Also states plainly that the two commands reproduce the arms and not the method — the A-B-A
  ordering, the index-stability check, the per-query pairing and the sign test lived in a session
  scratchpad that is gone, and #87 is the missing in-repo half — and records the two pinning
  caveats: GoldenReport carries no provenance, the headline was measured against golden.toml at blob
  559407e9 (30 entries, now 31), and a re-baseline after repointing the stale paths will move for
  three reasons at once with nothing to attribute the delta.

Docs only; no behaviour change. Gate green: ruff, 131 passed / 3 xfailed, teeth-check OK.

- **search**: Hybrid RRF retrieval and the note-level similarity view
  ([#18](https://github.com/cdcoonce/ragmark/pull/18),
  [`936e580`](https://github.com/cdcoonce/ragmark/commit/936e5805b6ff254e6c165188ec11ed9af7a618f4))

Implement the two owed seams in `search.py`.

`search` runs the mtime refresh, clamps k to MAX_RESULTS before over-fetching so the candidate pool
  is bounded regardless of caller input, then fuses a brute-force cosine leg with a pure-Python BM25
  leg by reciprocal rank fusion (RRF_K=60, legs equal-weighted, ties broken by chunk_id so ordering
  is reproducible across platforms). The BM25 tokenizer deliberately keeps `trunk_branch` and
  `afk#1089` as single tokens — a `\w+` tokenizer splits them and silently defeats the leg's reason
  to exist. Candidates are context-filtered through `gate.filter_visible` only, since that is the
  symbol the defang hook patches; filtering inline would leave a gating test with no teeth. When
  gating leaves fewer than k the result is short, never refilled: a count that adapts to hidden
  material is an inference channel.

`similar_notes` gates its input first so a hidden source is indistinguishable from a missing one,
  pools chunk vectors by L2-normalized arithmetic mean, scores by cosine so results stay in [-1, 1]
  for the downstream banding, and excludes the query note from its own results.

`store.read_chunk_rows` is added (additions only; no schema or signature change) because no accessor
  returned chunk text.

Deletes the two owed xfails and repairs the two tests that break as a consequence: the CLI's
  not-implemented probe now injects a raising stub so it keeps testing the error boundary rather
  than which seam happens to be unimplemented, and the owed-marker guard is renamed for the three
  survivors.

Closes #8

### Testing

- **fences**: Assert the NBSP closer and balanced CRLF tilde cases
  ([#193](https://github.com/cdcoonce/ragmark/pull/193),
  [`5e85b36`](https://github.com/cdcoonce/ragmark/commit/5e85b367c3cabba711326150a4f67f6a6c5688c8))

Two literal values from #108's acceptance criteria were never asserted: a closer followed by U+00A0
  is content, and unterminated_fence_line returns None for a balanced CRLF tilde fence. Without them
  a closer regex of \s*$ and an LF-only rstrip both pass the suite. Also drop the chunk.py comments
  that still describe line-by-line fence tracking.

Follow-up to #108


## v0.1.0 (2026-08-02)

### Continuous Integration

- **afk**: Enroll ragmark in the autonomous executor
  ([`e225fcc`](https://github.com/cdcoonce/ragmark/commit/e225fcc449624443930464a898b8ab777227665b))

Authors .afk/config.toml with the gate from CLAUDE.md verbatim (ruff + format + pytest +
  teeth_check) and the allowed_tools grant list, without which the executor runs no Bash at all and
  every slice parks on an approval prompt instead of failing honestly.

Branch posture is the staging shape rather than graphmark's, because afk's source says graphmark's
  shape cannot work here. Slices fork from integration_target (executor.py:474), and a per-slice PR
  opens only when integration_target == "main", with that same value as its base (executor.py:394) —
  so no configuration opens a per-slice PR against dev. Left at the default, slices would fork off
  main and open PRs into main, and a merge to main in this repo runs release.yml and cuts a version.
  Instead slices land on afk/staging with no PR and one integration PR carries the batch into dev;
  promotion to main stays a human step.

Grants deliberately exclude network tools. The fastembed embedder in Track A will need an egress
  decision when that slice is built.

Refs: the-vault#145

### Features

- Hand-authored seed — interfaces, gate, correctness harness, release machinery
  ([`d04ff08`](https://github.com/cdcoonce/ragmark/commit/d04ff0891b1c6df837c6ecf6e68caaf60142d2f5))

The Phase 0 seed decided on the-vault#145 (blueprint map the-vault#136):

- Typed public interfaces for every module; behavior owed to build slices is marked by strict xfails
  in tests/test_contract.py. - gate.py IMPLEMENTED: fail-closed machine-context scoping and the
  resolve-then-contain access boundary (migrated from vault_mcp.py, with absolute-path inputs now
  refused outright). - Correctness harness: golden-query loader/evaluator/CLI gate, safety invariant
  pins, and the teeth-check (gating suite must fail when defanged — enforced in CI,
  scripts/teeth_check.py). - MCP face pinned by contract tests (names, args, annotations — the shape
  accepted live on the-vault#142's prototype). - Store infrastructure: SQLite schema, atomic
  temp+rename writes, model identity recorded and checked. - graphmark's packaging playbook:
  hatchling, semantic-release deploy-on-promotion, PyPI Trusted Publishing, 2 OS x 3 python gate.
