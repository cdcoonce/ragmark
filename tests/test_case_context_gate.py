"""Filesystem case aliases must not change literal context or exclusion policy (#194)."""

from dataclasses import replace
from pathlib import Path

import pytest

from ragmark import gate
from ragmark.config import CONTEXT_FILE, RagmarkConfig


def _write(root: Path, relative: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Fixture content\n")


@pytest.mark.gating
@pytest.mark.parametrize("context", ["work", "unknown"])
def test_case_alias_cannot_make_personal_content_shared(tmp_path: Path, context: str) -> None:
    config = RagmarkConfig.for_vault(tmp_path)
    (tmp_path / CONTEXT_FILE).write_text(context)
    _write(tmp_path, "personal/diary.md")
    _write(tmp_path, "brain/shared.md")
    if not (tmp_path / "Personal/diary.md").exists():
        pytest.skip("filesystem does not accept alternate-case directory spelling")

    assert gate.read_note("brain/shared.md", config) == "Fixture content\n"
    for relative in ("Personal/diary.md", "personal/diary.md"):
        with pytest.raises(gate.VaultAccessError, match="path is not available"):
            gate.read_note(relative, config)


@pytest.mark.parametrize(
    "actual,alternate", [("templates", "Templates"), ("Templates", "templates")]
)
def test_configured_directory_exclusion_covers_case_alias(
    tmp_path: Path, actual: str, alternate: str
) -> None:
    config = replace(RagmarkConfig.for_vault(tmp_path), excluded_dirs=frozenset({actual}))
    _write(tmp_path, f"{actual}/note.md")
    if not (tmp_path / alternate / "note.md").exists():
        pytest.skip("filesystem does not accept alternate-case directory spelling")

    for relative in (f"{alternate}/note.md", f"{actual}/note.md"):
        with pytest.raises(gate.VaultAccessError, match="path is not available"):
            gate.read_note(relative, config)


@pytest.mark.gating
def test_physical_uppercase_owner_uses_explicit_literal_context_map(tmp_path: Path) -> None:
    config = replace(
        RagmarkConfig.for_vault(tmp_path), context_dirs={"Personal": "personal", "Work": "work"}
    )
    (tmp_path / CONTEXT_FILE).write_text("work")
    _write(tmp_path, "Personal/diary.md")
    _write(tmp_path, "Work/current.md")
    _write(tmp_path, "brain/shared.md")

    assert gate.read_note("Work/current.md", config) == "Fixture content\n"
    assert gate.read_note("brain/shared.md", config) == "Fixture content\n"
    with pytest.raises(gate.VaultAccessError, match="path is not available"):
        gate.read_note("Personal/diary.md", config)
