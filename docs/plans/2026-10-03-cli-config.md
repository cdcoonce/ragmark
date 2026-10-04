# Explicit CLI configuration — issue #26

Date: 2026-10-03. Local implementation against `5737aa8`; not committed or published.
Specification: [ragmark #26](https://github.com/cdcoonce/ragmark/issues/26).

## Behavior and scope

The CLI previously always called `RagmarkConfig.for_vault`, leaving the existing
`from_toml` loader unused. `ragmark --config PATH <verb>` now loads that explicit
configuration before constructing a store or embedder. The same loaded configuration
reaches `serve(config)` for `ragmark --config PATH mcp`.

The selected behavior is intentionally bounded:

- Global options precede the verb, as with the existing parser. Documentation fixes
  the previous `mcp --vault` example to `--vault PATH mcp`.
- Explicit `--config` and `--vault` are mutually exclusive; argparse exits 2 if both
  are present, regardless of order.
- Explicit configuration bypasses `RAGMARK_VAULT`. Without it, the existing `--vault`,
  environment fallback, defaults, and no-vault error contract remain unchanged.
- There is no autodiscovery, new environment variable, CLI context override, or change
  to the TOML schema. File-relative paths retain `from_toml`'s existing semantics.
- File, TOML, and shape exceptions raised by the existing loader become usage errors
  (exit 2) before store/embedder construction. This boundary surrounds only the load;
  engine errors are not reclassified. It does not add schema validation for values
  the existing loader accepts.

`config.py`, `gate.py`, core engine behavior, MCP tool names/arguments, dependencies,
version, and the reference configuration contents are unchanged. The golden CLI
shape assertion admits the new global `config` field; its golden-only options remain
pinned unchanged.

## Test evidence

TDD sequence:

| Test | Observed red before correction | Green behavior |
| --- | --- | --- |
| Config selection from another working directory with a conflicting environment root | Parser rejected unsupported `--config` | Reads the explicitly configured vault |
| Both explicit selectors, in either order | 2 failures because parsing succeeded | Usage error in both orders |
| Missing file, invalid TOML, missing root, wrong root type, wrong scopes container | 5 uncaught loader exceptions | Usage errors before poison store/embedder constructors can run |

Additional fixture coverage exercises actual search/index, read, and recent paths
with a stub embedder and temporary files. It verifies static exclusions, custom
context-directory names, asymmetric visibility for work/personal/unknown contexts,
and the custom index directory. MCP launcher forwarding, default behavior without
configuration, and the checked-in reference file are also covered.

The sdist already shipped tests but omitted `configs/the-vault.toml`. An actual cached
Hatchling build first failed a manifest assertion for the missing reference while
including the new test. Adding that one file to the sdist include list made the
assertion pass; the reference-file test then passed from the unpacked archive.
Cached Hatchling 1.32.4 and its cached dependencies were read directly; no installation
or network fetch was used. Temporary build artifacts were removed after validation.

Validation used the existing development environment and this worktree's source:

```sh
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider -m 'not model'
RUFF_NO_CACHE=true ruff check .
RUFF_NO_CACHE=true ruff format --check .
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' python scripts/teeth_check.py
git diff --check
```

Results: **259 passed, 6 model tests deselected, 1 existing xfail**; Ruff and format
checks passed. Gating teeth passed: **19 armed passes; 16 failures and 3 existing
passes when defanged**. All five newly marked negative gating cases failed when
defanged. The archive reference test separately passed (**1 passed, 19 deselected**).

No models or golden queries ran, and no live corpus, installed plugin/cache,
registration, or security settings were changed. This is local source readiness;
integration/cutover work in #94, #95, and #173 and the separate neighbor-scope fix
remain separate. The complete publish gate still includes the excluded model tests
and human review.
