"""Cohere Rerank — re-orders retrieved chunks by question-relevance.

Hybrid retrieval gives us a candidate set; reranker tightens it.
Skipped when no Cohere API key is configured (lets us run without it during dev).
"""
from functools import lru_cache

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.models import Chunk

log = structlog.get_logger()

RERANK_MODEL = "rerank-v3.5"


@lru_cache(maxsize=1)
def _cohere_client():
    import cohere

    return cohere.ClientV2(api_key=settings.cohere_api_key)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
def rerank(query: str, chunks: list[Chunk], top_n: int = 5) -> list[Chunk]:
    """Rerank chunks by relevance to query. Returns ordered subset of length ≤ top_n."""
    if not chunks:
        return []
    if not settings.cohere_api_key:
        log.warning("rerank.skipped_no_key")
        return chunks[:top_n]

    client = _cohere_client()
    try:
        resp = client.rerank(
            model=RERANK_MODEL,
            query=query,
            documents=[c.text for c in chunks],
            top_n=min(top_n, len(chunks)),
        )
    except Exception as e:
        log.warning("rerank.failed", error=str(e)[:200])
        return chunks[:top_n]

    return [chunks[r.index] for r in resp.results]
