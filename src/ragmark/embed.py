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

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

from ragmark.model import ModelIdentity

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"


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
    """fastembed-backed implementation (owed to a build slice).

    Lazy-imports fastembed on first embed so the core stays cheap to import;
    the model cache location must be durable (the predecessor cached to
    $TMPDIR, which the OS evicts — the-vault#137).
    """

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.model_name = model_name

    def identity(self) -> ModelIdentity:
        raise NotImplementedError("build slice: fastembed embedder (the-vault#140 d2)")

    def embed(self, texts: Sequence[str]) -> Any:
        raise NotImplementedError("build slice: fastembed embedder (the-vault#140 d2)")

    def count_tokens(self, text: str) -> int:
        raise NotImplementedError("build slice: fastembed embedder (the-vault#140 d2)")
