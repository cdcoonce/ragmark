"""Wikilink neighborhood walks — graphmark-backed BFS (the-vault#142).

Fixture vault (`tests/fixtures/neighbors/vault/`): origin -> hop1 -> hop2 ->
hop3 -> hop4 (4 hops, one past MAX_DEPTH), backlinker -> origin (a back-link
-only neighbor of origin), and hop1 -> personal/secret -> downstream (a
personal/ note reachable by wikilink from a shared note, itself linking onward
to a shared note that is reachable only THROUGH it).
"""

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from ragmark.config import CONTEXT_FILE, RagmarkConfig
from ragmark.neighbors import vault_neighbors

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def make_vault(tmp_path: Path):
    def _make(context: str | None) -> RagmarkConfig:
        vault_root = tmp_path / f"vault-{context or 'unmarked'}"
        shutil.copytree(FIXTURES / "neighbors" / "vault", vault_root)
        if context is not None:
            (vault_root / CONTEXT_FILE).write_text(context + "\n", encoding="utf-8")
        return RagmarkConfig.for_vault(vault_root)

    return _make


def test_out_link_and_back_link_only_neighbors_both_appear(make_vault) -> None:
    config = make_vault("personal")
    result = vault_neighbors("origin.md", depth=3, config=config)
    by_path = {n.note_path: n for n in result.neighbors}

    assert by_path["hop1.md"].direction == "out"
    assert by_path["backlinker.md"].direction == "back"


@pytest.mark.parametrize("hidden_dir", [".claude/worktrees/copy", "notes/.drafts/copy"])
def test_hidden_copies_do_not_change_visible_neighbors(make_vault, hidden_dir: str) -> None:
    config = make_vault("personal")
    expected = vault_neighbors("origin.md", depth=3, config=config)
    hidden = config.vault_root / hidden_dir
    hidden.mkdir(parents=True)
    for name in ("origin.md", "hop1.md"):
        (hidden / name).write_text("Hidden copy.\n", encoding="utf-8")

    actual = vault_neighbors("origin.md", depth=3, config=config)

    assert actual == expected


def test_configured_excluded_copies_do_not_change_visible_neighbors(make_vault) -> None:
    config = replace(make_vault("personal"), excluded_dirs=frozenset({"snapshots"}))
    expected = vault_neighbors("origin.md", depth=3, config=config)
    excluded = config.vault_root / "notes" / "snapshots" / "copy"
    excluded.mkdir(parents=True)
    for name in ("origin.md", "hop1.md"):
        (excluded / name).write_text("Excluded copy.\n", encoding="utf-8")

    actual = vault_neighbors("origin.md", depth=3, config=config)

    assert actual == expected


def test_hidden_markdown_alias_does_not_steal_visible_link(make_vault) -> None:
    config = make_vault("personal")
    (config.vault_root / "origin.md").write_text("[[Friendly]]\n", encoding="utf-8")
    (config.vault_root / "live.md").write_text(
        "---\naliases: [Friendly]\n---\nVisible target.\n", encoding="utf-8"
    )
    expected = vault_neighbors("origin.md", config=config)
    assert "live.md" in {n.note_path for n in expected.neighbors}
    (config.vault_root / ".hidden.md").write_text(
        "---\naliases: [Friendly]\n---\nHidden alias.\n", encoding="utf-8"
    )

    actual = vault_neighbors("origin.md", config=config)

    assert actual == expected


def test_visible_duplicate_stays_ambiguous(make_vault) -> None:
    config = make_vault("personal")
    duplicate = config.vault_root / "notes" / "hop1.md"
    duplicate.parent.mkdir()
    duplicate.write_text("Another visible note.\n", encoding="utf-8")

    result = vault_neighbors("origin.md", depth=3, config=config)

    assert [n.note_path for n in result.neighbors] == ["backlinker.md"]


def test_depth_99_matches_depth_3_and_caps_at_max_depth(make_vault) -> None:
    config = make_vault("personal")
    capped = vault_neighbors("origin.md", depth=3, config=config)
    uncapped = vault_neighbors("origin.md", depth=99, config=config)

    assert uncapped.neighbors == capped.neighbors
    assert all(n.depth <= 3 for n in uncapped.neighbors)
    assert "hop4.md" not in {n.note_path for n in uncapped.neighbors}


def test_zero_budget_keeps_full_neighbor_set_and_order(make_vault) -> None:
    config = make_vault("personal")
    default = vault_neighbors("origin.md", depth=3, config=config)
    starved = vault_neighbors("origin.md", depth=3, token_budget=0, config=config)

    assert [n.note_path for n in starved.neighbors] == [n.note_path for n in default.neighbors]
    assert len(starved.neighbors) == len(default.neighbors)
    assert all(not n.included and n.content is None for n in starved.neighbors)


def test_neighborhood_shape(make_vault) -> None:
    config = make_vault("personal")
    result = vault_neighbors("origin.md", depth=3, config=config)

    assert result.origin == "origin.md"
    assert result.context == "personal"
    paths = [n.note_path for n in result.neighbors]
    assert paths == [
        "hop1.md",
        "backlinker.md",
        "hop2.md",
        "personal/secret.md",
        "downstream.md",
        "hop3.md",
    ]


@pytest.mark.gating
def test_work_context_hides_personal_neighbor(make_vault) -> None:
    work_result = vault_neighbors("origin.md", depth=3, config=make_vault("work"))
    assert "personal/secret.md" not in {n.note_path for n in work_result.neighbors}

    personal_result = vault_neighbors("origin.md", depth=3, config=make_vault("personal"))
    assert "personal/secret.md" in {n.note_path for n in personal_result.neighbors}


@pytest.mark.gating
def test_work_context_never_names_a_hidden_note_as_via(make_vault) -> None:
    """The gate is applied at discovery, so a hidden note is not walked THROUGH:
    it can neither be named as another neighbor's `via` nor hand out the notes
    beyond it. `downstream.md` is reachable from origin only via the personal
    note, so a work-context walk must not reach it either."""
    work_result = vault_neighbors("origin.md", depth=3, config=make_vault("work"))

    assert all("personal/secret.md" not in (n.note_path, n.via) for n in work_result.neighbors)
    assert "downstream.md" not in {n.note_path for n in work_result.neighbors}

    personal_result = vault_neighbors("origin.md", depth=3, config=make_vault("personal"))
    beyond = {n.note_path: n for n in personal_result.neighbors}["downstream.md"]
    assert beyond.via == "personal/secret.md"
