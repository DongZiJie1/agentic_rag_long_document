"""LangGraph-based single-document Q&A agent.

Flow:
  analyze_query -> search -> read_content -> generate_answer -> (check_complete)
      ^                                              |
      └──────────── loop if insufficient ─────────────┘
"""
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from langgraph.graph import StateGraph, END

from app.elasticsearch_client import ElasticsearchClient
from app.llm_client import LLMClient
from app.tools import TOOL_SCHEMAS, TOOL_REGISTRY

logger = logging.getLogger(__name__)


# ── State ─────────────────────────────────────────────────────────────────

@dataclass
class AgentState:
    """Agent 在整个执行过程中的状态，贯穿 graph 的每个节点。

    LangGraph 会在每一步把这个 state 传给节点函数，节点函数可以读取和修改它。
    状态分为三组：输入、内部追踪、输出。
    """

    # ── 输入：调用 run_agent 时传入 ──
    doc_id: str                # 要查询的文档 ID
    question: str              # 用户的问题
    max_steps: int = 5         # 最大执行步数，防止无限循环

    # ── 内部追踪：agent 执行过程中自动维护 ──
    step: int = 0                                      # 当前已执行的步数
    search_keywords: list[str] = field(default_factory=list)   # 已搜索过的关键词，避免重复搜索
    visited_sections: list[dict] = field(default_factory=list) # 已访问过的章节标题列表
    context_chunks: list[dict] = field(default_factory=list)   # 已收集的内容片段（搜索结果+章节内容）
    action_log: list[str] = field(default_factory=list)        # 每一步的操作日志，用于调试
    section_list: list[dict] = field(default_factory=list)     # 文档大纲（首次进入时自动获取）

    # ── 输出：agent 执行完毕后的最终结果 ──
    answer: str = ""                           # 最终回答文本
    sources: list[dict] = field(default_factory=list)  # 回答引用的来源章节


# ── Prompt ─────────────────────────────────────────────────────────────────

#: 系统提示词，定义 agent 的角色、工作流程和行为规则。
SYSTEM_PROMPT = """你是一个文档问答助手。用户会上传一份文档并向你提问，你需要通过工具在文档中搜索和阅读内容来回答问题。

## 工作流程
1. 先理解用户问题，确定需要查找哪些信息
2. 使用 search_document 搜索相关关键词
3. 使用 read_section 读取感兴趣的章节的完整内容
4. 当你收集到足够的信息时，调用 answer_question 给出最终答案

## 规则
- 每一步只调用一个工具
- 如果搜索结果不理想，尝试换关键词重新搜索2
- 回答必须基于文档内容，不要编造
- 不确定时要如实说明
- 文档大纲已在上下文中提供，可据此定位目标章节"""

# ── Node functions ────────────────────────────────────────────────────────


def _build_messages(state: AgentState) -> list[dict]:
    """根据当前 state 构造发给 LLM 的消息列表。

    消息结构：
      - system: 系统提示词（固定）
      - user: 包含文档ID、用户问题、以及当前执行状态摘要

    状态摘要会告诉 LLM：
      1. 文档大纲（让 LLM 知道文档有哪些章节，方便选择要读哪个）
      2. 已访问过哪些章节（避免重复读取）
      3. 已搜索过哪些关键词（避免重复搜索）
      4. 已收集了多少内容片段（让 LLM 判断信息是否足够）
    """
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    # 拼接当前状态摘要
    context_parts = []

    # 文档大纲：让 LLM 知道文档结构，决定下一步读哪个章节
    if state.section_list:
        outline = json.dumps(state.section_list, ensure_ascii=False, indent=2)
        context_parts.append(f"文档大纲:\n{outline}")

    # 已访问章节：避免重复读取
    if state.visited_sections:
        secs = ", ".join(
            f'{s["section_id"]}({s["section_title"]})' for s in state.visited_sections
        )
        context_parts.append(f"已访问章节: {secs}")

    # 已搜索关键词：避免重复搜索
    if state.search_keywords:
        context_parts.append(f"已搜索关键词: {', '.join(state.search_keywords)}")

    # 已收集内容数量：让 LLM 判断是否可以回答了
    if state.context_chunks:
        context_parts.append(f"已收集 {len(state.context_chunks)} 条内容片段")

    # 如果什么都没做，提示尚未开始
    context_summary = "\n".join(context_parts) if context_parts else "尚未开始搜索。"

    # 组装 user 消息：告诉 LLM 当前文档、问题、状态，请它决定下一步
    messages.append(
        {
            "role": "user",
            "content": f"文档ID: {state.doc_id}\n\n用户问题: {state.question}\n\n--- 当前状态 ---\n{context_summary}\n\n请根据当前状态决定下一步操作。",
        }
    )
    return messages

