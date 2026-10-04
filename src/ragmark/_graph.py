"""Internal graph structure shared by neighbors and gaps, with corpus scope first.

The owner-approved corpus policy (ragmark#94) applies before names and aliases
are catalogued. Machine-context visibility remains each surface's gate decision.
Graphmark retains name normalization, alias resolution and edge extraction.
"""

from __future__ import annotations

import os
from pathlib import Path

import graphmark

from ragmark import gate
from ragmark.config import RagmarkConfig


def has_corpus_scope(config: RagmarkConfig) -> bool:
    """Whether the optional owner policy needs pre-catalog note filtering."""
    return bool(config.scoped_folders or config.excluded_filenames or config.excluded_path_prefixes)


def build_graph(config: RagmarkConfig) -> graphmark.VaultGraph:
    """Build structure once, excluding configured non-content before resolution."""
    return (
        _scoped_graph(config)
        if has_corpus_scope(config)
        else graphmark.build(_graph_config(config))
    )


def _graph_config(config: RagmarkConfig) -> graphmark.VaultConfig:
    """Apply static note exclusions before graphmark resolves names and aliases.

    Its exclusions are exact names, so discover the dot names that ragmark's
    index walker and gate already refuse. Context filtering stays in the surface.
    """
    excluded = set(config.excluded_dirs)
    hidden_files: set[str] = set()
    for _dirpath, dirnames, filenames in os.walk(config.vault_root):
        excluded.update(name for name in dirnames if name.startswith("."))
        dirnames[:] = [name for name in dirnames if name not in excluded]
        hidden_files.update(
            name for name in filenames if name.startswith(".") and name.lower().endswith(".md")
        )
    graph_config = graphmark.VaultConfig(root=config.vault_root, excluded_dirs=sorted(excluded))
    graph_config.rules_files.extend(sorted(hidden_files))
    return graph_config


def _scoped_graph(config: RagmarkConfig) -> graphmark.VaultGraph:
    """Build structure from owner-approved notes using public graphmark APIs.

    graphmark 0.9's transient_prefixes only affects orphan metrics, not its
    catalog. Filter before parsing and resolution here; do not fork its name
    normalization or alias policy. This supplies edges and degree facts for
    ragmark's surfaces, not graphmark's broader diagnostic/reporting surface.
    """
    root = config.vault_root.resolve()
    paths: set[Path] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name
            for name in dirnames
            if not name.startswith(".") and name not in config.excluded_dirs
        ]
        for name in filenames:
            candidate = Path(dirpath) / name
            if not gate.is_indexable_note(candidate, config):
                continue
            resolved = candidate.resolve()
            if (
                resolved.is_relative_to(root)
                and resolved.is_file()
                and gate._has_exact_spelling(root, resolved.relative_to(root))
                and gate.is_indexable_note(resolved, config)
            ):
                paths.add(resolved)
    docs = [graphmark.parse_document(path, root) for path in sorted(paths)]
    nodes = {doc.rel_path: doc for doc in docs}
    catalog = graphmark.build_catalog(docs)
    graph = graphmark.VaultGraph(
        nodes=nodes,
        out_links={path: set() for path in nodes},
        back_links={path: set() for path in nodes},
        catalog=catalog,
        aliases=graphmark.build_aliases(docs, catalog),
    )
    extractor = graphmark.WikilinkExtractor()
    for doc in docs:
        for display in extractor.extract(doc.text):
            target = graphmark.diagnose(graph, display).target
            if target is not None and target != doc.rel_path:
                graph.out_links[doc.rel_path].add(target)
                graph.back_links[target].add(doc.rel_path)
    return graph
