#!/usr/bin/env python
"""脚手架：新建一个「基础 / 常青」主题文件到 knowledge/。

常青库是**私有**的权威综合库（不参与建站），供 AI 在解读新闻时作背景。
每个主题应综合**多篇**权威文章，并在正文末尾用「## 参考来源」列出全部源头。

用法:
    python scripts/new_knowledge.py "9 bar 水压"
    python scripts/new_knowledge.py "通道效应" --slug channeling
"""
from __future__ import annotations

import argparse
import os
import re
import unicodedata

TEMPLATE = """---
topic: {topic}
title: {topic}（权威综合）
tags: 标签1, 标签2
concepts: 概念1, 概念2, 概念3
---

（在此综合多篇权威文章，给出该主题的核心结论、共识与分歧。
不要只搬运单篇，要跨源整合；下文「参考来源」列出你参考过的全部文章。）

- 要点一
- 要点二
- 不同权威的侧重 / 分歧（如有）

## 参考来源
- [来源名1 — 文章标题](https://)
- [来源名2 — 文章标题](https://)
"""


def _slugify(text: str) -> str:
    s = unicodedata.normalize("NFKD", text)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w一-鿿]+", "-", s).strip("-").lower()
    return s or "topic"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("topic", help="主题名，如「9 bar 水压」")
    ap.add_argument("--slug", default="", help="文件名 slug（默认按主题生成）")
    args = ap.parse_args()

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    kdir = os.path.join(here, "knowledge")
    os.makedirs(kdir, exist_ok=True)

    slug = args.slug or _slugify(args.topic)
    path = os.path.join(kdir, f"{slug}.md")
    if os.path.exists(path):
        print(f"已存在：{path}")
        return
    with open(path, "w", encoding="utf-8") as f:
        f.write(TEMPLATE.format(topic=args.topic))
    print(f"已创建常青主题模板：{path}")


if __name__ == "__main__":
    main()
