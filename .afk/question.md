# Issue #124 blocked: base assumption violated

The issue states: "Build against a base where #120 has not landed... If
`GoldenReport` already carries `provenance` when you start, stop and say so
in your summary — that field needs reconstructing, not ignoring, and this
spec does not cover it."

At `src/ragmark/golden.py:89-95`, `GoldenReport` already has:

```python
@dataclass(frozen=True, slots=True)
class GoldenReport:
    rows: tuple[GoldenRow, ...]
    mean_recall: float
    provenance: GoldenProvenance | None = None
```

`git log` confirms #120 (commit `928e8a3`, merged at `0337a2c`) already
landed this field on `afk/staging`, which this worktree's branch history
includes.

Per the issue's own explicit instruction, I am stopping rather than
implementing `report_from_dict` against the assumed pre-#120 shape:

- Ignoring `provenance` (treating it as an unrecognized top-level key) would
  be wrong — the issue says it needs *reconstructing*, not ignoring, and a
  round-trip test would fail because the reconstructed report would have
  `provenance=None` even when the source had a real `GoldenProvenance`.
- Reconstructing it requires deciding: what forward/backward-compat rules
  apply to `GoldenProvenance`'s own fields (some annotated `str | None` /
  `bool | None` with no dataclass default — are those "required" per the
  issue's backward-compat rule, i.e. absence raises `ValueError`, even
  though the field's value may legitimately be `None`?), and how a
  `provenance: null` vs. an absent `provenance` key in the JSON should be
  distinguished (since `GoldenReport.provenance` does have a dataclass
  default of `None`, unlike every other field in scope).

None of this is specified in issue #124's acceptance criteria. Rather than
guess at a nested-provenance reconstruction contract, I'm parking this slice
for human triage: either (a) issue #124 needs to be re-scoped/updated now
that #120 has landed, to specify `GoldenProvenance` round-trip behavior, or
(b) a human confirms `provenance` should in fact be ignored (contradicting
the issue's own stop condition) so I can proceed on that basis.

No code changes made.
