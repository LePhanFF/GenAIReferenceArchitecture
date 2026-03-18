"""
RAG Ingestion Pipeline
======================
Ingests documents into pgvector for RAG retrieval.

Usage:
    # Local: ingest from a directory
    python ingest.py --source ./docs --source-type directory

    # S3: ingest from an S3 bucket
    python ingest.py --source s3://my-bucket/docs --source-type s3

    # K8s Job: configured via environment variables
    SOURCE_PATH=s3://my-bucket/docs SOURCE_TYPE=s3 python ingest.py

Environment Variables:
    SOURCE_PATH          - Path to documents (directory or S3 URI)
    SOURCE_TYPE          - "directory" or "s3" (default: directory)
    EMBEDDING_SERVICE_URL - URL of the embedding service (default: http://localhost:8002)
    PGVECTOR_HOST        - PostgreSQL host (default: localhost)
    PGVECTOR_PORT        - PostgreSQL port (default: 5432)
    PGVECTOR_DB          - Database name (default: ragdb)
    PGVECTOR_USER        - Database user (default: postgres)
    PGVECTOR_PASSWORD    - Database password (default: postgres)
    CHUNK_SIZE           - Text chunk size in characters (default: 1000)
    CHUNK_OVERLAP        - Overlap between chunks (default: 200)
    COLLECTION_NAME      - pgvector collection name (default: documents)
"""

import argparse
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import List

import boto3
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import (
    CSVLoader,
    DirectoryLoader,
    JSONLoader,
    PyPDFLoader,
    TextLoader,
    UnstructuredMarkdownLoader,
)
from langchain_core.documents import Document
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import PGVector
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class Config:
    SOURCE_PATH: str = os.getenv("SOURCE_PATH", "./docs")
    SOURCE_TYPE: str = os.getenv("SOURCE_TYPE", "directory")  # "directory" or "s3"
    EMBEDDING_SERVICE_URL: str = os.getenv("EMBEDDING_SERVICE_URL", "http://localhost:8002")
    PGVECTOR_HOST: str = os.getenv("PGVECTOR_HOST", "localhost")
    PGVECTOR_PORT: int = int(os.getenv("PGVECTOR_PORT", "5432"))
    PGVECTOR_DB: str = os.getenv("PGVECTOR_DB", "ragdb")
    PGVECTOR_USER: str = os.getenv("PGVECTOR_USER", "postgres")
    PGVECTOR_PASSWORD: str = os.getenv("PGVECTOR_PASSWORD", "postgres")
    CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "1000"))
    CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", "200"))
    COLLECTION_NAME: str = os.getenv("COLLECTION_NAME", "documents")

    @property
    def connection_string(self) -> str:
        return (
            f"postgresql+psycopg2://{self.PGVECTOR_USER}:{self.PGVECTOR_PASSWORD}"
            f"@{self.PGVECTOR_HOST}:{self.PGVECTOR_PORT}/{self.PGVECTOR_DB}"
        )


# ---------------------------------------------------------------------------
# Embedding wrapper — calls our embedding microservice
# ---------------------------------------------------------------------------

