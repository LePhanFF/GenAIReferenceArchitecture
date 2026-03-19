"""Prometheus metrics for the RAG service.

Exposes key performance indicators at /metrics for Prometheus to scrape.
These metrics feed into the Grafana dashboard (see k8s/base/monitoring/prometheus-stack.yaml).

WHAT WE TRACK AND WHY:
  - Query latency:      Are users waiting too long? Where's the bottleneck?
  - Retrieval time:     Is pgvector slow? Do we need more RAM or an index rebuild?
  - Generation time:    Is vLLM overloaded? Should we scale up or use a smaller model?
  - Token counts:       Cost tracking — input tokens (retrieval context) + output tokens
  - Query count:        Traffic patterns, error rates, success rates
  - Document count:     How much knowledge is in the system?

USAGE IN FASTAPI:
  from app.metrics import (
      track_query, track_retrieval, track_generation,
      track_tokens, update_document_count, metrics_endpoint,
  )

  # In your query endpoint:
  with track_query():
      with track_retrieval():
          docs = retriever.invoke(question)
      with track_generation():
          answer = chain.invoke(question)
      track_tokens(input_tokens=150, output_tokens=200)
"""

import time
from contextlib import contextmanager
from typing import Generator

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.requests import Request
from starlette.responses import Response

# ---------------------------------------------------------------------------
# Custom registry (avoids polluting the default registry with process metrics
# that aren't useful in a container — the node-exporter handles those)
# Use REGISTRY = None and default registry if you DO want process metrics.
# ---------------------------------------------------------------------------
REGISTRY = CollectorRegistry()

# ---------------------------------------------------------------------------
# Histograms — track latency distributions
# ---------------------------------------------------------------------------
# Buckets tuned for LLM workloads:
# - Retrieval: 10ms to 5s (pgvector queries are fast, but can slow under load)
# - Generation: 100ms to 60s (LLM generation varies wildly with output length)
# - Total query: 100ms to 120s (retrieval + generation + overhead)

QUERY_DURATION = Histogram(
    "rag_query_duration_seconds",
    "Total RAG query latency (retrieval + generation + overhead)",
    labelnames=["status"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0],
    registry=REGISTRY,
)

RETRIEVAL_DURATION = Histogram(
    "rag_retrieval_duration_seconds",
    "Time spent on vector similarity search in pgvector",
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
    registry=REGISTRY,
)

GENERATION_DURATION = Histogram(
    "rag_generation_duration_seconds",
    "Time spent on LLM generation (vLLM call)",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
    registry=REGISTRY,
)

# ---------------------------------------------------------------------------
# Counters — track totals
# ---------------------------------------------------------------------------
QUERIES_TOTAL = Counter(
    "rag_queries_total",
    "Total number of RAG queries processed",
    labelnames=["status"],  # "success" or "error"
    registry=REGISTRY,
)

TOKENS_TOTAL = Counter(
    "rag_tokens_total",
    "Total tokens processed (for cost tracking)",
    labelnames=["type"],  # "input" or "output"
    registry=REGISTRY,
)

# ---------------------------------------------------------------------------
# Gauge — current state
# ---------------------------------------------------------------------------
DOCUMENTS_TOTAL = Gauge(
    "rag_documents_total",
    "Number of documents currently ingested in the vector store",
    registry=REGISTRY,
)


# ---------------------------------------------------------------------------
# Helper functions — use these in your endpoints
# ---------------------------------------------------------------------------
@contextmanager
def track_query(status: str = "success") -> Generator[None, None, None]:
    """Context manager to track total query latency.

    Usage:
        with track_query() as _:
            result = do_rag_query()
        # On exception, status is automatically set to "error"
    """
    start = time.perf_counter()
    _status = status
    try:
        yield
    except Exception:
        _status = "error"
        raise
    finally:
        duration = time.perf_counter() - start
        QUERY_DURATION.labels(status=_status).observe(duration)
        QUERIES_TOTAL.labels(status=_status).inc()


@contextmanager
def track_retrieval() -> Generator[None, None, None]:
    """Context manager to track vector retrieval latency."""
    start = time.perf_counter()
    try:
        yield
    finally:
        RETRIEVAL_DURATION.observe(time.perf_counter() - start)


@contextmanager
def track_generation() -> Generator[None, None, None]:
    """Context manager to track LLM generation latency."""
    start = time.perf_counter()
    try:
        yield
    finally:
        GENERATION_DURATION.observe(time.perf_counter() - start)


def track_tokens(input_tokens: int = 0, output_tokens: int = 0) -> None:
    """Record token usage for cost tracking.

    Call this after each query with token counts from the LLM response.
    vLLM returns usage in the OpenAI-compatible response:
        response.usage.prompt_tokens, response.usage.completion_tokens
    """
    if input_tokens > 0:
        TOKENS_TOTAL.labels(type="input").inc(input_tokens)
    if output_tokens > 0:
        TOKENS_TOTAL.labels(type="output").inc(output_tokens)


def update_document_count(count: int) -> None:
    """Set the current document count (call after ingestion or on startup)."""
    DOCUMENTS_TOTAL.set(count)


# ---------------------------------------------------------------------------
# /metrics endpoint — mount this in your FastAPI app
# ---------------------------------------------------------------------------
async def metrics_endpoint(request: Request) -> Response:
    """Prometheus metrics endpoint.

    Add to your FastAPI app:
        from app.metrics import metrics_endpoint
        app.add_route("/metrics", metrics_endpoint)
    """
    return Response(
        content=generate_latest(REGISTRY),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
