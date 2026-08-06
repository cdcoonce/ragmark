# CHANGELOG


## v0.1.0 (2026-08-02)

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
