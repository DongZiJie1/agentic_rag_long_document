"""FastAPI application entry point"""
import logging
import os
import uuid
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse

from app.config import AppConfig
from app.mineru_parser import MinerUParser, MinerUParseError
from app.elasticsearch_client import ElasticsearchClient
from app.llm_client import create_llm

logger = logging.getLogger(__name__)

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
es_client = ElasticsearchClient(config.elasticsearch)


@app.on_event("startup")
async def startup():
    """Ensure ES index exists on startup (best-effort, don't block if ES is down)"""
    try:
        es_client.create_index()
        logger.info("Elasticsearch index '%s' ready", config.elasticsearch.index_name)
    except Exception as exc:
        logger.warning("Elasticsearch not available at startup: %s", exc)


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
            return_middle_json=True,
        )
    except MinerUParseError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Uploaded file lost unexpectedly")

    # Build section tree from middle_json and index into ES
    outline = None
    indexed_chunks = 0
    middle_json = result.get("middle_json")
    if middle_json:
        from app.section_parser import SectionTreeBuilder

        tree = SectionTreeBuilder.from_middle_json(middle_json)
        tree.build_tree()
        outline = tree.to_dict()

        # Index all sections into Elasticsearch (best-effort)
        try:
            indexed_chunks = es_client.index_section_tree(
                doc_id=doc_id,
                doc_name=file.filename,
                tree=tree,
            )
        except Exception as exc:
            logger.warning("ES indexing failed: %s", exc)
            indexed_chunks = 0

    return JSONResponse(content={
        "doc_id": doc_id,
        "filename": file.filename,
        "md_content": result.get("md_content", result.get("markdown", "")),
        "content_list": result.get("content_list", []),
        "outline": outline,
        "es_indexed_chunks": indexed_chunks,
    })


# ── 文档章节查询 ───────────────────────────────────────────

@app.get("/documents/{doc_id}/sections")
async def get_document_sections(doc_id: str):
    """查一篇文章的所有章节（去重）"""
    try:
        sections = es_client.get_section_list(doc_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"doc_id": doc_id, "sections": sections}


@app.get("/documents/{doc_id}/sections/{section_id}/children")
async def get_section_children(doc_id: str, section_id: str, is_recursive: bool = False):
    """查某个章节下的子章节。is_recursive=true 时递归查所有子孙。"""
    try:
        children = es_client.get_child_sections(doc_id, section_id, is_recursive=is_recursive)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"doc_id": doc_id, "section_id": section_id, "children": children}


@app.get("/documents/{doc_id}/sections/{section_id}/content")
async def get_section_content(doc_id: str, section_id: str, is_recursive: bool = False):
    """查某个章节下的内容。is_recursive=true 时包含所有子孙章节的内容。"""
    try:
        content = es_client.get_section_content(doc_id, section_id, is_recursive=is_recursive)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"doc_id": doc_id, "section_id": section_id, "content": content}


@app.get("/documents/{doc_id}/search")
async def search_document(doc_id: str, keyword: str, size: int = 5):
    """在指定文档内搜索关键词"""
    try:
        results = es_client.search(doc_id, keyword, size=size)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"doc_id": doc_id, "keyword": keyword, "results": results}


# ── Agent 问答 ────────────────────────────────────────────────

@app.post("/agent/ask")
async def agent_ask(
    doc_id: str = Form(...),
    question: str = Form(...),
    max_steps: int = Form(default=5),
    model_name: str = Form(default=None)
):
    """基于 LangGraph agent 的单文档问答。

    Agent 会自动搜索、阅读章节并生成答案。
    """
    from app.agent import run_agent

    llm = create_llm(config.llm, model_name=model_name)

    try:
        result = run_agent(
            doc_id=doc_id,
            question=question,
            llm=llm,
            es=es_client,
            max_steps=max_steps,
        )
    except Exception as exc:
        logger.exception("Agent execution failed")
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "doc_id": doc_id,
        "question": question,
        "answer": result.answer,
        "sources": result.sources,
        "steps": result.steps,
        "action_log": result.action_log,
    }
