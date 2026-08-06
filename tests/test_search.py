"""Hybrid search and the note-level similarity view.

Cacheless tier (the gate for this change): a deterministic stub `Embedder`
(mirroring `tests/test_index.py`'s RecordingEmbedder in shape) stands in for
fastembed, so every criterion below holds on a leg with NO warm model cache.

The stub hashes with `hashlib` rather than `hash()` so its vectors are stable
across processes, and it deliberately sees only ALPHABETIC runs: `trunk_branch`
and `afk#1089` are invisible to it as identifiers. That is the whole reason the
lexical leg exists (the-vault#140 d4), and it lets the exact-identifier test
prove its own teeth by deleting the lexical leg and re-running.

Ranking and cap corpora are built under `tmp_path`; the committed gating
fixture vault (5 notes) is only used for the assertions it is big enough for.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from ragmark import index, search
from ragmark.config import RagmarkConfig
from ragmark.embed import Embedder
from ragmark.model import ModelIdentity
from ragmark.store import IndexStore

DIM = 64
BASE_MTIME = 1_700_000_000_000_000_000

PERSONAL_NOTE = "personal/projects/side-project.md"
TARGET_NOTE = "ops/pipeline-notes.md"

# The stub's view of a text: alphabetic runs only, so `trunk_branch` reads as
# "trunk"+"branch" and `afk#1089` as "afk" — the identifier itself is gone.
_PROSE_TOKEN_RE = re.compile(r"[a-z]+")

TARGET_TEXT = """# Pipeline notes

The nightly job reads trunk_branch from the executor config, and the drift it
found is filed as afk#1089 for the next review pass.
"""

FILLER_TOPICS = [
    "kayaking",
    "sourdough",
    "telescopes",
    "cartography",
    "beekeeping",
    "woodworking",
    "birdsong",
    "glassblowing",
]


class StubEmbedder(Embedder):
    """Deterministic hashing bag-of-words stub — no fastembed, no cache."""

    def identity(self) -> ModelIdentity:
        return ModelIdentity(name="stub", dim=DIM, version="1")

    def embed(self, texts: Any) -> Any:
        matrix = np.zeros((len(list(texts)), DIM), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in _PROSE_TOKEN_RE.findall(text.lower()):
                digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
                matrix[row, int.from_bytes(digest, "big") % DIM] += 1.0
        return matrix

    def count_tokens(self, text: str) -> int:
        return max(1, len(text.split()))


# --- corpus helpers -----------------------------------------------------------


def make_config(tmp_path: Path) -> RagmarkConfig:
    vault = tmp_path / "vault"
    vault.mkdir()
    return RagmarkConfig.for_vault(vault, index_dir=tmp_path / "index")


def write_note(config: RagmarkConfig, rel: str, text: str, mtime_ns: int = BASE_MTIME) -> Path:
    path = config.vault_root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.utime(path, ns=(mtime_ns, mtime_ns))
    return path


def write_ranking_corpus(config: RagmarkConfig) -> None:
    """33 notes: one identifier-bearing target, 24 decoys that dominate the
    vector leg for the target's PROSE words, and 8 unrelated fillers."""
    write_note(config, TARGET_NOTE, TARGET_TEXT)
    for i in range(12):
        write_note(
            config,
            f"decoys/trunk-{i}.md",
            f"# Trunk branch drill {i}\n\nTrunk branch trunk branch trunk branch.\n",
        )
        write_note(
            config,
            f"decoys/afk-{i}.md",
            f"# Afk drill {i}\n\nAfk afk afk afk afk afk.\n",
        )
    for i, topic in enumerate(FILLER_TOPICS):
        write_note(
            config,
            f"notes/filler-{i}.md",
            f"# Notes on {topic}\n\nA short note about {topic} and nothing else.\n",
        )


# --- exact-identifier retrieval (the lexical leg's reason to exist) ------------


@pytest.mark.parametrize("identifier", ["trunk_branch", "afk#1089"])
def test_exact_identifier_query_returns_the_note_holding_it(
    tmp_path: Path, identifier: str
) -> None:
    config = make_config(tmp_path)
    write_ranking_corpus(config)
    store = IndexStore(config.index_dir)

    hits = search.search(identifier, 8, config=config, store=store, embedder=StubEmbedder())

    assert TARGET_NOTE in {hit.note_path for hit in hits}


@pytest.mark.parametrize("identifier", ["trunk_branch", "afk#1089"])
def test_exact_identifier_retrieval_dies_without_the_lexical_leg(
    tmp_path: Path, monkeypatch, identifier: str
) -> None:
    """Teeth for the test above: delete the lexical leg and it must go dark.

    The decoys share the target's prose words at far higher density, so the
    vector leg alone cannot surface the identifier-bearing note — exactly the
    whiff the-vault#140 d4 set out to fix.
    """
    config = make_config(tmp_path)
    write_ranking_corpus(config)
    store = IndexStore(config.index_dir)
    monkeypatch.setattr(search, "_lexical_leg", lambda *args, **kwargs: [])

    hits = search.search(identifier, 8, config=config, store=store, embedder=StubEmbedder())

    assert hits
    assert TARGET_NOTE not in {hit.note_path for hit in hits}


