"""LangChain LCEL RAG chain definition."""

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_openai import ChatOpenAI
from langchain_community.vectorstores.pgvector import PGVector
from langchain_core.embeddings import Embeddings

from app.config import settings


RAG_SYSTEM_PROMPT = """You are a helpful AI assistant. Answer the user's question
based on the provided context. If the context doesn't contain enough information
to answer the question, say so clearly. Do not make up information.

Context:
{context}"""

RAG_PROMPT = ChatPromptTemplate.from_messages([
    ("system", RAG_SYSTEM_PROMPT),
    ("human", "{question}"),
])


def format_docs(docs: list) -> str:
    """Format retrieved documents into a single context string."""
    formatted = []
    for i, doc in enumerate(docs, 1):
        source = doc.metadata.get("source", "unknown")
        formatted.append(f"[{i}] (source: {source})\n{doc.page_content}")
    return "\n\n".join(formatted)


def create_llm() -> ChatOpenAI:
    """Create the vLLM-backed LLM client (OpenAI-compatible)."""
    return ChatOpenAI(
        base_url=settings.vllm_base_url,
        api_key=settings.vllm_api_key,
        model=settings.vllm_model,
        temperature=settings.vllm_temperature,
        max_tokens=settings.vllm_max_tokens,
    )


def create_vectorstore(embedding: Embeddings) -> PGVector:
    """Create pgvector vectorstore connection."""
    return PGVector(
        connection=settings.pgvector_connection_string,
        collection_name=settings.pgvector_collection,
        embedding_function=embedding,
    )


def create_rag_chain(embedding: Embeddings):
    """Create the full RAG chain using LCEL.

    Chain flow:
        1. Take user question
        2. Retrieve relevant docs from pgvector
        3. Format docs into context string
        4. Pass context + question to LLM
        5. Parse response to string

    Returns:
        Tuple of (chain, retriever) so the caller can also access
        raw retrieved documents for the response.
    """
    vectorstore = create_vectorstore(embedding)
    retriever = vectorstore.as_retriever(
        search_type="similarity",
        search_kwargs={"k": settings.retrieval_top_k},
    )
    llm = create_llm()

    chain = (
        {
            "context": retriever | format_docs,
            "question": RunnablePassthrough(),
        }
        | RAG_PROMPT
        | llm
        | StrOutputParser()
    )

    return chain, retriever
