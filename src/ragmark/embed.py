"""Embedding — the model seam.

The concrete model is decided by a golden-query bake-off during the build
(the-vault#140, decision 2); `DEFAULT_MODEL` seeds the incumbent. Whatever
wins: fastembed stays version-pinned, the model stays pinned, and the index
manifest records `ModelIdentity` so a mismatch is a detected error prompting
rebuild — never the silent shape-crash the survey found (the-vault#137).

`Embedder` is an ABC rather than a Protocol deliberately: implementations opt
in explicitly, and the identity property is part of the contract, not an
accident of shape.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ragmark.model import ModelIdentity

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
CACHE_DIR_ENV_VAR = "RAGMARK_FASTEMBED_CACHE"


class Embedder(ABC):
    """A pinned local embedding model."""

    @abstractmethod
    def identity(self) -> ModelIdentity:
        """Exact model identity, recorded in the index manifest."""

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> Any:
        """Embed *texts* → float32 array of shape (len(texts), dim)."""

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """Token count under THIS model's tokenizer (the chunker's ruler)."""


class FastembedEmbedder(Embedder):
    """fastembed-backed implementation.

    Lazy-imports fastembed and loads the model only on first use of
    `identity`, `embed`, or `count_tokens`, so constructing an instance and
    importing `ragmark` both stay cheap. The model cache location must be
    durable (the predecessor cached to $TMPDIR, which the OS evicts — the
    vault#137); resolution order is the constructor arg, then
    `RAGMARK_FASTEMBED_CACHE`, then `~/.cache/ragmark/fastembed`.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL, cache_dir: Path | None = None) -> None:
        self.model_name = model_name
        self.cache_dir = self._resolve_cache_dir(cache_dir)
        self._model: Any = None

    @staticmethod
    def _resolve_cache_dir(cache_dir: Path | None) -> Path:
        if cache_dir is not None:
            return cache_dir
        env_value = os.environ.get(CACHE_DIR_ENV_VAR)
        if env_value is not None:
            return Path(env_value)
        return Path.home() / ".cache" / "ragmark" / "fastembed"

    def _load_model(self) -> Any:
        if self._model is None:
            import fastembed

            self._model = fastembed.TextEmbedding(
                model_name=self.model_name, cache_dir=str(self.cache_dir)
            )
        return self._model

    def identity(self) -> ModelIdentity:
        import fastembed

        dim = fastembed.TextEmbedding.get_embedding_size(self.model_name)
        return ModelIdentity(name=self.model_name, dim=dim, version=fastembed.__version__)

    def embed(self, texts: Sequence[str]) -> Any:
        import numpy as np

        model = self._load_model()
        return np.array(list(model.embed(list(texts))), dtype=np.float32)

    def count_tokens(self, text: str) -> int:
        model = self._load_model()
        tokenizer = model.model.tokenizer
        truncation = tokenizer.truncation
        tokenizer.no_truncation()
        try:
            return len(tokenizer.encode(text).ids)
        finally:
            if truncation is not None:
                tokenizer.enable_truncation(**truncation)