# ── Graph node ────────────────────────────────────────────────────────────


def agent_node(state: AgentState, llm: LLMClient, es: ElasticsearchClient) -> dict:
    """Agent 的单步执行节点，LangGraph 每轮循环调用一次。

    执行流程：
      1. 首次进入时，自动从 ES 获取文档大纲（章节列表），存入 state
      2. 根据当前 state 构造消息，发给 LLM
      3. LLM 返回一个工具调用（或直接返回文本）
      4. 执行该工具，更新 state
      5. 返回 state 的增量更新（step +1）

    注意：LangGraph 要求节点函数返回一个 dict，其中的字段会合并回 state。
    这里我们只返回 step 的增量，state 的其他修改（如 search_keywords、answer 等）
    已经通过直接修改 state 对象完成了。
    """
    # 首次进入时自动获取文档大纲，让 LLM 知道文档结构
    if state.step == 0 and not state.section_list:
        state.section_list = es.get_section_list(state.doc_id)

    # 1. 构造消息
    messages = _build_messages(state)

    # 2. 调用 LLM，传入工具定义，让 LLM 决定下一步用哪个工具
    response = llm.complete(messages, tools=TOOL_SCHEMAS)

    # 3. 解析 LLM 响应，提取工具调用信息
    tool_name = None
    tool_input = None
    text_content = ""

    # Claude 风格的响应：response.content 是一个 block 列表
    # 可能包含 text block（普通文本）和 tool_use block（工具调用）
    if hasattr(response, "content"):
        for block in response.content:
            if hasattr(block, "type") and block.type == "tool_use":
                tool_name = block.name
                tool_input = block.input
                break
            elif hasattr(block, "type") and block.type == "text":
                text_content = block.text

    # OpenAI / vLLM 风格的响应：response.choices[0].message
    # message.tool_calls 存在表示有工具调用
    elif hasattr(response, "choices"):
        choice = response.choices[0]
        if choice.message.tool_calls:
            tc = choice.message.tool_calls[0]
            tool_name = tc.function.name
            tool_input = json.loads(tc.function.arguments)
        else:
            text_content = choice.message.content or ""

    # 4. 如果 LLM 没有调用任何工具（只返回了文本），将其作为答案
    if not tool_name:
        if text_content:
            state.answer = text_content
            state.action_log.append(f"step {state.step}: LLM returned text without tool call")
        return {"step": state.step + 1}

    # 5. 执行工具
    handler = TOOL_REGISTRY.get(tool_name)
    result = handler(tool_input, es, state) if handler else f"未知工具: {tool_name}"
    state.action_log.append(f"step {state.step}: {tool_name}({json.dumps(tool_input, ensure_ascii=False)})")

    # 6. 如果工具是 answer_question，说明 agent 已给出最终答案，后续 should_continue 会结束循环
    if tool_name == "answer_question":
        return {"step": state.step + 1, "answer": state.answer, "sources": state.sources}

    return {"step": state.step + 1}


# ── Conditional edge ──────────────────────────────────────────────────────


