"""Agent Service - FastAPI application.

Provides a conversational AI agent with tool-calling capabilities.
The agent can search the knowledge base, query metrics, classify
intents, and compute embeddings by calling other microservices.
"""

import logging
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from langchain.agents import AgentExecutor
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, Field

from app.agent import create_agent
from app.config import settings

logger = logging.getLogger(settings.service_name)
logging.basicConfig(level=settings.log_level)


class AppState:
    agent: AgentExecutor = None


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize agent on startup."""
    logger.info("Initializing agent service...")
    try:
        state.agent = create_agent()
        logger.info("Agent initialized successfully")
    except Exception as e:
        logger.warning(f"Agent init deferred: {e}")
    yield
    logger.info("Agent service shut down")


app = FastAPI(
    title="Agent Service",
    description="Conversational AI agent with tool-calling capabilities",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------
class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="User message")
    history: Optional[list[ChatMessage]] = Field(
        default=None,
        description="Previous conversation messages",
    )


class ToolCall(BaseModel):
    tool: str
    input: str
    output: str


class ChatResponse(BaseModel):
    response: str
    tools_used: list[ToolCall]
    latency_ms: float


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Chat with the agent. Supports conversation history."""
    if state.agent is None:
        try:
            state.agent = create_agent()
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Agent not ready: {e}")

    start = time.time()

    # Convert history to LangChain message format
    chat_history = []
    if request.history:
        for msg in request.history:
            if msg.role == "user":
                chat_history.append(HumanMessage(content=msg.content))
            else:
                chat_history.append(AIMessage(content=msg.content))

    try:
        result = await state.agent.ainvoke({
            "input": request.message,
            "chat_history": chat_history,
        })

        latency_ms = (time.time() - start) * 1000

        # Extract tool usage from intermediate steps
        tools_used = []
        for step in result.get("intermediate_steps", []):
            action, observation = step
            tools_used.append(ToolCall(
                tool=action.tool,
                input=str(action.tool_input),
                output=str(observation)[:500],  # Truncate long outputs
            ))

        return ChatResponse(
            response=result["output"],
            tools_used=tools_used,
            latency_ms=round(latency_ms, 2),
        )
    except Exception as e:
        logger.error(f"Agent chat failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Chat failed: {str(e)}")


@app.get("/health")
async def health():
    """Health check for K8s probes."""
    return {
        "service": settings.service_name,
        "status": "healthy" if state.agent is not None else "initializing",
        "model": settings.vllm_model,
        "tools": ["search_knowledge_base", "query_metrics", "classify_intent", "get_embeddings"],
    }
