"""Embedding service — supports Cohere and OpenAI; selected via EMBEDDING_PROVIDER."""
from functools import lru_cache

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings

log = structlog.get_logger()


@lru_cache(maxsize=1)
def _cohere_client():
    import cohere

    return cohere.ClientV2(api_key=settings.cohere_api_key)


@lru_cache(maxsize=1)
def _openai_client():
    from openai import OpenAI

    return OpenAI(api_key=settings.openai_api_key)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
def embed_texts(texts: list[str], *, input_type: str = "search_document") -> list[list[float]]:
    """Embed a batch of texts. Returns a list of vectors aligned with input order.

    For Cohere, input_type matters:
      - "search_document" when embedding the corpus
      - "search_query" when embedding a user question

    For OpenAI, input_type is ignored (no asymmetric encoder).
    """
    if not texts:
        return []

    if settings.embedding_provider == "cohere":
        client = _cohere_client()
        resp = client.embed(
            texts=texts,
            model=settings.cohere_embed_model,
            input_type=input_type,
            embedding_types=["float"],
        )
        return [list(e) for e in resp.embeddings.float_]

    elif settings.embedding_provider == "openai":
        client = _openai_client()
        resp = client.embeddings.create(input=texts, model=settings.openai_embed_model)
        return [d.embedding for d in resp.data]

    else:
        raise ValueError(f"Unknown embedding provider: {settings.embedding_provider}")
