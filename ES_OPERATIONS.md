# Elasticsearch 操作总结

## 索引数据模型

### Mapping

| 字段 | 类型 | 说明 |
|---|---|---|
| `doc_id` | keyword | 文档唯一 ID |
| `doc_name` | keyword | 文档文件名 |
| `type` | keyword | `"title"` 或 `"chunk"`，标识文档类型 |
| `section_id` | keyword | 章节唯一 ID（如 `s1`, `s2`） |
| `section_title` | text | 章节标题（全文检索） |
| `content` | text | 正文内容（chunk）或标题文字（title） |
| `level` | integer | 标题层级，1=H1, 2=H2, ... |
| `parent_id` | keyword | 父章节 section_id，顶级章节为 null |
| `line_number` | integer | 全局顺序，标题+chunk 混排递增 |
| `chunk_index` | integer | 章节内顺序，标题=0，chunk 从 1 开始 |
| `embedding` | dense_vector | 向量占位（384维，cosine） |

### 存储示例

```
文档结构：
s1 (H1) "第一章 绪论"
├── chunk "本章主要介绍..."
├── chunk "研究背景如下..."
├── s2 (H2) "1.1 研究目的"
│   └── chunk "本文旨在..."
└── s3 (H2) "1.2 研究意义"
    └── chunk "本研究具有..."

ES 存储：
line=0  type=title  section_id=s1  chunk_index=0  content="第一章 绪论"
line=1  type=chunk  section_id=s1  chunk_index=1  content="本章主要介绍..."
line=2  type=chunk  section_id=s1  chunk_index=2  content="研究背景如下..."
line=3  type=title  section_id=s2  chunk_index=0  content="1.1 研究目的"
line=4  type=chunk  section_id=s2  chunk_index=1  content="本文旨在..."
line=5  type=title  section_id=s3  chunk_index=0  content="1.2 研究意义"
line=6  type=chunk  section_id=s3  chunk_index=1  content="本研究具有..."
```

---

## API 接口

### 1. 上传并解析文档

```
POST /parse
```

上传 PDF，MinerU 解析后自动构建章节树并写入 ES。

**请求：** `multipart/form-data`
- `file`: PDF 文件
- `parse_method`: 解析方式，默认 `auto`
- `lang_list`: 语言，默认 `ch`

**返回：**
```json
{
  "doc_id": "a1b2c3d4e5f6",
  "filename": "example.pdf",
  "md_content": "...",
  "content_list": [...],
  "outline": { "root_children": [...], "sections": {...} },
  "es_indexed_chunks": 42
}
```

---

### 2. 查文章所有章节

```
GET /documents/{doc_id}/sections
```

返回该文档的所有标题（type=title），按文档顺序。

**返回：**
```json
{
  "doc_id": "a1b2c3d4e5f6",
  "sections": [
    {"section_id": "s1", "section_title": "第一章 绪论", "level": 1, "parent_id": null, "type": "title", "line_number": 0},
    {"section_id": "s2", "section_title": "1.1 研究目的", "level": 2, "parent_id": "s1", "type": "title", "line_number": 3}
  ]
}
```

---

### 3. 查章节下的子章节

```
GET /documents/{doc_id}/sections/{section_id}/children?is_recursive={bool}
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `is_recursive` | `false` | `false` 只查直接子章节，`true` 递归查所有子孙 |

**示例：**
```bash
# 只查 s1 的直接子章节
GET /documents/abc/sections/s1/children

# 查 s1 下所有子孙章节
GET /documents/abc/sections/s1/children?is_recursive=true
```

**返回：**
```json
{
  "doc_id": "abc",
  "section_id": "s1",
  "children": [
    {"section_id": "s2", "section_title": "1.1 研究目的", "level": 2, "parent_id": "s1"},
    {"section_id": "s3", "section_title": "1.2 研究意义", "level": 2, "parent_id": "s1"}
  ]
}
```

---

### 4. 查章节下的内容

```
GET /documents/{doc_id}/sections/{section_id}/content?is_recursive={bool}
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `is_recursive` | `false` | `false` 只查当前章节，`true` 查当前章节 + 所有子孙章节 |

