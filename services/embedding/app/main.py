"""Embedding Service - FastAPI application.

Wraps sentence-transformers to provide text embedding via an
OpenAI-compatible /v1/embeddings endpoint. Uses all-MiniLM-L6-v2
(22M params, ~80MB, runs on CPU).
"""

import logging
import time
from contextlib import asynccontextmanager
from typing import Union

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer

logger = logging.getLogger("embedding-service")
logging.basicConfig(level="INFO")

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


class AppState:
    model: SentenceTransformer = None


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load the embedding model on startup."""
    logger.info(f"Loading embedding model: {MODEL_NAME}")
    start = time.time()
    state.model = SentenceTransformer(MODEL_NAME)
    elapsed = time.time() - start
    logger.info(f"Model loaded in {elapsed:.1f}s — dimension={state.model.get_sentence_embedding_dimension()}")
    yield
    logger.info("Embedding service shut down")


app = FastAPI(
    title="Embedding Service",
    description="Text embedding via sentence-transformers (OpenAI-compatible)",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# OpenAI-compatible request/response models
# ---------------------------------------------------------------------------
class EmbeddingRequest(BaseModel):
    input: Union[str, list[str]] = Field(..., description="Text or list of texts to embed")
    model: str = Field(default="all-MiniLM-L6-v2", description="Model name (ignored, single model)")


class EmbeddingData(BaseModel):
    object: str = "embedding"
    embedding: list[float]
    index: int


class EmbeddingUsage(BaseModel):
    prompt_tokens: int
    total_tokens: int


class EmbeddingResponse(BaseModel):
    object: str = "list"
    data: list[EmbeddingData]
    model: str
    usage: EmbeddingUsage


# ---------------------------------------------------------------------------
# Simple endpoint
# ---------------------------------------------------------------------------
class SimpleEmbedRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1)


class SimpleEmbedResponse(BaseModel):
    embeddings: list[list[float]]
    dimension: int
    count: int
    latency_ms: float


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.post("/v1/embeddings", response_model=EmbeddingResponse)
async def openai_embeddings(request: EmbeddingRequest):
    """OpenAI-compatible embedding endpoint.

    This allows LangChain's OpenAIEmbeddings to work directly
    by pointing base_url to this service.
    """
    if state.model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    texts = [request.input] if isinstance(request.input, str) else request.input

    if not texts:
        raise HTTPException(status_code=400, detail="No input texts provided")

    try:
        embeddings = state.model.encode(texts, normalize_embeddings=True)

        # Estimate token count (rough: 1 token per 4 chars)
        total_chars = sum(len(t) for t in texts)
        est_tokens = max(1, total_chars // 4)

        data = [
            EmbeddingData(
                embedding=emb.tolist(),
                index=i,
            )
            for i, emb in enumerate(embeddings)
        ]

        return EmbeddingResponse(
            data=data,
            model=MODEL_NAME,
            usage=EmbeddingUsage(
                prompt_tokens=est_tokens,
                total_tokens=est_tokens,
            ),
        )
    except Exception as e:
        logger.error(f"Embedding failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Embedding failed: {str(e)}")


@app.post("/embed", response_model=SimpleEmbedResponse)
async def embed(request: SimpleEmbedRequest):
    """Simple embedding endpoint (non-OpenAI format)."""
    if state.model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    start = time.time()

    try:
        embeddings = state.model.encode(request.texts, normalize_embeddings=True)
        latency_ms = (time.time() - start) * 1000

        return SimpleEmbedResponse(
            embeddings=[emb.tolist() for emb in embeddings],
            dimension=int(embeddings.shape[1]),
            count=len(request.texts),
            latency_ms=round(latency_ms, 2),
        )
    except Exception as e:
        logger.error(f"Embedding failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Embedding failed: {str(e)}")


@app.get("/health")
async def health():
    """Health check for K8s probes."""
    return {
        "service": "embedding-service",
        "status": "healthy" if state.model is not None else "loading",
        "model": MODEL_NAME,
        "dimension": state.model.get_sentence_embedding_dimension() if state.model else None,
    }
