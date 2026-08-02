"""The access boundary and the context gate.

Tests marked `gating` are the teeth-checked suite (the-vault#144, decision
3): `scripts/teeth_check.py` re-runs exactly these with `--defang-gate` and
requires them to FAIL — each one must depend on the filter actually
filtering. Containment tests are unmarked: they hold with or without the
context filter and belong to the path boundary, not the gate.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ragmark import gate

ALL_NOTES = [
    "brain/daily-log.md",
    "personal/projects/side-project.md",
    "reference/graph-notes.md",
    "school/course-notes.md",
    "work/decisions/platform-choice.md",
]
SHARED_NOTES = ["brain/daily-log.md", "reference/graph-notes.md", "school/course-notes.md"]


# --- containment (unmarked: true regardless of context) ---------------------


def test_traversal_is_refused(make_vault) -> None:
    config = make_vault("personal")
    (config.vault_root.parent / "outside.md").write_text("secret", encoding="utf-8")
    with pytest.raises(gate.VaultAccessError):
        gate.resolve_note("../outside.md", config)


def test_absolute_path_is_refused(make_vault) -> None:
    config = make_vault("personal")
    target = config.vault_root / "brain" / "daily-log.md"
    with pytest.raises(gate.VaultAccessError):
        gate.resolve_note(str(target), config)


def test_symlink_escape_is_refused(make_vault, tmp_path: Path) -> None:
    config = make_vault("personal")
    secret = tmp_path / "secret.md"
    secret.write_text("outside the vault", encoding="utf-8")
    os.symlink(secret, config.vault_root / "brain" / "escape.md")
    with pytest.raises(gate.VaultAccessError):
        gate.resolve_note("brain/escape.md", config)


def test_dot_directories_are_unreachable(make_vault) -> None:
    config = make_vault("personal")
    hidden = config.vault_root / ".claude" / "settings.md"
    hidden.parent.mkdir()
    hidden.write_text("machine config", encoding="utf-8")
    with pytest.raises(gate.VaultAccessError):
        gate.resolve_note(".claude/settings.md", config)


def test_non_markdown_is_refused(make_vault) -> None:
    config = make_vault("personal")
    (config.vault_root / "work" / "data.csv").write_text("a,b", encoding="utf-8")
    with pytest.raises(gate.VaultAccessError):
        gate.resolve_note("work/data.csv", config)


def test_missing_note_is_refused(make_vault) -> None:
    config = make_vault("personal")
    with pytest.raises(gate.VaultAccessError):
        gate.resolve_note("brain/never-written.md", config)


def test_refusal_message_is_opaque_across_causes(make_vault) -> None:
    """Out-of-context and missing produce the SAME message for the same path.

    A probing caller must not be able to distinguish "exists but hidden from
    you" from "does not exist" (vault_mcp.py's deliberate design, kept).
    """
    rel_path = "personal/projects/side-project.md"

    config = make_vault("work")
    with pytest.raises(gate.VaultAccessError) as hidden:
        gate.resolve_note(rel_path, config)

    (config.vault_root / rel_path).unlink()
    with pytest.raises(gate.VaultAccessError) as missing:
        gate.resolve_note(rel_path, config)

    assert str(hidden.value) == str(missing.value)


def test_resolve_returns_real_path_in_context(make_vault) -> None:
    config = make_vault("personal")
    resolved = gate.resolve_note("brain/daily-log.md", config)
    assert resolved.is_file()
    assert resolved.is_relative_to(config.vault_root)


# --- the context gate (marked: must go red when defanged) -------------------


@pytest.mark.gating
def test_personal_context_sees_everything(make_vault) -> None:
    config = make_vault("personal")
    assert gate.filter_visible(ALL_NOTES, config) == ALL_NOTES


@pytest.mark.gating
def test_work_context_never_sees_personal(make_vault) -> None:
    config = make_vault("work")
    visible = gate.filter_visible(ALL_NOTES, config)
    assert "personal/projects/side-project.md" not in visible
    assert "work/decisions/platform-choice.md" in visible
    assert set(SHARED_NOTES) <= set(visible)


@pytest.mark.gating
def test_unknown_context_sees_shared_only(make_vault) -> None:
    """Fail-closed: an unmarked vault reveals least, not most."""
    config = make_vault(None)
    assert gate.filter_visible(ALL_NOTES, config) == SHARED_NOTES


@pytest.mark.gating
def test_blank_context_marker_is_unknown(make_vault) -> None:
    config = make_vault("")
    assert gate.filter_visible(ALL_NOTES, config) == SHARED_NOTES


@pytest.mark.gating
def test_school_is_shared_in_every_context(make_vault) -> None:
    """Deliberate recorded decision (the-vault#140 d9), pinned as a test."""
    for context in ("personal", "work", None):
        config = make_vault(context)
        assert "school/course-notes.md" in gate.filter_visible(ALL_NOTES, config)


@pytest.mark.gating
def test_work_context_cannot_read_personal_note(make_vault) -> None:
    """THE leak test: reading across the boundary must refuse."""
    config = make_vault("work")
    with pytest.raises(gate.VaultAccessError):
        gate.read_note("personal/projects/side-project.md", config)


@pytest.mark.gating
def test_personal_context_can_read_work_note(make_vault) -> None:
    """The asymmetry's other half: work/ is not hidden from personal."""
    config = make_vault("personal")
    text = gate.read_note("work/decisions/platform-choice.md", config)
    assert "Work-scope note" in text