返回结果包含标题（type=title）和内容（type=chunk），按 `line_number` 排序。

**示例：**
```bash
# 只查 s1 本身的内容
GET /documents/abc/sections/s1/content

# 查 s1 + 所有子孙的内容
GET /documents/abc/sections/s1/content?is_recursive=true
```

**返回：**
```json
{
  "doc_id": "abc",
  "section_id": "s1",
  "content": [
    {"type": "title", "section_id": "s1", "content": "第一章 绪论",     "line_number": 0, "chunk_index": 0},
    {"type": "chunk", "section_id": "s1", "content": "本章主要介绍...", "line_number": 1, "chunk_index": 1},
    {"type": "chunk", "section_id": "s1", "content": "研究背景如下...", "line_number": 2, "chunk_index": 2},
    {"type": "title", "section_id": "s2", "content": "1.1 研究目的",   "line_number": 3, "chunk_index": 0},
    {"type": "chunk", "section_id": "s2", "content": "本文旨在...",     "line_number": 4, "chunk_index": 1}
  ]
}
```

---

### 5. 文档内搜索

```
GET /documents/{doc_id}/search?keyword={string}&size={int}
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `keyword` | 必填 | 搜索关键词 |
| `size` | 5 | 返回结果数 |

同时搜索 `section_title` 和 `content` 字段，返回高亮片段。

**返回：**
```json
{
  "doc_id": "abc",
  "keyword": "研究目的",
  "results": [
    {
      "section_id": "s2",
      "section_title": "1.1 研究目的",
      "line_number": 3,
      "highlights": ["本文<em>旨在</em>探讨..."]
    }
  ]
}
```

---

## ES Client 内部方法一览

### 索引管理

| 方法 | 说明 |
|---|---|
| `create_index()` | 创建索引（已存在则跳过） |
| `delete_index()` | 删除整个索引 |
| `get_index_stats()` | 获取索引统计（文档数、大小等） |

### 写入

| 方法 | 说明 |
|---|---|
| `index_section(...)` | 写入单条文档 |
| `bulk_index_sections(docs)` | 批量写入 |
| `index_section_tree(doc_id, doc_name, tree)` | 将章节树展平并批量写入，自动产生 title + chunk 文档 |

### 查询

| 方法 | 说明 |
|---|---|
| `document_exists(doc_id)` | 文档是否存在 |
| `get_sections_by_doc(doc_id)` | 获取文档所有条目（标题+chunk） |
| `get_section_list(doc_id)` | 获取文档所有标题（去重） |
| `get_child_sections(doc_id, parent_id, is_recursive)` | 查子章节 |
| `get_section_content(doc_id, section_id, is_recursive)` | 查章节内容（标题+chunk） |
| `search(doc_id, keyword, size)` | 文档内关键词搜索 |
| `search_all(keyword, size)` | 跨文档搜索 |

### 更新

| 方法 | 说明 |
|---|---|
| `update_section(section_id, **fields)` | 更新指定字段 |
| `update_embedding(section_id, chunk_index, embedding)` | 更新向量（仅 chunk） |

### 删除

| 方法 | 说明 |
|---|---|
| `delete_document(doc_id)` | 删除文档所有数据 |
| `delete_section(section_id)` | 删除指定章节 |

---

## 索引重建

修改 mapping 后需要重建索引：

```bash
# 删除旧索引
curl -X DELETE "localhost:9200/your_index_name"

# 重建（应用启动时自动创建，或手动）
curl -X PUT "localhost:9200/your_index_name" -H 'Content-Type: application/json' -d '{
  "mappings": {
    "properties": {
      "doc_id": {"type": "keyword"},
      "doc_name": {"type": "keyword"},
      "type": {"type": "keyword"},
      "section_id": {"type": "keyword"},
      "section_title": {"type": "text"},
      "content": {"type": "text"},
      "level": {"type": "integer"},
      "parent_id": {"type": "keyword"},
      "line_number": {"type": "integer"},
      "chunk_index": {"type": "integer"},
      "embedding": {"type": "dense_vector", "dims": 384, "index": true, "similarity": "cosine"}
    }
  }
}'
```

重建后需重新上传文档（`POST /parse`）以重新写入数据。
