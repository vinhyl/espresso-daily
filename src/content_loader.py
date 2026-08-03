"""内容加载与配置读取。

- 解析 content/*.md（YAML 风格 frontmatter + Markdown 正文）
- 渲染正文为 HTML（供网站展示）
- 读取 config.toml（Python 3.11+ 内置 tomllib）
"""
from __future__ import annotations

import glob
import os
import re
import tomllib
from collections import OrderedDict

import markdown

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

def load_config(path: str = "config.toml") -> dict:
    """读取配置文件；不存在时回退到示例文件。"""
    if not os.path.exists(path):
        path = "config.example.toml"
    with open(path, "rb") as f:
        return tomllib.load(f)


def get_categories(cfg: dict) -> dict:
    """返回分类定义；仅用于向后兼容/可选展示，主筛选已改为动态标签。"""
    return cfg.get("categories", {})


def build_tag_index(entries):
    """汇总全量内容的标签词频，返回 [{name, count}]（按频次降序、再按名称）。"""
    from collections import Counter
    c = Counter()
    for e in entries:
        for t in e.get("tags", []):
            c[t] += 1
    ranked = sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"name": name, "count": cnt} for name, cnt in ranked]


# ---------------------------------------------------------------------------
# frontmatter 解析（轻量，无外部 YAML 依赖）
# ---------------------------------------------------------------------------

def _split_list(v: str):
    v = v.strip()
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        v = inner
    return [x.strip().strip('"').strip("'") for x in v.split(",") if x.strip()]


def _norm_url(u: str) -> str:
    """归一化 URL 用于去重比较：去协议、去 www.、去末尾斜杠、转小写。"""
    u = (u or "").strip().lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    return u.rstrip("/")


def _parse_value(key: str, v: str):
    v = v.strip()
    if key in ("tags", "category"):
        return _split_list(v)
    if v.startswith("[") and v.endswith("]"):
        return _split_list(v)
    return v.strip('"').strip("'")


def parse_frontmatter(text: str):
    """返回 (meta: dict, body: str)。无 frontmatter 时返回 ({}, text)。"""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            header, body = parts[1], parts[2].lstrip("\n")
            meta: dict = {}
            for line in header.splitlines():
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                if ":" in line:
                    k, _, v = line.partition(":")
                    meta[k.strip()] = _parse_value(k.strip(), v)
            return meta, body
    return {}, text


# ---------------------------------------------------------------------------
# 条目加载
# ---------------------------------------------------------------------------

def _slugify(text: str, n: int) -> str:
    return f"e{n}"


