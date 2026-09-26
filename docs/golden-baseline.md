# Golden oracle — first recorded run

The golden-query set has been the stated quality oracle since the seed, and until
this run it had never been executed to a recorded number. No numeric recall result
existed anywhere in this repo's docs, CI, transcripts, or commit history, and CI
still does not invoke `ragmark golden` (the gate is ruff + pytest + teeth-check).

This file records the first baseline and the RRF-vs-score-fusion comparison that
produced it.

## Setup

| | |
|---|---|
| date | 2026-09-19 |
| oracle | `the-vault/.claude/ragmark/golden.toml`, 30 queries, 43 expected paths |
| metric | `golden.evaluate` mean recall@k, note-level set recall after chunk→note dedup, k=8 chunks |
| corpus | the-vault @ 955 notes → 12,971 chunks |
| model | `BAAI/bge-small-en-v1.5`, dim 384, fastembed 0.8.0 |
| machine context | `personal` (sees `personal` + `work`; every expected path is in scope) |
| config | package defaults via `RagmarkConfig.for_vault` — note the CLI never loads `configs/the-vault.toml`, so `excluded_dirs` is empty and `templates/` IS indexed |

## Result

| arm | mean recall@k |
|---|---|
| **RRF** (shipped default) | **0.7778** |
| **CombSUM score fusion** | **0.8222** |
| delta | +0.0444 (+4.4pp) |

Per query: 3 better under score fusion, 1 worse, 26 unchanged. Perfect recall on
21/30 (RRF) vs 23/30 (score). Zero recall on 4/30 under both.

```
SCORE better:  0.00 -> 1.00  asset management reporting tool snowflake
               0.33 -> 0.67  how should agents share memory across repositories
               0.67 -> 1.00  degree program classes courses university school enrollment
SCORE worse:   0.33 -> 0.00  autonomous agents that fix bugs by themselves overnight
```

## Why this does NOT justify changing the default

The delta rests on **four discordant queries, 3–1**. A two-sided exact sign test
gives **p = 0.625** — indistinguishable from a coin flip. The oracle has 30
queries and 20 of them have a single expected path, so per-query recall is
mostly binary and one query flipping moves the mean by 3.3pp. The minimum
detectable effect is larger than the effect observed.

Separately, recall@k is a **set** metric: it is insensitive to ordering inside
the top-k. Score fusion's main claimed benefit is better ordering, which this
oracle cannot see at all. So this run is weak evidence in both directions.

**The shipped default therefore stays `Fusion.RRF`.** Score fusion is available
opt-in via `--fusion score`. Flipping the default would need a larger golden set,
or a rank-sensitive metric (MRR/nDCG), or an explicit human decision — "hybrid
rank fusion" is decided behavior (CLAUDE.md, the-vault#140 d4).

Cost is not a differentiator: both arms ran in ~22s over 30 queries on a warm index.

## Measurement hygiene

Design was A-B-A — RRF, score, RRF in one process — so corpus drift is measured
rather than assumed. The first attempt tripped its own stability check: the vault
gained 17 chunks mid-run and the auto-refresh re-embedded inside arm B (which is
why arm B appeared to take 986s; that was the re-index, not fusion). The run was
repeated on a settled index and reproduced exactly: 0.7778 / 0.8222 / 0.7778,
12,971 chunks before and after.

## The oracle's ceiling is NOT 1.0 — four expect-paths are stale

Four of the 43 expected paths no longer exist. All four are pure renames
(`git log --diff-filter=R` shows R100, content identical) that happened after the
set was curated on 2026-08-02. Retrieval surfaces the note correctly; the oracle
scores it a miss because the path in `expect` is the old one.

| `expect` (stale) | actual path today |
|---|---|
| `work/active/2026-07-27 REC Dashboard SQL Injection Fix.md` | `work/active/rec/2026-07-27 REC Dashboard SQL Injection Fix.md` |
| `work/active/IQ Tracker Architecture.md` | `work/active/iq-tracker/IQ Tracker Architecture.md` |
| `work/active/EGM-Mart-Validation-One-Pager.md` | `work/archive/2026/egm/EGM-Mart-Validation-One-Pager.md` |
| `work/active/EGM-Mart-Validation-Full-Report.md` | `work/archive/2026/egm/EGM-Mart-Validation-Full-Report.md` |

Achievable ceiling is therefore **27.5/30 = 0.9167**, and the baselines read
84.9% (RRF) and 89.7% (score) of what is reachable.

