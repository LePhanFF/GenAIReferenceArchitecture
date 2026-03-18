"""Configuration for Agent service."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Agent service configuration."""

    service_name: str = "agent-service"
    service_port: int = 8000
    log_level: str = "INFO"

    # vLLM inference endpoint (OpenAI-compatible)
    vllm_base_url: str = "http://inference:8000/v1"
    vllm_model: str = "Qwen/Qwen2.5-1.5B-Instruct"
    vllm_api_key: str = "not-needed"
    vllm_temperature: float = 0.1
    vllm_max_tokens: int = 1024

    # Downstream service URLs
    rag_service_url: str = "http://rag-service:8000"
    ml_service_url: str = "http://ml-service:8000"
    embedding_url: str = "http://embedding:8000"

    # Agent settings
    max_iterations: int = 10
    agent_verbose: bool = True

    model_config = {"env_prefix": "AGENT_"}


settings = Settings()