def load_entries(content_dir: str):
    """读取 content_dir 下所有 .md，返回结构化条目列表（按日期倒序）。"""
    entries = []
    paths = sorted(glob.glob(os.path.join(content_dir, "*.md")))
    for path in paths:
        fn = os.path.basename(path)
        if fn.endswith("-00.md"):
            continue  # 「每日总标题」sidecar，不参与条目加载/统计
        with open(path, encoding="utf-8") as f:
            text = f.read()
        meta, body = parse_frontmatter(text)
        if meta.get("kind") == "headline":
            continue  # 双保险：显式 kind 标记也跳过
        if not meta.get("date") or not meta.get("title"):
            continue  # 跳过无日期/标题的文件（如 README）
        date = str(meta["date"])
        # 动态标签优先；旧文件的 category 作为回退，最终统一进 tags
        tags = meta.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]
        if not tags:
            cat = meta.get("category", [])
            if isinstance(cat, str):
                cat = [cat]
            tags = list(cat)
        category = list(tags)  # 保留字段以便兼容旧模板引用

        # 编辑评分（pipeline 落盘时写入；演示/缺省为 0），用于首页「今日精选」排序与统计
        try:
            score = int(meta.get("score", 0))
        except (TypeError, ValueError):
            score = 0

        # 「参考来源」：仅深度解读使用，frontmatter 形如
        #   references: ["Barista Hustle|https://...", "Scott Rao|https://..."]
        # 或逗号字符串 "标题|url, 标题|url"。与 source_url 去重，避免重复链接。
        refs_raw = meta.get("references", [])
        if isinstance(refs_raw, str):
            refs_raw = [r for r in refs_raw.split(",") if r.strip()]
        references = []
        src_norm = _norm_url(str(meta.get("source_url", "")))
        for r in refs_raw:
            r = str(r).strip().strip('"').strip("'")
            if not r:
                continue
            if "|" in r:
                title, url = r.split("|", 1)
                title, url = title.strip(), url.strip()
            else:
                title, url = "", r.strip()
            if not url or _norm_url(url) == src_norm:
                continue  # 跳过空链接 / 与来源重复的链接
            references.append({"title": title, "url": url})

        # 拆分「深度解读」区块（由流水线结合常青知识库生成），与正文分离渲染。
        # 注意：拆出时**去掉**「## 深度解读」标题行本身——标题由模板的
        # deepdive-label 统一渲染，避免「标签+正文标题」两处重复。
        DIVE_MARK = "## 深度解读"
        if DIVE_MARK in body:
            main_body, dive_body = body.split(DIVE_MARK, 1)
            dive_body = dive_body.lstrip("\n")
        else:
            main_body, dive_body = body, ""

        body_html = markdown.markdown(
            main_body, extensions=["extra", "sane_lists"]
        )
        body_text = re.sub(r"<[^>]+>", "", body_html)
        deepdive_html = (
            markdown.markdown(dive_body, extensions=["extra", "sane_lists"])
            if dive_body else ""
        )

        entries.append(
            {
                "date": date,
                "category": category,
                "title": str(meta.get("title", "")),
                "source": str(meta.get("source", "")),
                "source_url": str(meta.get("source_url", "")),
                "references": references,
                "tags": tags,
                "author": str(meta.get("author", "")),
                "lang": str(meta.get("lang", "")),
                "score": score,
                "body_html": body_html,
                "body_text": body_text,
                "deepdive_html": deepdive_html,
                "file": os.path.basename(path),
            }
        )

    # 按日期倒序，同日按标题
    entries.sort(key=lambda e: (e["date"], e["title"]), reverse=True)
    for i, e in enumerate(entries):
        e["slug"] = _slugify(e["title"], i)
    return entries


# ---------------------------------------------------------------------------
# 每日总标题（headline）sidecar
# ---------------------------------------------------------------------------

def load_day_headlines(content_dir: str) -> dict:
    """读取「每日总标题」sidecar（content/{date}-00.md），返回 {date: headline}。

    - 仅采信 frontmatter 带 `kind: headline` 标记的文件；
    - 取值 headline 字段优先、回退 title（兼容人工手改任一处）。
    """
    headlines: dict = {}
    paths = sorted(glob.glob(os.path.join(content_dir, "*-00.md")))
    for path in paths:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        meta, _ = parse_frontmatter(text)
        if meta.get("kind") != "headline":
            continue
        date = str(meta.get("date", ""))
        if not date:
            continue
        headline = str(meta.get("headline") or meta.get("title") or "").strip()
        if headline:
            headlines[date] = headline
    return headlines


# ---------------------------------------------------------------------------
# 归档（按月份分组）
# ---------------------------------------------------------------------------

def build_months(entries):
    months: "OrderedDict[str, list]" = OrderedDict()
    for e in entries:  # 已倒序
        ym = e["date"][:7]
        months.setdefault(ym, []).append(e)
    result = []
    for ym, es in months.items():
        result.append(
            {
                "label": ym,
                "count": len(es),
                "days": [{"date": e["date"], "headline": e["title"]} for e in es],
            }
        )
    return result


def filter_by_date(entries, date: str):
    return [e for e in entries if e["date"] == date]


def filter_by_category(entries, cat: str):
    return [e for e in entries if cat in e["category"]]


def filter_by_tag(entries, tag: str):
    return [e for e in entries if tag in e.get("tags", [])]
