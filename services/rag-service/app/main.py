"""RAG Service - FastAPI application.

Provides retrieval-augmented generation over a pgvector knowledge base.
Uses LangChain LCEL chains, self-hosted vLLM for generation, and a
self-hosted embedding service for vector operations.
"""

import logging
import time
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from langchain_core.embeddings import Embeddings
from pydantic import BaseModel, Field

from app.chains import create_rag_chain
from app.config import settings
from app.ingestion import ingest_documents

logger = logging.getLogger(settings.service_name)
logging.basicConfig(level=settings.log_level)


# ---------------------------------------------------------------------------
# Custom embedding class that calls our embedding microservice
# ---------------------------------------------------------------------------
class RemoteEmbeddings(Embeddings):
    """Embedding class that delegates to the embedding microservice."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=30.0)
        self._sync_client = httpx.Client(timeout=30.0)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        response = await self._client.post(
            f"{self.base_url}/v1/embeddings",
            json={"input": texts, "model": "all-MiniLM-L6-v2"},
        )
        response.raise_for_status()
        data = response.json()
        return [item["embedding"] for item in data["data"]]

    async def aembed_query(self, text: str) -> list[float]:
        results = await self.aembed_documents([text])
        return results[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        response = self._sync_client.post(
            f"{self.base_url}/v1/embeddings",
            json={"input": texts, "model": "all-MiniLM-L6-v2"},
        )
        response.raise_for_status()
        data = response.json()
        return [item["embedding"] for item in data["data"]]

    def embed_query(self, text: str) -> list[float]:
        results = self.embed_documents([text])
        return results[0]


# ---------------------------------------------------------------------------
# Application state
# ---------------------------------------------------------------------------
class AppState:
    embedding: RemoteEmbeddings = None
    rag_chain = None
    retriever = None


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize embedding client and RAG chain on startup."""
    logger.info("Initializing RAG service...")
    state.embedding = RemoteEmbeddings(settings.embedding_url)

    try:
        state.rag_chain, state.retriever = create_rag_chain(state.embedding)
        logger.info("RAG chain initialized successfully")
    except Exception as e:
        logger.warning(f"RAG chain init deferred (pgvector may not be ready): {e}")

    yield

    # Cleanup
    if state.embedding._client:
        await state.embedding._client.aclose()
    logger.info("RAG service shut down")


app = FastAPI(
    title="RAG Service",
    description="Retrieval-Augmented Generation over a pgvector knowledge base",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------
class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, description="The question to answer")
    top_k: Optional[int] = Field(None, ge=1, le=20, description="Number of docs to retrieve")


class SourceDocument(BaseModel):
    content: str
    metadata: dict


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceDocument]
    latency_ms: float


class IngestRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1, description="List of texts to ingest")
    metadatas: Optional[list[dict]] = Field(None, description="Optional metadata per text")


class IngestResponse(BaseModel):
    documents_received: int
    chunks_created: int
    collection: str
    status: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest):
    """Run a RAG query: retrieve relevant docs, generate an answer."""
    if state.rag_chain is None:
        # Lazy init if pgvector wasn't ready at startup
        try:
            state.rag_chain, state.retriever = create_rag_chain(state.embedding)
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"RAG chain not ready: {e}")

    start = time.time()

    try:
        # Retrieve source documents
        docs = await state.retriever.ainvoke(request.question)

        # Run the full chain
        answer = await state.rag_chain.ainvoke(request.question)

        latency_ms = (time.time() - start) * 1000

        sources = [
            SourceDocument(content=doc.page_content, metadata=doc.metadata)
            for doc in docs
        ]

        return QueryResponse(
            answer=answer,
            sources=sources,
            latency_ms=round(latency_ms, 2),
        )
    except Exception as e:
        logger.error(f"RAG query failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")


@app.post("/ingest", response_model=IngestResponse)
async def ingest(request: IngestRequest):
    """Ingest documents: split, embed, and store in pgvector."""
    if state.embedding is None:
        raise HTTPException(status_code=503, detail="Embedding service not initialized")

    try:
        result = await ingest_documents(
            texts=request.texts,
            metadatas=request.metadatas,
            embedding=state.embedding,
        )
        return IngestResponse(**result)
    except Exception as e:
        logger.error(f"Ingestion failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")


@app.get("/health")
async def health():
    """Health check endpoint for K8s liveness/readiness probes."""
    checks = {
        "service": settings.service_name,
        "status": "healthy",
        "embedding_configured": state.embedding is not None,
        "rag_chain_ready": state.rag_chain is not None,
    }

    # Optionally verify embedding service connectivity
    if state.embedding:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{settings.embedding_url}/health")
                checks["embedding_service"] = "reachable" if resp.status_code == 200 else "unreachable"
        except Exception:
            checks["embedding_service"] = "unreachable"

    return checks
