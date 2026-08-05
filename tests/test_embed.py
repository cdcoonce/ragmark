"""FastembedEmbedder: identity/cache resolution (no model load) + real model behavior.

Split into two tiers per CLAUDE.md's CI shape (six legs, no warm cache, no
cache-restore step): the cacheless tier below runs unconditionally and loads
no weights; the `model`-marked tier loads the real model and is skipped by
the autouse fixture in `conftest.py` when no warm cache is present.
"""

from __future__ import annotations

from pathlib import Path

import fastembed
import numpy as np
import pytest

from ragmark.embed import CACHE_DIR_ENV_VAR, DEFAULT_MODEL, FastembedEmbedder
from ragmark.model import ModelIdentity

# --- cacheless tier: no model load ------------------------------------------


def test_identity_matches_pinned_model_no_load() -> None:
    embedder = FastembedEmbedder()
    assert embedder.identity() == ModelIdentity(
        name=DEFAULT_MODEL, dim=384, version=fastembed.__version__
    )


def test_cache_dir_defaults_to_ragmark_cache_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv(CACHE_DIR_ENV_VAR, raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    embedder = FastembedEmbedder()
    assert embedder.cache_dir == tmp_path / ".cache" / "ragmark" / "fastembed"


def test_cache_dir_env_var_beats_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env_dir = tmp_path / "env-cache"
    monkeypatch.setenv(CACHE_DIR_ENV_VAR, str(env_dir))
    embedder = FastembedEmbedder()
    assert embedder.cache_dir == env_dir


def test_cache_dir_constructor_arg_beats_env_var(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(CACHE_DIR_ENV_VAR, str(tmp_path / "env-cache"))
    arg_dir = tmp_path / "arg-cache"
    embedder = FastembedEmbedder(cache_dir=arg_dir)
    assert embedder.cache_dir == arg_dir


def test_construct_with_nonexistent_cache_dir_raises_nothing(tmp_path: Path) -> None:
    FastembedEmbedder(cache_dir=tmp_path / "does" / "not" / "exist")


# --- model tier: loads real weights -----------------------------------------


@pytest.mark.model
def test_embed_returns_normalized_float32_matrix() -> None:
    embedder = FastembedEmbedder()
    vectors = embedder.embed(["a", "b c"])
    assert vectors.shape == (2, 384)
    assert vectors.dtype == np.float32
    norms = np.linalg.norm(vectors, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)


@pytest.mark.model
def test_count_tokens_deterministic() -> None:
    text = "some representative markdown paragraph text"
    embedder = FastembedEmbedder()
    counts = {embedder.count_tokens(text) for _ in range(5)}
    assert len(counts) == 1

    other = FastembedEmbedder()
    assert other.count_tokens(text) == next(iter(counts))


@pytest.mark.model
def test_count_tokens_counts_special_tokens() -> None:
    assert FastembedEmbedder().count_tokens("a") == 3


@pytest.mark.model
def test_count_tokens_does_not_saturate() -> None:
    assert FastembedEmbedder().count_tokens("word " * 600) > 512


@pytest.mark.model
def test_count_tokens_monotonic_under_repetition() -> None:
    embedder = FastembedEmbedder()
    s = "a distinctive sentence used for the repetition check"
    assert embedder.count_tokens(s * 10) > embedder.count_tokens(s)
