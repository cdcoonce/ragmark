"""ragmark — local-first retrieval over markdown / [[wikilink]] vaults.

Hybrid (vector + lexical) chunk search, note-level similarity, wikilink-aware
context expansion, and a first-party MCP surface — embeddings run locally and
the package makes no network egress at query time.

Import from the canonical modules directly (one import path per symbol):

    from ragmark.config import RagmarkConfig
    from ragmark.search import search

Decision provenance lives in the-vault#136 (the blueprint map) and its
resolution tickets; the operating contract for autonomous work is CLAUDE.md.
"""
