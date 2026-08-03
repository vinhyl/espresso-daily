"""基础 / 常青知识库（私有，不参与建站）。

设计（按用户要求）：
- 每个主题一篇 Markdown，位于 `knowledge/`，是对**多篇权威文章的综合**
  （而非搬运单篇），正文末尾用「## 参考来源」列出该主题涉及的**全部源头**。
- 本模块只被 `score.py` 在解读新闻时调用：把知识库作为背景上下文注入 LLM，
  让 AI 结合新闻做多角度深度整理，并把权威出处传递出来。
- `build.py` 只加载 `content/`，**完全不碰 `knowledge/`**，因此常青库天然不出现在网站上。

检索策略（小而全）：知识库体量不大，且用户要求「最全面」，故默认
`mode = "all"`——每次新闻调用直接注入整库背景（无 embedding / 无向量库 /
无额外服务）。当库增长到需要裁剪时，可切 `mode = "recall"`（按标签/概念高召回），
仍保证不漏掉相关背景。
"""
from __future__ import annotations

import glob
import os
import re

from src.content_loader import parse_frontmatter

# 从「## 参考来源」段提取 Markdown 链接：[- 名称](URL)
_SOURCE_RE = re.compile(r"^\s*[-*]\s*\[(?P<name>[^\]]+)\]\((?P<url>[^)]+)\)", re.M)


def _norm_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [x.strip() for x in str(v).split(",") if x.strip()]


def _extract_sources(body: str) -> list[dict]:
    """取正文「## 参考来源」段之后的全部链接，返回 [{name, url}]。"""
    m = re.search(r"##\s*参考来源\s*\n(.*)$", body, re.S)
    block = m.group(1) if m else ""
    return [
        {"name": x.group("name").strip(), "url": x.group("url").strip()}
        for x in _SOURCE_RE.finditer(block)
    ]


def load_knowledge(cfg: dict) -> list[dict]:
    """读取 knowledge/ 下所有 .md，返回结构化主题列表（按文件名排序）。"""
    kc = cfg.get("knowledge", {})
    kdir = kc.get("dir", "knowledge")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    kpath = os.path.join(root, kdir)
    entries = []
    if not os.path.isdir(kpath):
        return entries
    for p in sorted(glob.glob(os.path.join(kpath, "*.md"))):
        with open(p, encoding="utf-8") as f:
            text = f.read()
        meta, body = parse_frontmatter(text)
        topic = (meta.get("topic") or meta.get("title") or "").strip()
        if not topic:
            continue  # 跳过无主题的杂项文件
        entries.append(
            {
                "topic": topic,
                "title": str(meta.get("title", topic)),
                "tags": _norm_list(meta.get("tags")),
                "concepts": _norm_list(meta.get("concepts")),
                "body": body.strip(),
                "sources": _extract_sources(body),
                "file": os.path.basename(p),
            }
        )
    return entries


def _format_entry(k: dict) -> str:
    src_lines = "\n".join(f"- {s['name']} ({s['url']})" for s in k["sources"])
    src_block = f"\n参考来源：\n{src_lines}" if src_lines else ""
    return f"【主题：{k['topic']}】\n{k['body']}{src_block}"


def build_context(item: dict, knowledge: list[dict], cfg: dict) -> str:
    """拼接供 LLM 使用的背景上下文文本。

    mode = "all"   : 注入整库（小库最全面，默认）。
    mode = "recall": 仅注入与新闻共享标签/概念、或正文命中的主题；若无一命中则退化为全量。
    超过 max_chars 预算则截断。
    """
    kc = cfg.get("knowledge", {})
    mode = kc.get("mode", "all")
    max_chars = int(kc.get("max_chars", 8000))

    item_tags = set(map(str.lower, _norm_list(item.get("tags"))))
    item_text = " ".join(
        str(item.get(k, "")) for k in ("title", "summary")
    ).lower()

    if mode == "all":
        selected = list(knowledge)
    else:
        selected = []
        for k in knowledge:
            keys = set(map(str.lower, k["tags"])) | set(map(str.lower, k["concepts"]))
            if (item_tags & keys) or any(c.lower() in item_text for c in keys):
                selected.append(k)
        if not selected:  # 高召回落空时退化为全量，保证最全面
            selected = list(knowledge)

    text = "\n\n---\n\n".join(_format_entry(k) for k in selected)
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n…（背景上下文已截断）"
    return text
