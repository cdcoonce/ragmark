"""Approved owner corpus scope is explicit, literal, and validated (#94)."""

from dataclasses import replace
from pathlib import Path

import pytest

from ragmark.config import RagmarkConfig


def test_scope_config_loads_toml_and_preserves_empty_defaults(tmp_path: Path) -> None:
    default = RagmarkConfig.for_vault(tmp_path)
    assert default.scoped_folders == frozenset()
    assert default.excluded_filenames == frozenset()
    assert default.excluded_path_prefixes == ()
    path = tmp_path / "ragmark.toml"
    path.write_text(
        'vault_root = "."\nscoped_folders = ["brain", "work"]\n'
        'excluded_filenames = ["AGENTS.md"]\n'
        'excluded_path_prefixes = ["work/tasks/", "work/Tasks.md"]\n'
    )
    loaded = RagmarkConfig.from_toml(path)
    assert loaded.scoped_folders == frozenset({"brain", "work"})
    assert loaded.excluded_filenames == frozenset({"AGENTS.md"})
    assert loaded.excluded_path_prefixes == ("work/tasks/", "work/Tasks.md")
    assert replace(default, scoped_folders=["brain"]).scoped_folders == frozenset({"brain"})


@pytest.mark.parametrize(
    "field", ["scoped_folders", "excluded_filenames", "excluded_path_prefixes"]
)
@pytest.mark.parametrize("value", ["brain", {"brain": True}, None, 3, [3], [None], [[]]])
def test_scope_collections_reject_wrong_types(tmp_path: Path, field: str, value) -> None:
    with pytest.raises(ValueError, match=field):
        replace(RagmarkConfig.for_vault(tmp_path), **{field: value})


@pytest.mark.parametrize("field", ["scoped_folders", "excluded_filenames"])
@pytest.mark.parametrize(
    "value", ["", ".", "..", "/brain", "brain/x", "x\\y", "C:", "*.md", "a?", "a[b]", "x\0y"]
)
def test_scope_names_are_literal_components(tmp_path: Path, field: str, value: str) -> None:
    with pytest.raises(ValueError, match=field):
        replace(RagmarkConfig.for_vault(tmp_path), **{field: [value]})


@pytest.mark.parametrize(
    "value",
    [
        "",
        "/work/",
        "../work/",
        "work/../x",
        "./work/",
        "work//x",
        "work\\x",
        "C:/work/",
        "work/*",
        "work/.",
        "work/..",
        "x\0y",
    ],
)
def test_scope_prefixes_are_literal_vault_relative_posix(tmp_path: Path, value: str) -> None:
    with pytest.raises(ValueError, match="excluded_path_prefixes"):
        replace(RagmarkConfig.for_vault(tmp_path), excluded_path_prefixes=[value])


@pytest.mark.parametrize(
    "field", ["scoped_folders", "excluded_filenames", "excluded_path_prefixes"]
)
def test_toml_string_is_not_silently_split_into_characters(tmp_path: Path, field: str) -> None:
    path = tmp_path / "invalid.toml"
    path.write_text(f'vault_root = "."\n{field} = "brain"\n')
    with pytest.raises(ValueError, match=field):
        RagmarkConfig.from_toml(path)


def test_reference_config_matches_approved_owner_scope() -> None:
    config = RagmarkConfig.from_toml(Path(__file__).parent.parent / "configs" / "the-vault.toml")
    assert config.scoped_folders == frozenset(
        {"brain", "work", "personal", "org", "perf", "reference", "school", "thinking"}
    )
    assert config.excluded_filenames == frozenset(
        {"AGENTS.md", "AGENTS.local.md", "CLAUDE.md", "CLAUDE.local.md"}
    )
    assert config.excluded_path_prefixes == (
        "work/Tasks.md",
        "personal/tasks/",
        "personal/archive/tasks/",
        "work/tasks/",
        "work/archive/tasks/",
        "work/archive/2026/tasks/",
    )
    assert config.excluded_dirs == frozenset({"templates", "session-logs"})