# --- the server-side cap ------------------------------------------------------


def test_k_above_the_cap_is_clamped_silently(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    write_ranking_corpus(config)
    store = IndexStore(config.index_dir)

    hits = search.search(
        "trunk branch afk drill note", 40, config=config, store=store, embedder=StubEmbedder()
    )

    assert store.chunk_count(store.connect()) >= 30
    assert len(hits) == search.MAX_RESULTS == 25


# --- determinism --------------------------------------------------------------


def test_repeated_search_over_one_index_is_byte_for_byte_ordered(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    write_ranking_corpus(config)
    store = IndexStore(config.index_dir)
    embedder = StubEmbedder()

    first = search.search("trunk branch drill", 10, config=config, store=store, embedder=embedder)
    second = search.search("trunk branch drill", 10, config=config, store=store, embedder=embedder)

    assert [hit.chunk_id for hit in first] == [hit.chunk_id for hit in second]
    assert [hit.score for hit in first] == [hit.score for hit in second]


# --- every indexed note retrievable (safety invariant) ------------------------


@pytest.mark.parametrize(
    ("title", "note_path"),
    [
        ("Daily log", "brain/daily-log.md"),
        ("Side project", PERSONAL_NOTE),
        ("Graph notes", "reference/graph-notes.md"),
        ("Course notes", "school/course-notes.md"),
        ("Platform choice", "work/decisions/platform-choice.md"),
    ],
)
def test_every_indexed_note_is_retrievable_by_its_own_title(
    make_vault, title: str, note_path: str
) -> None:
    config = make_vault("personal")
    store = IndexStore(config.index_dir)

    hits = search.search(title, 8, config=config, store=store, embedder=StubEmbedder())

    assert note_path in {hit.note_path for hit in hits}


# --- staleness (auto-refresh on the query path) -------------------------------


def test_search_reflects_an_edit_with_no_manual_reindex(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    write_note(config, "a.md", "# Alpha\n\nThe alpha note is about kayaking.\n")
    write_note(config, "b.md", "# Beta\n\nThe beta note is about gardening.\n")
    store = IndexStore(config.index_dir)
    embedder = StubEmbedder()

    before = search.search("spelunking", 8, config=config, store=store, embedder=embedder)
    assert all("spelunking" not in hit.snippet for hit in before)

    write_note(
        config,
        "a.md",
        "# Alpha\n\nThe alpha note is about spelunking.\n",
        BASE_MTIME + 10_000_000,
    )

    after = search.search("spelunking", 8, config=config, store=store, embedder=embedder)
    assert any(hit.note_path == "a.md" and "spelunking" in hit.snippet for hit in after)


# --- note-level similarity ----------------------------------------------------


def test_similar_notes_is_cosine_excludes_self_and_omits_chunkless_notes(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    write_note(config, "a.md", "# Alpha\n\nThe alpha note is about kayaking and rivers.\n")
    write_note(config, "b.md", "# Beta\n\nThe beta note is about kayaking and rapids.\n")
    write_note(config, "c.md", "# Gamma\n\nThe gamma note is about glassblowing.\n")
    write_note(config, "empty.md", "")
    store = IndexStore(config.index_dir)
    index.reindex(config, store, StubEmbedder())

    pairs = search.similar_notes("a.md", 8, config=config, store=store)

    paths = [path for path, _ in pairs]
    assert "a.md" not in paths
    assert "empty.md" not in paths
    assert paths[0] == "b.md"
    assert all(-1.0 <= score <= 1.0 for _, score in pairs)


def test_similar_notes_refuses_an_out_of_context_source(make_vault) -> None:
    from ragmark import gate

    config = make_vault("work")
    store = IndexStore(config.index_dir)
    index.reindex(config, store, StubEmbedder())

    with pytest.raises(gate.VaultAccessError):
        search.similar_notes(PERSONAL_NOTE, 8, config=config, store=store)


# --- the context gate (marked: must go red when defanged) ---------------------


@pytest.mark.gating
def test_work_context_search_never_surfaces_a_personal_chunk(make_vault) -> None:
    config = make_vault("work")
    store = IndexStore(config.index_dir)

    hits = search.search(
        "side project personal", 8, config=config, store=store, embedder=StubEmbedder()
    )

    assert hits
    assert all(hit.note_path != PERSONAL_NOTE for hit in hits)


@pytest.mark.gating
def test_work_context_similar_notes_never_surfaces_a_personal_note(make_vault) -> None:
    config = make_vault("work")
    store = IndexStore(config.index_dir)
    index.reindex(config, store, StubEmbedder())

    pairs = search.similar_notes("work/decisions/platform-choice.md", 8, config=config, store=store)

    assert pairs
    assert all(path != PERSONAL_NOTE for path, _ in pairs)
