"""Configuration for RAG service using Pydantic Settings."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """RAG service configuration.

    All values can be overridden via environment variables.
    On K8s, these come from ConfigMaps/Secrets.
    """

    # Service identity
    service_name: str = "rag-service"
    service_port: int = 8000
    log_level: str = "INFO"

    # vLLM inference endpoint (OpenAI-compatible)
    vllm_base_url: str = "http://inference:8000/v1"
    vllm_model: str = "Qwen/Qwen2.5-1.5B-Instruct"
    vllm_api_key: str = "not-needed"  # vLLM doesn't require auth by default
    vllm_temperature: float = 0.1
    vllm_max_tokens: int = 1024

    # Embedding service endpoint
    embedding_url: str = "http://embedding:8000"

    # pgvector connection
    pgvector_host: str = "pgvector"
    pgvector_port: int = 5432
    pgvector_database: str = "vectordb"
    pgvector_user: str = "postgres"
    pgvector_password: str = "postgres"
    pgvector_collection: str = "documents"

    # RAG parameters
    chunk_size: int = 512
    chunk_overlap: int = 64
    retrieval_top_k: int = 5
    embedding_dimension: int = 384  # all-MiniLM-L6-v2

    @property
    def pgvector_connection_string(self) -> str:
        return (
            f"postgresql+psycopg://{self.pgvector_user}:{self.pgvector_password}"
            f"@{self.pgvector_host}:{self.pgvector_port}/{self.pgvector_database}"
        )

    model_config = {"env_prefix": "RAG_"}


settings = Settings()
