"""Shared test infrastructure — including the gating defang hook.

`--defang-gate` disables the context filter for the whole run. It exists ONLY
so `scripts/teeth_check.py` can verify the gating suite by defect
re-injection (the-vault#144, decision 3): run the `gating`-marked tests
normally (must pass), then defanged (must FAIL — a gating suite that stays
green with the filter off is itself a build failure). The defang lives here,
in test infrastructure, so production code carries no disable knob.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ragmark.config import CONTEXT_FILE, RagmarkConfig
from ragmark.embed import FastembedEmbedder

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _skip_model_without_warm_cache(request: pytest.FixtureRequest) -> None:
    """Skip `model`-marked tests when the fastembed cache has no model tree.

    CI runs six legs with no warm cache and no cache-restore step; these
    tests must not attempt a ~67 MB download.
    """
    if request.node.get_closest_marker("model") is None:
        return
    cache_dir = FastembedEmbedder._resolve_cache_dir(None)
    if not (cache_dir / "models--qdrant--bge-small-en-v1.5-onnx-q").is_dir():
        pytest.skip("no warm fastembed cache present")


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--defang-gate",
        action="store_true",
        default=False,
        help="disable the context filter (teeth-check only; gating tests must then fail)",
    )


def pytest_configure(config: pytest.Config) -> None:
    if config.getoption("--defang-gate"):
        from ragmark import gate

        gate.visible_in_context = lambda rel_path, context, config: True  # type: ignore[assignment]


@pytest.fixture
def make_vault(tmp_path: Path):
    """Copy the gating fixture vault to tmp and stamp a machine context.

    Returns a factory: `make_vault("work")` → RagmarkConfig for a vault whose
    `.vault-context` says "work"; `make_vault(None)` leaves the vault
    unmarked (the "unknown" fail-closed case).
    """

    def _make(context: str | None) -> RagmarkConfig:
        vault_root = tmp_path / f"vault-{context or 'unmarked'}"
        shutil.copytree(FIXTURES / "gating" / "vault", vault_root)
        if context is not None:
            (vault_root / CONTEXT_FILE).write_text(context + "\n", encoding="utf-8")
        return RagmarkConfig.for_vault(vault_root)

    return _make
