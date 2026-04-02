"""Configuration management for the Agentic RAG system"""
import os
from dataclasses import dataclass
from typing import Literal


@dataclass
class ElasticsearchConfig:
    """Elasticsearch connection configuration"""
    url: str
    index_name: str = "documents"
    
    @classmethod
    def from_env(cls) -> "ElasticsearchConfig":
        return cls(
            url=os.getenv("ELASTICSEARCH_URL", "http://localhost:9200"),
            index_name=os.getenv("ELASTICSEARCH_INDEX", "documents")
        )


@dataclass
class LLMConfig:
    """LLM client configuration"""
    backend: Literal["claude", "vllm"]
    anthropic_api_key: str | None = None
    vllm_base_url: str | None = None
    vllm_api_key: str | None = None
    model_name: str | None = None

    @classmethod
    def from_env(cls) -> "LLMConfig":
        backend = os.getenv("LLM_BACKEND", "claude")
        return cls(
            backend=backend,  # type: ignore
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            vllm_base_url=os.getenv("VLLM_BASE_URL", "http://localhost:8000"),
            vllm_api_key=os.getenv("VLLM_API_KEY", "EMPTY"),
            model_name=os.getenv("LLM_MODEL_NAME", "claude-3-5-sonnet-20241022" if backend == "claude" else "Qwen2.5-7B-Instruct")
        )


@dataclass
class EmbeddingConfig:
    """Embedding model configuration"""
    model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    similarity_threshold: float = 0.85
    
    @classmethod
    def from_env(cls) -> "EmbeddingConfig":
        return cls(
            model_name=os.getenv("EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"),
            similarity_threshold=float(os.getenv("EMBEDDING_SIMILARITY_THRESHOLD", "0.85"))
        )


@dataclass
class MinerUConfig:
    """MinerU document parser configuration"""
    model_path: str | None = None
    
    @classmethod
    def from_env(cls) -> "MinerUConfig":
        return cls(
            model_path=os.getenv("MINERU_MODEL_PATH")
        )


@dataclass
class AppConfig:
    """Application-wide configuration"""
    elasticsearch: ElasticsearchConfig
    llm: LLMConfig
    embedding: EmbeddingConfig
    mineru: MinerUConfig
    
    # File paths
    data_dir: str = "data"
    uploads_dir: str = "data/uploads"
    parsed_dir: str = "data/parsed"
    outlines_dir: str = "data/outlines"
    sessions_dir: str = "data/sessions"
    parse_tasks_dir: str = "data/parse_tasks"
    
    # Queue settings
    max_queue_size: int = 100
    parse_timeout_seconds: int = 300
    
    # Agent settings
    max_agent_steps: int = 15
    context_compression_threshold: float = 0.8
    
    @classmethod
    def from_env(cls) -> "AppConfig":
        return cls(
            elasticsearch=ElasticsearchConfig.from_env(),
            llm=LLMConfig.from_env(),
            embedding=EmbeddingConfig.from_env(),
            mineru=MinerUConfig.from_env(),
            data_dir=os.getenv("DATA_DIR", "data"),
            uploads_dir=os.getenv("UPLOADS_DIR", "data/uploads"),
            parsed_dir=os.getenv("PARSED_DIR", "data/parsed"),
            outlines_dir=os.getenv("OUTLINES_DIR", "data/outlines"),
            sessions_dir=os.getenv("SESSIONS_DIR", "data/sessions"),
            parse_tasks_dir=os.getenv("PARSE_TASKS_DIR", "data/parse_tasks"),
            max_queue_size=int(os.getenv("MAX_QUEUE_SIZE", "100")),
            parse_timeout_seconds=int(os.getenv("PARSE_TIMEOUT_SECONDS", "300")),
            max_agent_steps=int(os.getenv("MAX_AGENT_STEPS", "15")),
            context_compression_threshold=float(os.getenv("CONTEXT_COMPRESSION_THRESHOLD", "0.8"))
        )
