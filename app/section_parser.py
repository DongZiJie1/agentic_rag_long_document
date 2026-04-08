"""Section tree builder from MinerU middle_json output.

Parses MinerU's middle_json (pdf_info -> para_blocks) into a hierarchical
section tree with heading levels determined by font size.
"""
import json
import logging
import os

logger = logging.getLogger(__name__)


class Section:
    """表示文档中的一个章节（标题 + 内容）"""

    def __init__(self, section_id: str, title: str, level: int):
        self.section_id = section_id  # 唯一标识，如 "s1", "s2_1"
        self.title = title
        self.level = level  # 1=H1, 2=H2, ...
        self.parent_id: str | None = None
        self.children: list[str] = []  # 子章节 section_id 列表
        self.content: list[dict] = []  # 该标题下的内容块列表

    def to_dict(self) -> dict:
        return {
            "section_id": self.section_id,
            "title": self.title,
            "level": self.level,
            "parent_id": self.parent_id,
            "children": self.children,
            "content": self.content,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Section":
        s = cls(data["section_id"], data["title"], data["level"])
        s.parent_id = data.get("parent_id")
        s.children = data.get("children", [])
        s.content = data.get("content", [])
        return s


class SectionTreeBuilder:
    """从 MinerU middle_json 构建章节树。

    支持两种输入方式：
    - from_json_file(path): 从 _middle.json 文件加载
    - from_middle_json(data): 直接传入 middle_json dict（API 调用场景）
    """

    def __init__(self, data: dict):
        self.data = data
        self.title_map: dict[float, int] = {}  # 字号 -> 标题层级
        self.sections: dict[str, Section] = {}  # section_id -> Section
        self.root_children: list[str] = []  # 顶级章节列表

    @classmethod
    def from_json_file(cls, json_path: str) -> "SectionTreeBuilder":
        """从 MinerU 生成的 _middle.json 文件加载"""
        if not os.path.exists(json_path):
            raise FileNotFoundError(f"文件未找到: {json_path}")
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return cls(data)

    @classmethod
    def from_middle_json(cls, middle_json: str | dict) -> "SectionTreeBuilder":
        """从 MinerU API 返回的 middle_json 构建。

        Args:
            middle_json: middle_json 数据，可以是 JSON 字符串或已解析的 dict。
        """
        if isinstance(middle_json, str):
            middle_json = json.loads(middle_json)
        return cls(middle_json)

    # ── 字号计算 ──────────────────────────────────────────────

    def _calculate_block_height(self, block):
        """从 bbox 计算文本高度作为字号"""
        if 'lines' in block and len(block['lines']) > 0:
            line_bbox = block['lines'][0]['bbox']
            return round(line_bbox[3] - line_bbox[1], 1)
        elif 'bbox' in block:
            return round(block['bbox'][3] - block['bbox'][1], 1)
        return 0

    def _extract_text(self, block) -> str:
        """从 block 的 lines/spans 中提取纯文本"""
        parts = []
        if 'lines' in block:
            for line in block['lines']:
                for span in line.get('spans', []):
                    parts.append(span.get('content', ''))
        return ''.join(parts).strip()

    def _extract_block_content(self, block) -> dict:
        """将 block 标准化为 content dict"""
        b_type = block.get('type')
        text = self._extract_text(block)

        item = {"type": b_type, "text": text}

        if b_type == 'table':
            html_parts = []
            for line in block.get('lines', []):
                for span in line.get('spans', []):
                    if 'html' in span:
                        html_parts.append(span['html'])
            item["html"] = '\n'.join(html_parts) if html_parts else None

        if b_type == 'image':
            item["img_path"] = block.get('img_path', '')

        return item

    # ── 层级分析 ──────────────────────────────────────────────

    def _analyze_hierarchy(self):
        """全文档扫描，建立 字号->标题层级 的动态映射

        对高度做聚类：差值 < 1.0 的视为同一层级，取均值作为代表。
        """
        title_heights = set()

        for page in self.data.get('pdf_info', []):
            for block in page.get('para_blocks', []):
                if block['type'] == 'title':
                    height = self._calculate_block_height(block)
                    if height > 0:
                        title_heights.add(height)

        if not title_heights:
            return

        # 按高度降序排列，差值 < 1.0 的聚为一组
        sorted_heights = sorted(title_heights, reverse=True)
        clusters = [[sorted_heights[0]]]
        for h in sorted_heights[1:]:
            if abs(h - clusters[-1][0]) < 1.0:
                clusters[-1].append(h)
            else:
                clusters.append([h])

        # 每个簇一个 level，均值作为代表高度
        for idx, cluster in enumerate(clusters):
            level = min(idx + 1, 6)
            avg_height = round(sum(cluster) / len(cluster), 1)
            for h in cluster:
                self.title_map[h] = level

        logger.info("标题层级映射 (高度->Level): %s", self.title_map)

    # ── 树构建（核心） ────────────────────────────────────────

    def build_tree(self):
        """
        按文档顺序遍历所有 block，构建标题树并关联内容。

        算法：
        1. 遇到 title block -> 创建新 Section，根据 level 挂到正确的父节点
        2. 遇到非 title block -> 追加到当前最深的 open section
        """
        self._analyze_hierarchy()

        self.sections = {}
        self.root_children = []

        # 用栈追踪当前打开的各级标题 path[level] = section_id
        # level=0 表示文档根
        path: dict[int, str] = {}
        counter = 0

        for page in self.data.get('pdf_info', []):
            for block in page.get('para_blocks', []):
                b_type = block.get('type')

                if b_type == 'title':
                    height = self._calculate_block_height(block)
                    level = self.title_map.get(height, 6)
                    text = self._extract_text(block)

                    if not text:
                        continue

                    counter += 1
                    sid = f"s{counter}"
                    section = Section(sid, text, level)

                    # 找父节点：找比当前 level 小的最近上级
                    parent_id = None
                    for p in range(level - 1, 0, -1):
                        if p in path:
                            parent_id = path[p]
                            break

                    if parent_id:
                        section.parent_id = parent_id
                        self.sections[parent_id].children.append(sid)
                    else:
                        self.root_children.append(sid)

                    self.sections[sid] = section

                    # 更新路径：当前 level 及更深层的旧路径都清掉
                    path[level] = sid
                    to_remove = [k for k in path if k > level]
                    for k in to_remove:
                        del path[k]

                else:
                    # 内容块 -> 追加到当前最深 open section
                    content_item = self._extract_block_content(block)
                    if not content_item["text"]:
                        continue

                    # path 中最大的 key 就是最深层
                    if path:
                        deepest = max(path.keys())
                        target_sid = path[deepest]
                        self.sections[target_sid].content.append(content_item)

        logger.info(
            "构建完成: %d 个章节, %d 个顶级节点",
            len(self.sections), len(self.root_children),
        )
        return self

    # ── 查询接口 ──────────────────────────────────────────────

    def get_section(self, section_id: str) -> Section | None:
        """根据 ID 获取章节"""
        return self.sections.get(section_id)

    def get_children(self, section_id: str) -> list[Section]:
        """获取某章节的所有直接子章节"""
        sec = self.sections.get(section_id)
        if not sec:
            return []
        return [self.sections[cid] for cid in sec.children if cid in self.sections]

    def get_subtree(self, section_id: str) -> dict:
        """递归获取以某章节为根的子树（含内容）"""
        sec = self.sections.get(section_id)
        if not sec:
            return {}

        return {
            "section_id": sec.section_id,
            "title": sec.title,
            "level": sec.level,
            "content": sec.content,
            "children": [self.get_subtree(cid) for cid in sec.children],
        }

    def get_leaf_sections(self) -> list[Section]:
        """获取所有叶子章节（无子章节的节点）"""
        return [s for s in self.sections.values() if not s.children]

    def get_content_by_section(self, section_id: str) -> list[dict]:
        """获取某章节自身的内容块（不含子章节内容）"""
        sec = self.sections.get(section_id)
        return sec.content if sec else []

    def get_all_content_under(self, section_id: str) -> list[dict]:
        """获取某章节及其所有子孙的内容（展平）"""
        sec = self.sections.get(section_id)
        if not sec:
            return []

        result = list(sec.content)
        for child_id in sec.children:
            result.extend(self.get_all_content_under(child_id))
        return result

    def find_section_by_title(self, keyword: str) -> list[Section]:
        """模糊搜索标题中包含 keyword 的所有章节"""
        return [s for s in self.sections.values() if keyword in s.title]

    # ── 序列化 / 反序列化 ─────────────────────────────────────

    def to_dict(self) -> dict:
        """导出完整的树结构为可序列化的 dict"""
        return {
            "root_children": self.root_children,
            "sections": {
                sid: sec.to_dict() for sid, sec in self.sections.items()
            },
        }

    def to_json(self, output_path: str):
        """导出树结构为 JSON 文件"""
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        logger.info("树结构已导出: %s", output_path)

    @classmethod
    def from_dict(cls, data: dict) -> "SectionTreeBuilder":
        """从 to_dict() 的结果重建（无需原始 middle_json）"""
        obj = cls.__new__(cls)
        obj.data = {}
        obj.title_map = {}
        obj.root_children = data["root_children"]
        obj.sections = {
            sid: Section.from_dict(sec_data)
            for sid, sec_data in data["sections"].items()
        }
        return obj

    # ── Markdown 输出 ─────────────────────────────────────────

    def _section_to_markdown(self, section_id: str, md_lines: list[str]):
        """递归输出单个章节的 markdown"""
        sec = self.sections[section_id]

        prefix = '#' * sec.level
        md_lines.append(f"\n{prefix} {sec.title}\n")

        for item in sec.content:
            if item["type"] == "text":
                md_lines.append(f"{item['text']}\n")
            elif item["type"] == "table":
                if item.get("html"):
                    md_lines.append(f"\n{item['html']}\n")
                else:
                    md_lines.append("\n> [表格数据，请查看原图或 HTML]\n")
            elif item["type"] == "image":
                md_lines.append(f"\n> ![图片]({item.get('img_path', 'Image')})\n")
            elif item["type"] == "list":
                md_lines.append(f"- {item['text']}\n")

        for child_id in sec.children:
            self._section_to_markdown(child_id, md_lines)

    def to_markdown(self, output_path: str):
        """按标题层级输出带结构的 Markdown"""
        if not self.sections:
            self.build_tree()

        md_lines = []
        for sid in self.root_children:
            self._section_to_markdown(sid, md_lines)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.writelines(md_lines)
        logger.info("Markdown 已输出: %s", output_path)


# ── 向后兼容：保留旧类名 ────────────────────────────────────
MinerUExtractor = SectionTreeBuilder
