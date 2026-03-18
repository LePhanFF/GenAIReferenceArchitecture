"""Tool definitions for the LangChain agent.

Each tool calls a downstream microservice via HTTP, demonstrating
real service mesh communication patterns on K8s.
"""

import logging
from typing import Optional

import httpx
from langchain_core.tools import tool

from app.config import settings

logger = logging.getLogger(__name__)

# Shared async HTTP client with connection pooling
_client = httpx.AsyncClient(timeout=30.0)


@tool
async def search_knowledge_base(query: str) -> str:
    """Search the knowledge base using RAG for relevant information.

    Use this tool when the user asks a question that requires looking up
    information from documents, policies, or stored knowledge.

    Args:
        query: The search query or question to look up.
    """
    try:
        response = await _client.post(
            f"{settings.rag_service_url}/query",
            json={"question": query, "top_k": 5},
        )
        response.raise_for_status()
        data = response.json()

        answer = data["answer"]
        sources = data.get("sources", [])
        source_refs = "\n".join(
            f"  - {s['metadata'].get('source', 'unknown')}" for s in sources[:3]
        )

        return f"Answer: {answer}\n\nSources:\n{source_refs}"
    except httpx.HTTPStatusError as e:
        logger.error(f"RAG service error: {e.response.status_code}")
        return f"Error querying knowledge base: {e.response.status_code}"
    except httpx.ConnectError:
        return "Error: RAG service is unavailable"
    except Exception as e:
        logger.error(f"Knowledge base search failed: {e}")
        return f"Error: {str(e)}"


@tool
async def query_metrics(sql_query: str) -> str:
    """Query time-series metrics data using SQL (DuckDB on Parquet files).

    Use this tool when the user asks about metrics, performance data,
    or any quantitative analysis. Write standard SQL queries.

    Available tables:
        - request_metrics (timestamp, service, latency_ms, status_code, endpoint)
        - model_metrics (timestamp, model_name, tokens_per_second, gpu_utilization, memory_mb)
        - cost_metrics (timestamp, service, cost_usd, resource_type)

    Args:
        sql_query: A SQL query to execute against the metrics database.
    """
    try:
        import duckdb

        # Connect to DuckDB with Parquet files mounted via PVC
        conn = duckdb.connect(database=":memory:")

        # Register Parquet files as tables (mounted via K8s PVC)
        parquet_base = "/data/metrics"
        for table in ["request_metrics", "model_metrics", "cost_metrics"]:
            try:
                conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {table} AS "
                    f"SELECT * FROM read_parquet('{parquet_base}/{table}/*.parquet')"
                )
            except Exception:
                # Table's parquet files may not exist yet
                pass

        result = conn.execute(sql_query).fetchdf()
        conn.close()

        if result.empty:
            return "No results found for the query."

        # Format as a readable table (limit to 20 rows)
        return result.head(20).to_string(index=False)

    except Exception as e:
        logger.error(f"Metrics query failed: {e}")
        return f"Error executing query: {str(e)}"


@tool
async def classify_intent(text: str) -> str:
    """Classify the intent of user text using the ML service.

    Use this tool when you need to understand what the user is trying
    to do, or to route their request to the right handler.

    Args:
        text: The text to classify.
    """
    try:
        response = await _client.post(
            f"{settings.ml_service_url}/classify",
            json={"text": text},
        )
        response.raise_for_status()
        data = response.json()

        intent = data["intent"]
        confidence = data["confidence"]
        return f"Intent: {intent} (confidence: {confidence:.2%})"
    except httpx.HTTPStatusError as e:
        logger.error(f"ML service error: {e.response.status_code}")
        return f"Error classifying intent: {e.response.status_code}"
    except httpx.ConnectError:
        return "Error: ML service is unavailable"
    except Exception as e:
        logger.error(f"Intent classification failed: {e}")
        return f"Error: {str(e)}"


@tool
async def get_embeddings(text: str) -> str:
    """Get the embedding vector for a piece of text.

    Use this tool when you need to compute semantic similarity
    or get vector representations of text.

    Args:
        text: The text to embed.
    """
    try:
        response = await _client.post(
            f"{settings.embedding_url}/embed",
            json={"texts": [text]},
        )
        response.raise_for_status()
        data = response.json()

        dimension = data["dimension"]
        embedding = data["embeddings"][0]
        # Return summary (full vector is too large for agent context)
        preview = embedding[:5]
        return (
            f"Embedding computed: dimension={dimension}, "
            f"preview={[round(v, 4) for v in preview]}..."
        )
    except httpx.ConnectError:
        return "Error: Embedding service is unavailable"
    except Exception as e:
        logger.error(f"Embedding request failed: {e}")
        return f"Error: {str(e)}"


# Export all tools as a list for the agent
ALL_TOOLS = [
    search_knowledge_base,
    query_metrics,
    classify_intent,
    get_embeddings,
]
