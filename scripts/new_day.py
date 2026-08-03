#!/usr/bin/env python
"""脚手架：新建一日空白条目模板到 content/。

用法:
    python scripts/new_day.py                 # 今天
    python scripts/new_day.py 2026-08-03      # 指定日期
    python scripts/new_day.py --cat theory    # 预设分类（可选）

生成的文件可直接编辑，也可用流水线自动填充。
"""
from __future__ import annotations

import argparse
import datetime as dt
import os

TEMPLATE = """---
date: {date}
category: {cat}
title: 在此填写标题
source: 来源名（可选）
source_url: https://（可选）
tags: 标签1, 标签2
---

在此用 Markdown 写正文：要点、原理、参考链接等。

- 要点一
- 要点二

参考：[链接文字](https://)
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("date", nargs="?", default=dt.datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--cat", default="theory", choices=["theory", "technique", "product"])
    args = ap.parse_args()

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    content_dir = os.path.join(here, "content")
    os.makedirs(content_dir, exist_ok=True)
    path = os.path.join(content_dir, f"{args.date}-untitled.md")
    if os.path.exists(path):
        print(f"已存在：{path}")
        return
    with open(path, "w", encoding="utf-8") as f:
        f.write(TEMPLATE.format(date=args.date, cat=args.cat))
    print(f"已创建模板：{path}")


if __name__ == "__main__":
    main()
