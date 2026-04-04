"""FastAPI application entry point"""
import os
import uuid
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse

from app.config import AppConfig
from app.mineru_parser import MinerUParser, MinerUParseError

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
    version="0.1.0",
)

mineru_parser = MinerUParser(config.mineru)


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "ok",
        "service": "Agentic RAG Long Document System",
        "version": "0.1.0",
    }


@app.get("/health")
async def health():
    """Detailed health check"""
    return {
        "status": "healthy",
        "llm_backend": config.llm.backend,
        "elasticsearch_url": config.elasticsearch.url,
    }


@app.post("/parse")
async def parse_document(
    file: UploadFile = File(...),
    parse_method: str = Form(default="auto"),
    lang_list: str = Form(default="ch"),
    return_md: bool = Form(default=True),
):
    """Upload a PDF and parse it via MinerU.

    Returns the parsed result including Markdown content and structured
    content list from the MinerU service.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    # Save uploaded file
    doc_id = uuid.uuid4().hex[:12]
    safe_name = f"{doc_id}_{file.filename}"
    upload_path = Path(config.uploads_dir) / safe_name

    content = await file.read()
    upload_path.write_bytes(content)

    try:
        result = mineru_parser.parse_pdf(
            upload_path,
            parse_method=parse_method,
            lang_list=lang_list,
            return_md=return_md,
        )
    except MinerUParseError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Uploaded file lost unexpectedly")

    return JSONResponse(content={"doc_id": doc_id, "filename": file.filename, **result})
