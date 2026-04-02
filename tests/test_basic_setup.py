"""Basic tests to verify project setup"""
import pytest
from app.config import AppConfig, ElasticsearchConfig, LLMConfig, EmbeddingConfig
from app.models import OutlineNode, OutlineTree, State, Task, Message


def test_config_initialization():
    """Test that configuration can be initialized"""
    config = AppConfig.from_env()
    assert config is not None
    assert config.max_agent_steps == 15
    assert config.context_compression_threshold == 0.8


def test_elasticsearch_config():
    """Test Elasticsearch configuration"""
    es_config = ElasticsearchConfig.from_env()
    assert es_config.index_name == "documents"


def test_llm_config():
    """Test LLM configuration"""
    llm_config = LLMConfig.from_env()
    assert llm_config.backend in ["claude", "vllm"]


def test_embedding_config():
    """Test Embedding configuration"""
    emb_config = EmbeddingConfig.from_env()
    assert emb_config.similarity_threshold == 0.85


def test_outline_node_creation():
    """Test OutlineNode creation and serialization"""
    node = OutlineNode(
        section_id="doc1_1",
        line_number=1,
        title="Introduction",
        level=1,
        children=[],
        parent_id=None
    )
    
    assert node.section_id == "doc1_1"
    assert node.line_number == 1
    assert node.level == 1
    
    # Test serialization
    node_dict = node.to_dict()
    assert node_dict["section_id"] == "doc1_1"
    
    # Test deserialization
    node_restored = OutlineNode.from_dict(node_dict)
    assert node_restored.section_id == node.section_id
    assert node_restored.line_number == node.line_number


def test_outline_tree_creation():
    """Test OutlineTree creation and serialization"""
    node1 = OutlineNode(
        section_id="doc1_1",
        line_number=1,
        title="Chapter 1",
        level=1
    )
    
    tree = OutlineTree(
        doc_id="doc1",
        nodes=[node1],
        total_lines=1
    )
    
    assert tree.doc_id == "doc1"
    assert len(tree.nodes) == 1
    
    # Test serialization roundtrip
    tree_dict = tree.to_dict()
    tree_restored = OutlineTree.from_dict(tree_dict)
    assert tree_restored.doc_id == tree.doc_id
    assert len(tree_restored.nodes) == len(tree.nodes)


def test_state_initialization():
    """Test State object initialization"""
    state = State(
        session_id="session1",
        doc_id="doc1"
    )
    
    assert state.session_id == "session1"
    assert state.doc_id == "doc1"
    assert len(state.visited_node_ids) == 0
    assert len(state.used_keywords) == 0
    assert state.current_step == 0
    assert state.cumulative_tokens == 0


def test_task_serialization():
    """Test Task serialization"""
    task = Task(
        task_id="task1",
        session_id="session1",
        document_id="doc1",
        extraction_goal="Extract key points",
        status="pending"
    )
    
    task_dict = task.to_dict()
    assert task_dict["task_id"] == "task1"
    assert task_dict["status"] == "pending"
    
    task_restored = Task.from_dict(task_dict)
    assert task_restored.task_id == task.task_id


def test_message_serialization():
    """Test Message serialization"""
    message = Message(
        message_id="msg1",
        message_type="cross_reference_request",
        source_reader_id="reader1",
        target_reader_id="reader2",
        payload={"info": "test"},
        created_at="2024-01-01T00:00:00"
    )
    
    msg_dict = message.to_dict()
    assert msg_dict["message_id"] == "msg1"
    
    msg_restored = Message.from_dict(msg_dict)
    assert msg_restored.message_id == message.message_id
    assert msg_restored.message_type == message.message_type
