import math
from pathlib import Path

import pytest

from gateway.config import Settings
from gateway.errors import EmbeddingDimensionMismatch, EmbeddingModelError
from gateway.ingest.embedder import Embedder


async def test_embeddings_have_configured_dim_and_unit_norm(embedder: Embedder, settings: Settings) -> None:
    (vec,) = await embedder.embed_passages(["Annual leave is 22 days."])
    q = await embedder.embed_query("How much annual leave?")
    assert len(vec) == len(q) == settings.embedding_dim
    assert math.isclose(math.sqrt(sum(x * x for x in vec)), 1.0, rel_tol=1e-3)


def test_token_counter_is_not_truncated(embedder: Embedder) -> None:
    long_text = "word " * 2000
    assert embedder.count_tokens(long_text) > embedder.max_seq_len
    assert embedder.max_seq_len == 512


async def test_refuses_to_embed_text_the_model_would_truncate(embedder: Embedder) -> None:
    with pytest.raises(EmbeddingModelError):
        await embedder.embed_passages(["word " * 2000])


def test_dim_mismatch_fails_fast(settings: Settings) -> None:
    with pytest.raises(EmbeddingDimensionMismatch):
        Embedder(settings.embedding_model_id, 768, settings.embedding_cache_dir)


def test_unknown_model_raises_typed_error(tmp_path: Path) -> None:
    with pytest.raises(EmbeddingModelError):
        Embedder("not-a-real/model-id", 384, tmp_path)
