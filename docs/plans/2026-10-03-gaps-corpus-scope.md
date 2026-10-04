# Apply approved corpus scope to the merged gaps surface

Date: 2026-10-03. Integration base: `0261a085` (PR #186).

The owner-approved policy in
https://github.com/cdcoonce/ragmark/issues/94#issuecomment-5973972945
requires corpus exclusions before graph name and alias resolution. The newly
merged `gaps()` still built a graph from only the Vault root. Excluded duplicate
stems and aliases made existing links ambiguous, producing false suggestions.
The parent explicitly authorized extending the approved policy to this new path.

Move the existing neighbor graph/config builders into a shared private `_graph`
module. Both `gaps` and `neighbors` call its `build_graph(config)` once. Optional
owner scope selects the existing contained, canonical, exact-spelling note walk;
empty scope retains Graphmark's configured build path and inherited hidden-note
exclusions. Graphmark still supplies parsing, catalog/alias rules and resolution.
No alternate ranking or name-resolution policy is introduced.

The root-only construction assertion inherited from #149 conflicts with this
approved policy. Replace it with a control that both surfaces pass the complete
configuration to the shared builder exactly once. Keep the independent
`rank_pairs` implementation and banding, active-context checks, dismissal hashes,
narrow access-error handling and missing-index behavior unchanged. No seeded
public signature, model, golden data, installation or live state is changed.

TDD evidence: eight temporary-corpus regressions first produced a false gap after
an excluded duplicate was added, then passed after the shared adapter was wired.
They cover folder/filename/prefix policy and inherited excluded directories,
hidden directories and hidden Markdown names, using both stems and aliases.
The final assertions also verify excluded documents never reach parsing.

Validation uses stub similarity responses and temporary index-existence files;
no embeddings, live index, model or golden queries are needed. Existing upstream
gaps tests, neighbor/corpus tests and the full non-model suite remain required.

Focused validation: **97 passed** across `test_gaps.py`, `test_neighbors.py`,
`test_corpus_scope.py` and `test_contract.py`. Ruff check and format check pass
for the changed Python files; `git diff --check` passes. The parent runs the final
combined non-model and context-teeth gates after this slice is frozen.
