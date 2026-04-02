"""Elasticsearch client for document indexing and search"""
from elasticsearch import Elasticsearch
from app.config import ElasticsearchConfig


class ElasticsearchClient:
    """Elasticsearch client wrapper"""

    def __init__(self, config: ElasticsearchConfig):
        self.client = Elasticsearch(config.url)
        self.index_name = config.index_name

    def create_index(self):
        """Create the documents index if it doesn't exist"""
        if not self.client.indices.exists(index=self.index_name).body:
            self.client.indices.create(
                index=self.index_name,
                mappings={
                    "properties": {
                        "doc_id": {"type": "keyword"},
                        "section_id": {"type": "keyword"},
                        "section_title": {"type": "text"},
                        "content": {"type": "text"},
                        "level": {"type": "integer"},
                        "line_number": {"type": "integer"}
                    }
                }
            )

    def index_section(self, doc_id: str, section_id: str, section_title: str,
                     content: str, level: int, line_number: int):
        """Index a document section"""
        self.client.index(
            index=self.index_name,
            document={
                "doc_id": doc_id,
                "section_id": section_id,
                "section_title": section_title,
                "content": content,
                "level": level,
                "line_number": line_number
            }
        )

    def search(self, doc_id: str, keyword: str, size: int = 5) -> list[dict]:
        """
        Search for sections in a document

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

    def delete_document(self, doc_id: str):
        """Delete all sections of a document"""
        self.client.delete_by_query(
            index=self.index_name,
            query={
                "term": {"doc_id": doc_id}
            }
        )
