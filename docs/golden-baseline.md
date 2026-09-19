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
- `afk#1105` → **0.00** under both. A bare identifier query, which is precisely
  what the lexical leg was built for — worth its own investigation.
- `autonomous agents that fix bugs by themselves overnight` → 0.33 under RRF,
  0.00 under score fusion. The only query score fusion made worse.
- `how should agents share memory across repositories` → 0.33 under RRF.

## Reproducing

The index is built to a scratch dir on purpose: `<vault>/.ragmark` is untracked
but NOT gitignored in the-vault, and that vault auto-commits.

```
ragmark golden --vault /path/to/the-vault \
  --file /path/to/the-vault/.claude/ragmark/golden.toml \
  --fusion rrf     # or: score
```