The golden file is hand-curated and executor-untouchable, so this was NOT fixed
here — it needs Charles to repoint those four paths. Until then the absolute
number understates retrieval quality by up to 11.7pp.

## Real retrieval defects this run surfaced

Misses under the default that are NOT the stale-path artifact — these are
candidate reproducing queries in the oracle's own defect-ratchet sense:

- `asset management reporting tool snowflake` → **0.00** under RRF. The note
  exists at `work/active/amrt/asset-management-reporting-tool.md`. Transcript
  provenance (a real query Charles ran). Score fusion recovers it to 1.00.
- `afk#1105` → **0.00** under both. Investigated: **not a retrieval defect.** The
  expect note has never contained that literal string (`git log -S` confirms); it
  cites the issue as a URL and as `#1105`. The entry was unsatisfiable, so no
  fusion mode could ever score it. Corrected in the golden set to `#1105`, which
  retrieves the note at rank 1. Its old provenance comment was factually wrong.
- `autonomous agents that fix bugs by themselves overnight` → 0.33 under RRF,
  0.00 under score fusion. The only query score fusion made worse.
- `how should agents share memory across repositories` → 0.33 under RRF.

## Reproducing

**Run against the live vault.** An earlier draft of this section said the index had
to go to a scratch dir because `<vault>/.ragmark` is untracked but not gitignored in
a vault that auto-commits. That was already false when it was written: the-vault
added `.ragmark/` to `.gitignore` in `57f74e83` at 12:11:23, thirteen minutes before
this file was first committed. It is also unactionable — there is no `--index-path`
flag, and the CLI never calls `RagmarkConfig.from_toml`, so `index_dir` is always
`<vault>/.ragmark`.

This matters for cost. `index.refresh()` is mtime-gated and incremental, so the full
build over ~13k chunks is paid **once, ever**, and each arm costs **~22s** after.
Do not delete `<vault>/.ragmark` between runs; building into a throwaway directory
pays the full build every time for no benefit.

```
ragmark golden --vault /path/to/the-vault \
  --file /path/to/the-vault/.claude/ragmark/golden.toml \
  --fusion rrf     # or: score
```

### What those two commands do NOT reproduce

They reproduce the **arms**, not the **method**. The A-B-A ordering, the index-stability
check that caught the mid-run re-embed, the pairing of per-query rows across arms, and
the exact sign test were all done by a harness written to a session scratchpad, which is
gone. Nothing in this repo runs them today. #87 (a paired per-query regression diff
between two saved `GoldenReport` JSONs) is the missing in-repo half; until it lands,
re-deriving the comparison means re-deriving that machinery.

Two further caveats for anyone re-running this:

- **The numbers above are not pinned and are not re-derivable from today's inputs.**
  `GoldenReport` carries no provenance — no vault revision, no oracle revision, no model
  or `k`. The headline was measured against the golden file as of blob `559407e9` (30
  entries, the parent of the-vault's amendment commit `e4e94f90`); the file is now 31
  entries. The corpus was the-vault's working tree at 955 notes / 12,971 chunks on
  2026-09-19, and that vault moves continuously.
- **A re-baseline after the four stale paths are repointed will differ from 0.7778 for
  three reasons at once** — repointed paths, the added 31st entry, and corpus growth —
  with nothing in the output to attribute the delta between them.

## Follow-ups from this run

Investigating the `afk#1105` miss exposed a defect in the lexical leg's tokenizer:
`_TOKEN_RE` includes `.`, so a sentence-final word keeps its period and
`retryability.` never matches `retryability`. This strands **47,690 occurrences
across 7,794 distinct words — 3.8% of all corpus tokens** — and also welds whole
URLs into one token. Filed as #118, with the important negative result recorded
there: the obvious edge-stripping fix scores **worse** on this oracle
(0.7778 → 0.7611), because merging `work.` into `work` redistributes IDF. The set
simply could not see the benefit — no query hit a sentence-final term.

The golden set has since been amended (a reproducer for that defect, plus the
`#1105` correction), making it 31 entries with an RRF baseline of **0.7849**. The
A/B headline above is deliberately left on the **pre-amendment 30-entry set** it was
actually measured against — grading this PR with an oracle edited during this work
is exactly what the executor-untouchable rule exists to prevent. The four stale
expect-paths remain untouched and still need a human decision.
