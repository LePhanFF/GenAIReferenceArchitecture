"""LangChain Agent definition with tool calling.

Uses create_tool_calling_agent with an OpenAI-compatible vLLM backend.
The agent has access to tools that call other microservices in the platform.
"""

import logging

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_tool_calling_agent

from app.config import settings
from app.tools import ALL_TOOLS

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an AI platform assistant with access to the following capabilities:

1. **Knowledge Base Search** - Search documents and stored knowledge via RAG
2. **Metrics Query** - Query platform metrics using SQL (DuckDB)
3. **Intent Classification** - Classify user intent using ML models
4. **Embeddings** - Compute text embeddings for similarity analysis

Use the appropriate tools to answer the user's questions. Always explain
your reasoning and cite sources when using the knowledge base.

If you don't have enough information to answer, say so clearly.
Do not make up information."""


def create_agent() -> AgentExecutor:
    """Create a LangChain tool-calling agent.

    Returns:
        AgentExecutor configured with all platform tools.
    """
    llm = ChatOpenAI(
        base_url=settings.vllm_base_url,
        api_key=settings.vllm_api_key,
        model=settings.vllm_model,
        temperature=settings.vllm_temperature,
        max_tokens=settings.vllm_max_tokens,
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ])

    agent = create_tool_calling_agent(llm, ALL_TOOLS, prompt)

    executor = AgentExecutor(
        agent=agent,
        tools=ALL_TOOLS,
        verbose=settings.agent_verbose,
        max_iterations=settings.max_iterations,
        handle_parsing_errors=True,
        return_intermediate_steps=True,
    )

    return executor