def should_continue(state: AgentState) -> Literal["continue", "end"]:
    """判断 agent 循环是否应该继续。

    结束条件（满足任一即结束）：
      1. state.answer 不为空 —— agent 已经调用 answer_question 给出了答案
      2. step >= max_steps —— 达到最大步数限制，防止无限循环

    返回值会映射到 LangGraph 的条件边：
      - "continue" -> 回到 agent 节点继续执行
      - "end"      -> 跳出循环，流程结束
    """
    if state.answer:
        return "end"
    if state.step >= state.max_steps:
        return "end"
    return "continue"


# ── Graph builder ─────────────────────────────────────────────────────────


def build_agent_graph(llm: LLMClient, es: ElasticsearchClient) -> Any:
    """构建并编译 LangGraph 图。

    图的结构非常简单（单节点循环）：
      agent 节点 --[should_continue]--> agent 节点（继续）
                 --[should_continue]--> END（结束）

    因为 llm 和 es 是外部依赖，不能直接放进 state，
    所以用闭包把它们包进 _agent_step 里，让 LangGraph 调用时自动传入。
    """
    # 用闭包把 llm、es 绑定到节点函数上
    def _agent_step(state: AgentState) -> dict:
        return agent_node(state, llm, es)

    # 创建状态图，指定状态类型为 AgentState
    graph = StateGraph(AgentState)

    # 添加唯一的节点 "agent"
    graph.add_node("agent", _agent_step)

    # 设置入口点：流程从 "agent" 节点开始
    graph.set_entry_point("agent")

    # 添加条件边：每次 agent 节点执行完后，调用 should_continue 判断下一步
    graph.add_conditional_edges(
        "agent",
        should_continue,
        {
            "continue": "agent",  # 继续循环 → 回到 agent 节点
            "end": END,           # 结束 → 整个流程终止
        },
    )

    # 编译图，返回可执行的 LangGraph app
    return graph.compile()


# ── Public API ────────────────────────────────────────────────────────────


@dataclass
class AgentResult:
    """Agent 执行完毕后的最终结果，对外暴露的简单数据结构。"""

    answer: str              # 最终回答文本
    sources: list[dict]      # 回答引用的来源章节（含 section_id 和 section_title）
    steps: int               # 实际执行的步数
    action_log: list[str]    # 每一步的操作日志


def run_agent(
    doc_id: str,
    question: str,
    llm: LLMClient,
    es: ElasticsearchClient,
    max_steps: int = 5,
) -> AgentResult:
    """运行单文档 Q&A agent，对外暴露的主入口。

    使用方式：
        result = run_agent("doc_123", "这份文档的主要结论是什么？", llm, es)
        print(result.answer)

    执行流程：
      1. 构建 LangGraph 图（build_agent_graph）
      2. 创建初始状态（AgentState），传入 doc_id 和 question
      3. 调用 graph.invoke 运行整个 agent 循环
      4. 从最终状态中提取 answer、sources 等结果，封装成 AgentResult 返回
    """
    # 构建图
    graph = build_agent_graph(llm, es)

    # 创建初始状态
    initial_state = AgentState(
        doc_id=doc_id,
        question=question,
        max_steps=max_steps,
    )

    # 运行 agent 循环，直到结束
    final_state = graph.invoke(initial_state)

    # LangGraph invoke 返回的可能是 dict（取决于版本），需要兼容处理
    if isinstance(final_state, dict):
        return AgentResult(
            answer=final_state.get("answer", "未能从文档中找到相关信息。"),
            sources=final_state.get("sources", []),
            steps=final_state.get("step", 0),
            action_log=final_state.get("action_log", []),
        )

    # 如果返回的是 AgentState 对象，直接取属性
    return AgentResult(
        answer=final_state.answer or "未能从文档中找到相关信息。",
        sources=final_state.sources,
        steps=final_state.step,
        action_log=final_state.action_log,
    )
