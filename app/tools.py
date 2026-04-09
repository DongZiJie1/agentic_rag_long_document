"""Agent 可调用的工具集合。

每个工具由三部分组成：
  1. schema —— 给 LLM 看的工具描述（名称、说明、参数定义）
  2. handler —— 实际执行函数
  3. 在 TOOL_REGISTRY 中注册 —— 让 agent 能通过名字找到它

新增工具只需：写 schema + 写 handler + 注册到 TOOL_REGISTRY。
"""
import json
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from app.agent import AgentState
    from app.elasticsearch_client import ElasticsearchClient


# ══════════════════════════════════════════════════════════════════════════
#  Schema —— 给 LLM 看的工具定义
# ══════════════════════════════════════════════════════════════════════════

SEARCH_DOCUMENT_SCHEMA = {
    "name": "search_document",
    "description": "在文档中搜索关键词，返回匹配的章节及高亮片段",
    "input_schema": {
        "type": "object",
        "properties": {
            "keyword": {"type": "string", "description": "搜索关键词"},
            "size": {"type": "integer", "description": "返回结果数量，默认5", "default": 5},
        },
        "required": ["keyword"],
    },
}

READ_SECTION_SCHEMA = {
    "name": "read_section",
    "description": "读取指定章节的完整内容（含子章节）",
    "input_schema": {
        "type": "object",
        "properties": {
            "section_id": {"type": "string", "description": "章节ID，如 s1, s2_3"},
            "recursive": {
                "type": "boolean",
                "description": "是否递归读取子章节内容",
                "default": False,
            },
        },
        "required": ["section_id"],
    },
}

ANSWER_QUESTION_SCHEMA = {
    "name": "answer_question",
    "description": "基于已收集的信息回答用户问题（仅在信息充分时调用）",
    "input_schema": {
        "type": "object",
        "properties": {
            "answer": {"type": "string", "description": "对用户问题的完整回答"},
            "source_section_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "回答所依据的章节ID列表",
            },
        },
        "required": ["answer", "source_section_ids"],
    },
}

# 所有 schema 的集合，直接传给 LLM 的 tools 参数
TOOL_SCHEMAS = [SEARCH_DOCUMENT_SCHEMA, READ_SECTION_SCHEMA, ANSWER_QUESTION_SCHEMA]


# ══════════════════════════════════════════════════════════════════════════
#  Handlers —— 工具的实际实现
# ══════════════════════════════════════════════════════════════════════════

def search_document(tool_input: dict, es: "ElasticsearchClient", state: "AgentState") -> str:
    """在文档中搜索关键词，返回匹配的章节及高亮片段。"""
    keyword = tool_input["keyword"]
    size = tool_input.get("size", 5)
    # 记录搜索过的关键词，后续构建消息时会告诉 LLM，避免重复搜索
    state.search_keywords.append(keyword)
    # 调用 ES 进行全文搜索，返回匹配的章节和高亮片段
    results = es.search(state.doc_id, keyword, size=size)
    return json.dumps(results, ensure_ascii=False, indent=2)


def read_section(tool_input: dict, es: "ElasticsearchClient", state: "AgentState") -> str:
    """读取指定章节的完整内容（含子章节）。"""
    section_id = tool_input["section_id"]
    recursive = tool_input.get("recursive", False)
    # 调用 ES 读取章节内容，recursive=True 会连子章节一起读
    content = es.get_section_content(state.doc_id, section_id, is_recursive=recursive)
    if content:
        # 把读到的章节标题记录到 visited_sections（标记已访问）
        if not recursive:
            # 非递归模式：只记录目标章节本身
            state.visited_sections.extend(
                [c for c in content if c.get("type") == "title" and c["section_id"] == section_id]
            )
        else:
            # 递归模式：记录所有返回的章节标题
            state.visited_sections.extend(
                [c for c in content if c.get("type") == "title"]
            )
        # 把所有内容存入 context_chunks，后续可能用于构建答案的引用来源
        state.context_chunks.extend(content)
    return json.dumps(content, ensure_ascii=False, indent=2)


def answer_question(tool_input: dict, es: "ElasticsearchClient", state: "AgentState") -> str:
    """基于已收集的信息回答用户问题，记录最终答案到 state。"""
    # LLM 认为信息已经足够，给出最终答案
    answer = tool_input["answer"]
    source_ids = tool_input.get("source_section_ids", [])
    # 把答案和来源章节 ID 存入 state
    state.answer = answer
    state.sources = [
        {"section_id": sid, "section_title": ""}
        for sid in source_ids
    ]
    # 从已收集的内容中查找章节标题，填充到 sources 中（方便前端展示引用）
    title_map = {
        c["section_id"]: c.get("section_title", "")
        for c in state.context_chunks
        if c.get("type") == "title"
    }
    for src in state.sources:
        src["section_title"] = title_map.get(src["section_id"], "")
    return "DONE"


# ══════════════════════════════════════════════════════════════════════════
#  Registry —— 工具名 -> 处理函数的映射
# ══════════════════════════════════════════════════════════════════════════

TOOL_REGISTRY: dict[str, Callable] = {
    "search_document": search_document,
    "read_section": read_section,
    "answer_question": answer_question,
}
