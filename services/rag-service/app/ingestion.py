"""Document ingestion: splitting, embedding, and storing in pgvector."""

import logging
from typing import Optional

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_community.vectorstores.pgvector import PGVector

from app.config import settings

logger = logging.getLogger(__name__)


def create_text_splitter() -> RecursiveCharacterTextSplitter:
    """Create a text splitter with configured chunk size and overlap."""
    return RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""],
    )


async def ingest_documents(
    texts: list[str],
    metadatas: Optional[list[dict]] = None,
    embedding: Embeddings = None,
) -> dict:
    """Ingest documents into pgvector.

    Steps:
        1. Create Document objects from raw text + metadata
        2. Split into chunks using RecursiveCharacterTextSplitter
        3. Embed and store in pgvector

    Args:
        texts: List of raw text strings to ingest.
        metadatas: Optional list of metadata dicts (one per text).
        embedding: Embedding model instance.

    Returns:
        Dict with ingestion stats.
    """
    if metadatas is None:
        metadatas = [{}] * len(texts)

    # Create Document objects
    documents = [
        Document(page_content=text, metadata=meta)
        for text, meta in zip(texts, metadatas)
    ]

    # Split into chunks
    splitter = create_text_splitter()
    chunks = splitter.split_documents(documents)
    logger.info(f"Split {len(documents)} documents into {len(chunks)} chunks")

    # Store in pgvector (handles embedding internally)
    vectorstore = PGVector.from_documents(
        documents=chunks,
        embedding=embedding,
        connection=settings.pgvector_connection_string,
        collection_name=settings.pgvector_collection,
        pre_delete_collection=False,  # Append, don't replace
    )

    logger.info(f"Stored {len(chunks)} chunks in pgvector collection '{settings.pgvector_collection}'")

    return {
        "documents_received": len(documents),
        "chunks_created": len(chunks),
        "collection": settings.pgvector_collection,
        "status": "success",
    }
