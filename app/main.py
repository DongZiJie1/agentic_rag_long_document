"""FastAPI application entry point"""
from fastapi import FastAPI
from app.config import AppConfig
import os

# Initialize configuration
config = AppConfig.from_env()

# Create data directories
os.makedirs(config.uploads_dir, exist_ok=True)
os.makedirs(config.parsed_dir, exist_ok=True)
os.makedirs(config.outlines_dir, exist_ok=True)
os.makedirs(config.sessions_dir, exist_ok=True)
os.makedirs(config.parse_tasks_dir, exist_ok=True)

# Create FastAPI app
app = FastAPI(
    title="Agentic RAG Long Document System",
    description="Intelligent Q&A and cross-document analysis for long documents",
    version="0.1.0"
)


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "ok",
        "service": "Agentic RAG Long Document System",
        "version": "0.1.0"
    }


@app.get("/health")
async def health():
    """Detailed health check"""
    return {
        "status": "healthy",
        "llm_backend": config.llm.backend,
        "elasticsearch_url": config.elasticsearch.url
    }
