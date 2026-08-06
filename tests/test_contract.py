"""The seed contract: decided constants, owed behavior, release-machinery guards.

Two kinds of test live here:

- **Pins** freeze decided values (map resolutions). An executor changing one
  goes red — making the change a visible decision, not a drive-by.
- **Owed-behavior markers**: strict xfails that pass while a module raises
  NotImplementedError and XPASS-fail the moment an implementation lands,
  forcing the landing slice to replace them with real behavior tests in the
  same PR (conductor act — see CLAUDE.md).
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

from ragmark import activity, chunk, gaps, neighbors, search
from ragmark.config import RagmarkConfig

OWED = pytest.mark.xfail(strict=True, raises=NotImplementedError, reason="owed to a build slice")


# --- pins -------------------------------------------------------------------


def test_decided_constants_are_pinned() -> None:
    assert chunk.HARD_TOKEN_CEILING == 512  # the-vault#140 d1
    assert search.MAX_RESULTS == 25  # the-vault#142
    assert search.OVERFETCH == 4  # the-vault#137 carry-over
    assert neighbors.DEFAULT_TOKEN_BUDGET == 4000  # the-vault#142
    # Gap banding migrates verbatim from graphmark metrics.py (the-vault#143 d2).
    assert gaps.GAPS_DEFAULT_THRESHOLD == 0.6
    assert gaps.GAPS_DEFAULT_MAX_SCORE == 0.92
    assert gaps.GAPS_DEFAULT_K == 8
    assert gaps.GAPS_DEFAULT_HUB_DEGREE == 40


def test_release_relock_names_this_package() -> None:
    """uv does not error on an unknown --upgrade-package name, so a rename
    would silently disable the release relock (graphmark's guard, carried)."""
    pyproject = tomllib.loads(
        (Path(__file__).parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    )
    build_command = pyproject["tool"]["semantic_release"]["build_command"]
    assert f"--upgrade-package {pyproject['project']['name']}" in build_command


# --- owed behavior ----------------------------------------------------------


def seed_config(tmp_path: Path) -> RagmarkConfig:
    vault = tmp_path / "vault"
    vault.mkdir(exist_ok=True)
    return RagmarkConfig.for_vault(vault)


@OWED
def test_owed_neighbors(tmp_path: Path) -> None:
    neighbors.vault_neighbors("a.md", config=seed_config(tmp_path))


@OWED
def test_owed_activity(tmp_path: Path) -> None:
    activity.recent_activity(config=seed_config(tmp_path))


@OWED
def test_owed_gaps(tmp_path: Path) -> None:
    gaps.gaps(config=seed_config(tmp_path))


def test_exactly_three_owed_behaviors_remain() -> None:
    """Guards the owed-xfail contract itself: each landing slice deletes its
    own `test_owed_*` marker, so the surviving count is a live check that no
    slice quietly dropped (or kept) one it shouldn't have."""
    module = sys.modules[__name__]
    owed = [
        name
        for name in dir(module)
        if name.startswith("test_owed_")
        and any(m.name == "xfail" for m in getattr(getattr(module, name), "pytestmark", ()))
    ]
    assert sorted(owed) == [
        "test_owed_activity",
        "test_owed_gaps",
        "test_owed_neighbors",
    ]
