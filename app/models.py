"""Data models for the Agentic RAG system"""
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class OutlineNode:
    """A node in the document outline tree"""
    section_id: str
    line_number: int
    title: str
    level: int  # 1=H1, 2=H2, 3=H3
    children: list["OutlineNode"] = field(default_factory=list)
    parent_id: str | None = None
    
    def to_dict(self) -> dict:
        return {
            "section_id": self.section_id,
            "line_number": self.line_number,
            "title": self.title,
            "level": self.level,
            "children": [child.to_dict() for child in self.children],
            "parent_id": self.parent_id
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "OutlineNode":
        children = [cls.from_dict(child) for child in data.get("children", [])]
        return cls(
            section_id=data["section_id"],
            line_number=data["line_number"],
            title=data["title"],
            level=data["level"],
            children=children,
            parent_id=data.get("parent_id")
        )


@dataclass
class OutlineTree:
    """Document outline tree structure"""
    doc_id: str
    nodes: list[OutlineNode]
    total_lines: int
    
    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "nodes": [node.to_dict() for node in self.nodes],
            "total_lines": self.total_lines
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "OutlineTree":
        nodes = [OutlineNode.from_dict(node) for node in data["nodes"]]
        return cls(
            doc_id=data["doc_id"],
            nodes=nodes,
            total_lines=data["total_lines"]
        )


@dataclass
class ActionRecord:
    """Record of an action execution"""
    step: int
    action_type: str  # "search" | "read" | "answer" | "format_error"
    params: dict
    result_summary: str
    is_error: bool = False


@dataclass
class State:
    """Agent state object"""
    session_id: str
    doc_id: str
    visited_node_ids: set[str] = field(default_factory=set)
    used_keywords: list[str] = field(default_factory=list)
    action_history: list[ActionRecord] = field(default_factory=list)
    current_step: int = 0
    cumulative_tokens: int = 0
    outline_context: str = ""


@dataclass
class Task:
    """TaskBoard task definition"""
    task_id: str
    session_id: str
    document_id: str
    extraction_goal: str
    status: Literal["pending", "running", "completed", "failed"]
    result: "ExtractionResult | None" = None
    dependencies: list[str] = field(default_factory=list)
    retry_count: int = 0
    created_at: str = ""
    updated_at: str = ""
    
    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "session_id": self.session_id,
            "document_id": self.document_id,
            "extraction_goal": self.extraction_goal,
            "status": self.status,
            "result": self.result.to_dict() if self.result else None,
            "dependencies": self.dependencies,
            "retry_count": self.retry_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        result = ExtractionResult.from_dict(data["result"]) if data.get("result") else None
        return cls(
            task_id=data["task_id"],
            session_id=data["session_id"],
            document_id=data["document_id"],
            extraction_goal=data["extraction_goal"],
            status=data["status"],
            result=result,
            dependencies=data.get("dependencies", []),
            retry_count=data.get("retry_count", 0),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", "")
        )


@dataclass
class ExtractionResult:
    """Result of a Reader extraction task"""
    task_id: str
    document_id: str
    dimensions: dict[str, str]
    missing_dimensions: list[str] = field(default_factory=list)
    source_sections: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "document_id": self.document_id,
            "dimensions": self.dimensions,
            "missing_dimensions": self.missing_dimensions,
            "source_sections": self.source_sections
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ExtractionResult":
        return cls(
            task_id=data["task_id"],
            document_id=data["document_id"],
            dimensions=data["dimensions"],
            missing_dimensions=data.get("missing_dimensions", []),
            source_sections=data.get("source_sections", [])
        )


@dataclass
class Message:
    """MessageBus message"""
    message_id: str
    message_type: Literal[
        "cross_reference_request",
        "cross_reference_response",
        "supplement_request",
        "supplement_response"
    ]
    source_reader_id: str
    target_reader_id: str
    payload: dict
    created_at: str
    
    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "message_type": self.message_type,
            "source_reader_id": self.source_reader_id,
            "target_reader_id": self.target_reader_id,
            "payload": self.payload,
            "created_at": self.created_at
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Message":
        return cls(
            message_id=data["message_id"],
            message_type=data["message_type"],
            source_reader_id=data["source_reader_id"],
            target_reader_id=data["target_reader_id"],
            payload=data["payload"],
            created_at=data["created_at"]
        )


@dataclass
class DimensionMatrix:
    """Cross-document dimension comparison matrix"""
    session_id: str
    dimensions: list[str]
    documents: list[str]
    matrix: dict[str, dict[str, str | None]]
    # matrix[dimension][doc_id] = content | "NOT_PRESENT" | None (not extracted)


@dataclass
class ToolResult:
    """Result from a tool execution"""
    success: bool
    data: dict | None = None
    error: str | None = None
