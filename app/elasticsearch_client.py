"""Elasticsearch client for document indexing and search"""
from elasticsearch import Elasticsearch, NotFoundError, helpers
from app.config import ElasticsearchConfig


# 默认索引 mapping：保留 embedding 向量字段（当前为空，后续接入 embedding 模型后填充）
INDEX_MAPPING = {
    "properties": {
        "doc_id": {"type": "keyword"},
        "doc_name": {"type": "keyword"},
        "type": {"type": "keyword"},           # "title" | "chunk"
        "section_id": {"type": "keyword"},
        "section_title": {"type": "text"},
        "content": {"type": "text"},
        "level": {"type": "integer"},
        "parent_id": {"type": "keyword"},
        "line_number": {"type": "integer"},     # 全局顺序（标题+chunk 混排）
        "chunk_index": {"type": "integer"},     # 章节内 chunk 顺序（标题=0）
        # dense_vector 占位，dims=384 匹配 paraphrase-multilingual-MiniLM-L12-v2
        "embedding": {
            "type": "dense_vector",
            "dims": 384,
            "index": True,
            "similarity": "cosine",
        },
    }
}


class ElasticsearchClient:
    """Elasticsearch client wrapper"""

    def __init__(self, config: ElasticsearchConfig):
        self.client = Elasticsearch(config.url)
        self.index_name = config.index_name

    # ── 索引管理 ──────────────────────────────────────────────

    def _index_exists(self) -> bool:
        """Check if index exists (compatible with ES 8.x + client 9.x)"""
        try:
            self.client.indices.get(index=self.index_name)
            return True
        except NotFoundError:
            return False

    def create_index(self):
        """Create the documents index if it doesn't exist"""
        if not self._index_exists():
            self.client.indices.create(
                index=self.index_name,
                mappings=INDEX_MAPPING,
            )

    def delete_index(self):
        """Delete the entire index"""
        if self._index_exists():
            self.client.indices.delete(index=self.index_name)

    def get_index_stats(self) -> dict:
        """Get basic stats for the index (doc count, size, etc.)"""
        stats = self.client.indices.stats(index=self.index_name)
        return stats["indices"][self.index_name]["total"]

    # ── 写入 ──────────────────────────────────────────────────

    def index_section(self, doc_id: str, doc_name: str, section_id: str,
                     section_title: str, content: str, level: int,
                     line_number: int = 0, chunk_index: int = 0):
        """Index a single document section (refresh for immediate visibility)"""
        self.client.index(
            index=self.index_name,
            document={
                "doc_id": doc_id,
                "doc_name": doc_name,
                "section_id": section_id,
                "section_title": section_title,
                "content": content,
                "level": level,
                "line_number": line_number,
                "chunk_index": chunk_index,
            },
            refresh=True,
        )

    def bulk_index_sections(self, sections: list[dict]):
        """
        Bulk index multiple sections at once.

        Each dict should contain: doc_id, doc_name, section_id, section_title,
                                   content, level, line_number, chunk_index
        """
        actions = [
            {"_index": self.index_name, "_source": s} for s in sections
        ]
        helpers.bulk(self.client, actions, refresh=True)

    def index_section_tree(self, doc_id: str, doc_name: str,
                           tree: "SectionTreeBuilder"):
        """
        将 SectionTreeBuilder 构建的章节树展平并批量写入 ES。

        每个 section 先写一条 title 文档，再逐个写 chunk 文档。
        line_number 为全局顺序（标题+chunk 混排），
        chunk_index 为章节内 chunk 顺序（标题固定为 0）。
        """
        self.create_index()

        docs = []
        line_no = 0

        def _walk(section_ids: list[str]):
            nonlocal line_no
            for sid in section_ids:
                section = tree.sections.get(sid)
                if not section:
                    continue

                # 写标题文档
                docs.append({
                    "doc_id": doc_id,
                    "doc_name": doc_name,
                    "type": "title",
                    "section_id": section.section_id,
                    "section_title": section.title,
                    "content": section.title,
                    "level": section.level,
                    "parent_id": section.parent_id,
                    "line_number": line_no,
                    "chunk_index": 0,
                })
                line_no += 1

                # 写内容 chunk
                for chunk_idx, block in enumerate(section.content):
                    text = block.get("text", "")
                    if not text:
                        continue

                    if block.get("type") == "table" and block.get("html"):
                        text = text + "\n" + block["html"]

                    docs.append({
                        "doc_id": doc_id,
                        "doc_name": doc_name,
                        "type": "chunk",
                        "section_id": section.section_id,
                        "section_title": section.title,
                        "content": text,
                        "level": section.level,
                        "parent_id": section.parent_id,
                        "line_number": line_no,
                        "chunk_index": chunk_idx + 1,  # +1 因为标题占了 0
                    })
                    line_no += 1

                # 递归子章节
                _walk(section.children)

        _walk(tree.root_children)

        if docs:
            self.bulk_index_sections(docs)

        return len(docs)

    # ── 更新 ──────────────────────────────────────────────────

    def update_section(self, section_id: str, **fields):
        """
        Update specific fields of a section identified by section_id.

        Example:
            client.update_section("sec_1", content="new content", level=2)
        """
        self.client.update_by_query(
            index=self.index_name,
            query={"term": {"section_id": section_id}},
            script={
                "source": "; ".join(
                    f"ctx._source.{k} = params.{k}" for k in fields
                ),
                "params": fields,
            },
            refresh=True,
        )

    def update_embedding(self, section_id: str, chunk_index: int,
                         embedding: list[float]):
        """
        更新指定 section + chunk 的向量字段。

        后续接入 embedding 模型时调用此方法填充向量。
        """
        self.client.update_by_query(
            index=self.index_name,
            query={
                "bool": {
                    "must": [
                        {"term": {"type": "chunk"}},
                        {"term": {"section_id": section_id}},
                        {"term": {"chunk_index": chunk_index}},
                    ]
                }
            },
            script={
                "source": "ctx._source.embedding = params.embedding",
                "params": {"embedding": embedding},
            },
            refresh=True,
        )

    # ── 查询 ──────────────────────────────────────────────────

    def document_exists(self, doc_id: str) -> bool:
        """Check if any sections for the given doc_id are indexed"""
        resp = self.client.count(
            index=self.index_name,
            query={"term": {"doc_id": doc_id}},
        )
        return resp["count"] > 0

    def get_sections_by_doc(self, doc_id: str, size: int = 100) -> list[dict]:
        """Get all chunks for a document, ordered by line_number"""
        resp = self.client.search(
            index=self.index_name,
            query={"term": {"doc_id": doc_id}},
            sort=[{"line_number": "asc"}],
            size=size,
        )
        return [hit["_source"] for hit in resp["hits"]["hits"]]

    def get_section_list(self, doc_id: str, size: int = 200) -> list[dict]:
        """
        查一篇文章的所有章节（去重），按文档顺序返回。
        """
        resp = self.client.search(
            index=self.index_name,
            query={
                "bool": {
                    "must": [
                        {"term": {"doc_id": doc_id}},
                        {"term": {"type": "title"}},
                    ]
                }
            },
            sort=[{"line_number": "asc"}],
            _source=["section_id", "section_title", "level", "parent_id", "type", "line_number"],
            size=size,
        )
        return [hit["_source"] for hit in resp["hits"]["hits"]]

    def get_child_sections(self, doc_id: str, parent_id: str,
                           is_recursive: bool = False) -> list[dict]:
        """
        查某个章节下的子章节，按文档顺序返回。

        is_recursive=False: 只查直接子章节
        is_recursive=True:  递归查所有子孙章节
        """
        if not is_recursive:
            resp = self.client.search(
                index=self.index_name,
                query={
                    "bool": {
                        "must": [
                            {"term": {"doc_id": doc_id}},
                            {"term": {"type": "title"}},
                            {"term": {"parent_id": parent_id}},
                        ]
                    }
                },
                sort=[{"line_number": "asc"}],
                _source=["section_id", "section_title", "level", "parent_id", "type", "line_number"],
                size=100,
            )
            return [hit["_source"] for hit in resp["hits"]["hits"]]

        # 递归模式：拿到文档所有标题，用 BFS 收集所有子孙
        resp = self.client.search(
            index=self.index_name,
            query={
                "bool": {
                    "must": [
                        {"term": {"doc_id": doc_id}},
                        {"term": {"type": "title"}},
                    ]
                }
            },
            _source=["section_id", "section_title", "level", "parent_id", "type", "line_number"],
            size=500,
        )
        all_titles = [hit["_source"] for hit in resp["hits"]["hits"]]

        # parent_id -> [children]
        children_map: dict[str, list[dict]] = {}
        for t in all_titles:
            pid = t.get("parent_id") or ""
            children_map.setdefault(pid, []).append(t)

        # BFS 从 parent_id 出发
        result = []
        queue = list(children_map.get(parent_id, []))
        while queue:
            node = queue.pop(0)
            result.append(node)
            queue.extend(children_map.get(node["section_id"], []))

        result.sort(key=lambda x: x.get("line_number", 0))
        return result

    def get_section_content(self, doc_id: str, section_id: str,
                            is_recursive: bool = False) -> list[dict]:
        """
        查某个章节下的内容（标题+chunk），按 line_number 排序。

        is_recursive=False: 只查当前章节
        is_recursive=True:  查当前章节 + 所有子孙章节
        """
        if not is_recursive:
            resp = self.client.search(
                index=self.index_name,
                query={
                    "bool": {
                        "must": [
                            {"term": {"doc_id": doc_id}},
                            {"term": {"section_id": section_id}},
                            {"terms": {"type": ["title", "chunk"]}},
                        ]
                    }
                },
                sort=[{"line_number": "asc"}],
                size=100,
            )
            return [hit["_source"] for hit in resp["hits"]["hits"]]

        # 递归模式：先拿到所有子孙 section_id
        titles_resp = self.client.search(
            index=self.index_name,
            query={
                "bool": {
                    "must": [
                        {"term": {"doc_id": doc_id}},
                        {"term": {"type": "title"}},
                    ]
                }
            },
            _source=["section_id", "parent_id"],
            size=500,
        )
        all_titles = [hit["_source"] for hit in titles_resp["hits"]["hits"]]

        # BFS 收集所有子孙 section_id（含自身）
        children_map: dict[str, list[str]] = {}
        for t in all_titles:
            pid = t.get("parent_id") or ""
            children_map.setdefault(pid, []).append(t["section_id"])

        descendant_ids = [section_id]
        queue = list(children_map.get(section_id, []))
        while queue:
            sid = queue.pop(0)
            descendant_ids.append(sid)
            queue.extend(children_map.get(sid, []))

        # 查这些 section 下的标题+chunk
        resp = self.client.search(
            index=self.index_name,
            query={
                "bool": {
                    "must": [
                        {"term": {"doc_id": doc_id}},
                        {"terms": {"type": ["title", "chunk"]}},
                        {"terms": {"section_id": descendant_ids}},
                    ]
                }
            },
            sort=[{"line_number": "asc"}],
            size=500,
        )
        return [hit["_source"] for hit in resp["hits"]["hits"]]

    def search(self, doc_id: str, keyword: str, size: int = 5) -> list[dict]:
        """
        Search for sections within a specific document.

        Args:
            doc_id: Document ID to search within
            keyword: Search keyword
            size: Number of results to return

        Returns:
            List of search results with section_id and highlighted snippets
        """
        response = self.client.search(
            index=self.index_name,
            query={
                "bool": {
                    "must": [
                        {"term": {"doc_id": doc_id}},
                        {"multi_match": {
                            "query": keyword,
                            "fields": ["section_title", "content"]
                        }}
                    ]
                }
            },
            highlight={
                "fields": {
                    "content": {},
                    "section_title": {}
                }
            },
            size=size
        )

        results = []
        for hit in response["hits"]["hits"]:
            result = {
                "section_id": hit["_source"]["section_id"],
                "section_title": hit["_source"]["section_title"],
                "line_number": hit["_source"]["line_number"],
                "highlights": []
            }

            if "highlight" in hit:
                for field, snippets in hit["highlight"].items():
                    result["highlights"].extend(snippets)

            results.append(result)

        return results

    def search_all(self, keyword: str, size: int = 10) -> list[dict]:
        """
        Search across ALL documents (cross-document search).

        Returns results from any document matching the keyword.
        """
        response = self.client.search(
            index=self.index_name,
            query={
                "multi_match": {
                    "query": keyword,
                    "fields": ["section_title^2", "content"]
                }
            },
            highlight={
                "fields": {
                    "content": {},
                    "section_title": {}
                }
            },
            size=size
        )

        results = []
        for hit in response["hits"]["hits"]:
            result = {
                "doc_id": hit["_source"]["doc_id"],
                "doc_name": hit["_source"].get("doc_name", ""),
                "section_id": hit["_source"]["section_id"],
                "section_title": hit["_source"]["section_title"],
                "line_number": hit["_source"]["line_number"],
                "score": hit["_score"],
                "highlights": []
            }

            if "highlight" in hit:
                for field, snippets in hit["highlight"].items():
                    result["highlights"].extend(snippets)

            results.append(result)

        return results

    # ── 删除 ──────────────────────────────────────────────────

    def delete_document(self, doc_id: str):
        """Delete all sections of a document"""
        self.client.delete_by_query(
            index=self.index_name,
            query={"term": {"doc_id": doc_id}},
            refresh=True,
        )

    def delete_section(self, section_id: str):
        """Delete a specific section by section_id"""
        self.client.delete_by_query(
            index=self.index_name,
            query={"term": {"section_id": section_id}},
            refresh=True,
        )