class EmbeddingServiceClient:
    """Wraps the embedding FastAPI service so LangChain can use it."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        resp = requests.post(
            f"{self.base_url}/embed",
            json={"texts": texts},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["embeddings"]

    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]


# ---------------------------------------------------------------------------
# Document loading
# ---------------------------------------------------------------------------

LOADER_MAP = {
    ".txt": TextLoader,
    ".md": UnstructuredMarkdownLoader,
    ".pdf": PyPDFLoader,
    ".csv": CSVLoader,
}


def load_from_directory(path: str) -> List[Document]:
    """Load documents from a local directory."""
    logger.info("Loading documents from directory: %s", path)
    docs: List[Document] = []
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Source directory not found: {path}")

    for ext, loader_cls in LOADER_MAP.items():
        loader = DirectoryLoader(
            str(p),
            glob=f"**/*{ext}",
            loader_cls=loader_cls,
            show_progress=True,
            use_multithreading=True,
        )
        loaded = loader.load()
        logger.info("  Loaded %d documents with extension %s", len(loaded), ext)
        docs.extend(loaded)

    # JSON files need special handling
    json_files = list(p.rglob("*.json"))
    for jf in json_files:
        try:
            loader = JSONLoader(str(jf), jq_schema=".", text_content=False)
            docs.extend(loader.load())
        except Exception as e:
            logger.warning("Failed to load JSON %s: %s", jf, e)

    logger.info("Total documents loaded: %d", len(docs))
    return docs


def load_from_s3(s3_uri: str) -> List[Document]:
    """Download files from S3 to a temp directory, then load them."""
    logger.info("Loading documents from S3: %s", s3_uri)
    # Parse s3://bucket/prefix
    parts = s3_uri.replace("s3://", "").split("/", 1)
    bucket = parts[0]
    prefix = parts[1] if len(parts) > 1 else ""

    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")

    with tempfile.TemporaryDirectory() as tmpdir:
        count = 0
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                local_path = Path(tmpdir) / key
                local_path.parent.mkdir(parents=True, exist_ok=True)
                s3.download_file(bucket, key, str(local_path))
                count += 1
        logger.info("Downloaded %d files from S3", count)
        return load_from_directory(tmpdir)


# ---------------------------------------------------------------------------
# Text splitting
# ---------------------------------------------------------------------------

def split_documents(docs: List[Document], chunk_size: int, chunk_overlap: int) -> List[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = splitter.split_documents(docs)
    logger.info("Split %d documents into %d chunks", len(docs), len(chunks))
    return chunks


# ---------------------------------------------------------------------------
# Embedding & storage
# ---------------------------------------------------------------------------

def store_in_pgvector(
    chunks: List[Document],
    embedding_client: EmbeddingServiceClient,
    connection_string: str,
    collection_name: str,
) -> None:
    """Embed chunks and store in pgvector."""
    logger.info("Storing %d chunks in pgvector (collection=%s)", len(chunks), collection_name)

    # Process in batches to avoid OOM
    batch_size = 50
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        texts = [c.page_content for c in batch]
        metadatas = [c.metadata for c in batch]
        embeddings = embedding_client.embed_documents(texts)

        PGVector.from_embeddings(
            text_embeddings=list(zip(texts, embeddings)),
            metadatas=metadatas,
            embedding=embedding_client,
            collection_name=collection_name,
            connection_string=connection_string,
            pre_delete_collection=False,
        )
        logger.info("  Stored batch %d-%d / %d", i, min(i + batch_size, len(chunks)), len(chunks))

    logger.info("Ingestion complete.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="RAG Document Ingestion Pipeline")
    parser.add_argument("--source", default=None, help="Source path (directory or S3 URI)")
    parser.add_argument("--source-type", choices=["directory", "s3"], default=None)
    parser.add_argument("--chunk-size", type=int, default=None)
    parser.add_argument("--chunk-overlap", type=int, default=None)
    parser.add_argument("--collection", default=None)
    args = parser.parse_args()

    cfg = Config()
    if args.source:
        cfg.SOURCE_PATH = args.source
    if args.source_type:
        cfg.SOURCE_TYPE = args.source_type
    if args.chunk_size:
        cfg.CHUNK_SIZE = args.chunk_size
    if args.chunk_overlap:
        cfg.CHUNK_OVERLAP = args.chunk_overlap
    if args.collection:
        cfg.COLLECTION_NAME = args.collection

    # Load
    if cfg.SOURCE_TYPE == "s3":
        docs = load_from_s3(cfg.SOURCE_PATH)
    else:
        docs = load_from_directory(cfg.SOURCE_PATH)

    if not docs:
        logger.warning("No documents found. Exiting.")
        sys.exit(0)

    # Split
    chunks = split_documents(docs, cfg.CHUNK_SIZE, cfg.CHUNK_OVERLAP)

    # Embed & store
    embedding_client = EmbeddingServiceClient(cfg.EMBEDDING_SERVICE_URL)
    store_in_pgvector(chunks, embedding_client, cfg.connection_string, cfg.COLLECTION_NAME)

    logger.info("Pipeline finished. %d chunks ingested.", len(chunks))


if __name__ == "__main__":
    main()
