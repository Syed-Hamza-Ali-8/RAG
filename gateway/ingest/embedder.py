"""fastembed wrapper: batched local embeddings plus an exact token counter."""

import asyncio
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from fastembed import TextEmbedding
from tokenizers import Tokenizer

from gateway.errors import EmbeddingDimensionMismatch, EmbeddingModelError


class Embedder:
    def __init__(self, model_id: str, dim: int, cache_dir: Path, batch_size: int = 32) -> None:
        try:
            self._model = TextEmbedding(model_name=model_id, cache_dir=str(cache_dir))
        except Exception as exc:
            raise EmbeddingModelError(f"failed to load embedding model {model_id!r}: {exc}") from exc
        self.model_id = model_id
        self.batch_size = batch_size
        self.dim = self._model.embedding_size
        if self.dim != dim:
            raise EmbeddingDimensionMismatch(
                f"{model_id} outputs {self.dim}-dim vectors but EMBEDDING_DIM={dim}"
            )
        # fastembed's own tokenizer truncates at the model max, so counting with it can never
        # report an oversize chunk. Count with an untruncated copy of the same tokenizer.
        model_tokenizer: Tokenizer = self._model.model.tokenizer  # type: ignore[attr-defined]
        truncation = model_tokenizer.truncation
        if not truncation:
            raise EmbeddingModelError(f"{model_id}: tokenizer exposes no max sequence length")
        self.max_seq_len: int = truncation["max_length"]
        self._counter = Tokenizer.from_str(model_tokenizer.to_str())
        self._counter.no_truncation()
        self._counter.no_padding()

    def count_tokens(self, text: str, *, special_tokens: bool = True) -> int:
        """Tokens the model sees for `text`; with special_tokens, includes [CLS]/[SEP]."""
        return len(self._counter.encode(text, add_special_tokens=special_tokens).ids)

    def _embed_passages_sync(self, texts: Sequence[str]) -> list[list[float]]:
        for text in texts:
            n = self.count_tokens(text)
            if n > self.max_seq_len:
                # Would be silently truncated by the model; refuse instead.
                raise EmbeddingModelError(
                    f"text of {n} tokens exceeds {self.model_id} max {self.max_seq_len}"
                )
        vectors = list(self._model.passage_embed(list(texts), batch_size=self.batch_size))
        return [_to_list(v, self.dim) for v in vectors]

    def _embed_query_sync(self, text: str) -> list[float]:
        (vector,) = list(self._model.query_embed(text))
        return _to_list(vector, self.dim)

    async def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return await asyncio.to_thread(self._embed_passages_sync, texts)

    async def embed_query(self, text: str) -> list[float]:
        return await asyncio.to_thread(self._embed_query_sync, text)


def _to_list(vector: np.ndarray, dim: int) -> list[float]:
    if vector.shape != (dim,) or not np.all(np.isfinite(vector)):
        raise EmbeddingModelError(f"model returned an invalid vector of shape {vector.shape}")
    return [float(x) for x in vector]
