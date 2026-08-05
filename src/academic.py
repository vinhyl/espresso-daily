"""每周学术雷达（阶段三）。

独立于每日 RSS 管线：由 weekly.yml 周级 CI 触发 `python -m src.academic [--date YYYY-MM-DD]`。

流程：
  1. 抓学术源（fetch.fetch_academic：OpenAlex + Crossref，严格 AND 检索 + 排除词）；
  2. 为每条论文建「研究卡」（固定字段，LLM 优先，无 LLM 规则回退）；
  3. 写研究卡到 research/<date>-<slug>.md；
  4. 生成知识库补丁提案 knowledge/patches/<date>-<slug>.json（提案 + 可触发应用）；
  5. 写本周周报 research/weekly-<date>.md + 索引 research/latest.md；
  6. 输出本周抽检清单 reports/research_spotcheck_<date>.md（人工抽检 10 条）。

研究卡固定字段（对接验收「研究卡固定字段」）：
  研究对象 subject / 实验条件 conditions / 核心发现 finding /
  实际影响 implication / 不能推出 not_claim / 证据等级 evidence_level / DOI。

知识库补丁机制（对接验收「知识库补丁可触发」）：
  - 每条研究卡产出一个补丁提案 JSON（含建议并入的知识库主题 kb_topic）；
  - `python -m src.academic apply --patch knowledge/patches/xxx.json` 可触发应用：
    若 knowledge/<topic>.md 已存在则追加「## 补充（日期）」段，否则新建综合条目。
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import fetch as fetch_mod  # noqa: E402
from src import score as score_mod  # noqa: E402
from src.content_loader import load_config  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESEARCH_DIR = os.path.join(ROOT, "research")
PATCH_DIR = os.path.join(ROOT, "knowledge", "patches")
REPORTS_DIR = fetch_mod.REPORTS_DIR

# 若 config 未配置任何 academic 源，周级 CI 仍要稳定产出：用这个默认检索式
DEFAULT_ACADEMIC_SOURCE = {
    "name": "Espresso Research (default)",
    "type": "academic",
    "enabled": True,
    "category_hint": "research",
    "lang": "en",
    "academic_must": ["espresso", "extraction"],
    "academic_exclude": ["tea", "pourover", "pour over", "cold brew", "caffeine health",
                          "decaf", "sensory", "consumer"],
    "academic_filters": "from_publication_date:2015-01-01",
    "max_per_source": 8,
}

# 研究卡 kb_topic → 既有知识库 slug 映射，避免补丁落到平行新建文件造成主题碎片化。
# key 为 LLM/规则回退可能给出的主题词（小写包含匹配），value 为 knowledge/ 下的文件名（去后缀）。
KB_TOPIC_TO_SLUG = {
    "萃取": "extraction-rate-tds", "萃取率": "extraction-rate-tds", "tds": "extraction-rate-tds",
    "研磨": "grind", "粒径": "grind", "刀盘": "grind",
    "粉量": "dose-ratio", "粉水比": "dose-ratio", "ratio": "dose-ratio", "dose": "dose-ratio",
    "水温": "temperature", "温度": "temperature",
    "预浸泡": "preinfusion", "pre-infusion": "preinfusion",
    "布粉": "distribution", "distribution": "distribution",
    "通道": "channeling", "channeling": "channeling",
    "填压": "tamping", "tamping": "tamping",
    "压力": "9bar", "9bar": "9bar", "bar": "9bar",
}


def _slug(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", s)
    return re.sub(r"-+", "-", s).strip("-")[:60] or "paper"


def _first_sentences(text: str, n: int = 2) -> str:
    text = (text or "").strip()
    # 中英文句子切分
    parts = re.split(r"(?<=[。.!?])\s*", text)
    return " ".join(p for p in parts[:n] if p.strip())


def _build_card_llm(item: dict, cfg: dict) -> dict | None:
    """用 LLM 从摘要抽取研究卡固定字段。失败返回 None。"""
    client = score_mod._llm_client(cfg)
    if client is None:
        return None
    api_key, base, model, temperature = client
    abstract = item.get("summary", "")
    prompt = (
        "你是意式浓缩咖啡领域的科研编辑。下面是一篇学术论文的标题与摘要，"
        "请抽取为结构化的「研究卡」，严格输出 JSON。\n\n"
        "【字段说明】\n"
        "- title：简洁中文标题（保留关键专名如机型/方法/物质，技术词用中文）。\n"
        "- tags：2-4 个具体主题标签（如 萃取率、粉水比、粒径、预浸泡、通道效应）。\n"
        "- subject：研究对象——一句话说清这篇论文研究了什么（谁/什么/在何种条件下）。\n"
        "- conditions：实验条件——样本量、方法、器具/参数、对照设置（摘要里有的才写）。\n"
        "- finding：核心发现——最关键的结果/结论（用数据说话，摘要里有的数值照写）。\n"
        "- implication：实际影响——对家庭/商用意式萃取实践意味着什么，可操作吗。\n"
        "- not_claim：不能推出——摘要未支持、容易被过度解读的结论（诚实标注局限）。\n"
        "- evidence_level：从 {同行评审, 预印本, 综述, 其他} 四选一。\n"
        "- kb_topic：这篇论文最该并入知识库的哪个主题（如 粉水比 / 萃取率 / 预浸泡），"
        "用一个简短主题词；若与现有主题都不直接对应，给一个你认为合适的主题词。\n\n"
        f"【来源】{item.get('source','')}　【证据等级（接口给）】{item.get('evidence_level','')}\n"
        f"【标题】{item.get('title','')}\n"
        f"【摘要】{abstract[:3500]}\n\n"
        '只输出 JSON：{"title":"","tags":[],"subject":"","conditions":"","finding":"",'
        '"implication":"","not_claim":"","evidence_level":"","kb_topic":""}'
    )
    data = score_mod._chat_json(api_key, base, model, temperature, prompt)
    if data is None:
        return None
    return data


def _build_card_rule(item: dict, cfg: dict) -> dict:
    """无 LLM 时的研究卡规则回退：摘要启发式 + 接口证据等级。"""
    abstract = item.get("summary", "")
    return {
        "title": item.get("title", "")[:60],
        "tags": ["研究", "萃取"],
        "subject": _first_sentences(abstract, 1) or item.get("title", ""),
        "conditions": "（规则回退：原文未结构化，请见下方摘要）",
        "finding": "（规则回退：原文未结构化，请见下方摘要）",
        "implication": "（规则回退：详见摘要，结合知识库判断）",
        "not_claim": "（规则回退：无法判断，需人工核对原文）",
        "evidence_level": item.get("evidence_level", "其他"),
        "kb_topic": "萃取",
    }


def build_research_card(item: dict, cfg: dict) -> dict:
    """产出一个研究卡 dict（含固定字段 + 中文摘要）。"""
    card = _build_card_llm(item, cfg)
    if card is None:
        card = _build_card_rule(item, cfg)
    # 规范化
    card["title"] = (card.get("title") or item.get("title", ""))[:80]
    card["tags"] = [str(t).strip() for t in (card.get("tags") or []) if str(t).strip()][:5] or ["研究"]
    card["doi"] = item.get("doi", "")
    card["source"] = item.get("source", "")
    card["source_url"] = item.get("source_url", "")
    card["evidence_level"] = card.get("evidence_level") or item.get("evidence_level", "其他")
    card["kb_topic"] = (card.get("kb_topic") or "萃取").strip()
    card["authors"] = item.get("authors", [])
    card["venue"] = item.get("venue", "")
    # 中文摘要（LLM 给的 finding 已是要点；这里存原始摘要供阅读）
    card["abstract"] = item.get("summary", "")
    return card


def _card_markdown(card: dict, date_str: str) -> str:
    tags = ", ".join(card.get("tags", []))
    lines = [
        "---",
        f"date: {date_str}",
        f"title: {card['title']}",
        f"tags: {tags}",
        f"kind: research",
        f"content_type: research",
        f"doi: {card.get('doi', '')}",
        f"source: {card.get('source', '')}",
        f"source_url: {card.get('source_url', '')}",
        f"evidence_level: {card.get('evidence_level', '')}",
        f"kb_topic: {card.get('kb_topic', '')}",
        "---",
        "",
        f"# {card['title']}",
        "",
        f"- **研究对象**：{card.get('subject', '')}",
        f"- **实验条件**：{card.get('conditions', '')}",
        f"- **核心发现**：{card.get('finding', '')}",
        f"- **实际影响**：{card.get('implication', '')}",
        f"- **不能推出**：{card.get('not_claim', '')}",
        f"- **证据等级**：{card.get('evidence_level', '')}　"
        f"**DOI**：{card.get('doi', '') or '—'}",
        "",
        "## 摘要（原文）",
        "",
        card.get("abstract", "") or "（原文未提供摘要，仅有元数据；建议人工核对 DOI 判断价值）",
        "",
    ]
    return "\n".join(lines)


def make_patch_proposal(card: dict, date_str: str) -> dict:
    """把研究卡转为知识库补丁提案（含建议并入的主题 kb_topic）。"""
    return {
        "date": date_str,
        "topic": card.get("kb_topic", "萃取"),
        "title": card["title"],
        "tags": card.get("tags", []),
        "concepts": [card.get("kb_topic", "萃取")],
        "body": (
            f"{card.get('finding', '')} "
            f"（实验条件：{card.get('conditions', '')}；"
            f"实际影响：{card.get('implication', '')}；"
            f"注意：{card.get('not_claim', '')}）"
        ),
        "sources": [{"name": card["title"], "url": card.get("source_url", "")}]
        if card.get("source_url") else [],
        "evidence_level": card.get("evidence_level", "其他"),
        "doi": card.get("doi", ""),
    }


def apply_patch(patch: dict | str, kb_dir: str | None = None) -> str:
    """应用一个知识库补丁提案：写/更新 knowledge/<topic>.md。

    已存在则追加「## 补充（日期）」段（保留既有综合），不存在则新建综合条目。
    返回被写入/更新的文件路径。
    """
    if isinstance(patch, str):
        with open(patch, encoding="utf-8") as f:
            patch = json.load(f)
    kb_dir = kb_dir or os.path.join(ROOT, "knowledge")
    os.makedirs(kb_dir, exist_ok=True)
    topic = (patch.get("topic") or patch.get("kb_topic") or "萃取").strip()
    # 解析到既有知识库 slug（若存在映射），避免主题碎片化
    slug = None
    low = topic.lower()
    for k, v in KB_TOPIC_TO_SLUG.items():
        if k in low:
            slug = v
            break
    if slug is None:
        slug = _slug(topic)
    path = os.path.join(kb_dir, f"{slug}.md")
    date = patch.get("date", dt.date.today().strftime("%Y-%m-%d"))
    body = patch.get("body", "").strip()
    src_lines = "\n".join(f"- [{s['name']}]({s['url']})" for s in patch.get("sources", [])
                          if s.get("url"))
    src_block = f"\n\n## 参考来源\n\n{src_lines}\n" if src_lines else "\n"

    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            old = f.read()
        addition = f"\n\n## 补充（{date}）\n\n{body}{src_block}"
        with open(path, "w", encoding="utf-8") as f:
            f.write(old.rstrip() + addition)
        print(f"[academic] 补丁已追加到既有知识库条目：{path}")
    else:
        front = (
            "---\n"
            f"topic: {topic}\n"
            f"title: {patch.get('title', topic)}\n"
            f"tags: {', '.join(patch.get('tags', []))}\n"
            f"concepts: {', '.join(patch.get('concepts', []))}\n"
            "---\n\n"
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(front + body + src_block)
        print(f"[academic] 补丁已新建知识库条目：{path}")
    return path


def _spotcheck(cards: list[dict], date_str: str, n: int = 10) -> str:
    """从本周研究卡里抽 n 条，输出人工抽检清单（reports/）。"""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    # 优先抽证据等级较低 / 缺 structured 的，保证抽检有信息量；不够 n 则补足
    ordered = sorted(cards, key=lambda c: (c.get("evidence_level") != "同行评审",
                                            c.get("title", "")))
    picked = ordered[:n]
    lines = [
        f"# 学术雷达人工抽检清单 · {date_str}",
        "",
        f"> 本周共 {len(cards)} 条研究卡，抽检 {len(picked)} 条。请逐条判断是否并入知识库。",
        "",
        "| # | 标题 | 证据等级 | 核心发现（摘要） | 入库？ |",
        "| --- | --- | --- | --- | --- |",
    ]
    for i, c in enumerate(picked, 1):
        finding = (c.get("finding") or c.get("abstract") or "")[:80].replace("\n", " ")
        lines.append(
            f"| {i} | {c.get('title','')[:40]} | {c.get('evidence_level','')} "
            f"| {finding} | ☐ 是 / ☐ 否 |"
        )
    lines.append("")
    path = os.path.join(REPORTS_DIR, f"research_spotcheck_{date_str}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[academic] 抽检清单已写：{path}")
    return path


def run_weekly(cfg: dict | None = None, date_override: str | None = None) -> list[dict]:
    cfg = cfg or load_config()
    date_str = date_override or dt.date.today().strftime("%Y-%m-%d")
    # 学术源：取 config 里 type=academic 的（无论 enabled——学术源专门为周级 CI 服务，
    # 在 config 里通常 enabled=false，避免被每日管线抓进 content/）。没有则用默认检索式。
    academic_sources = [s for s in cfg.get("sources", [])
                         if s.get("type") == "academic"]
    if not academic_sources:
        academic_sources = [DEFAULT_ACADEMIC_SOURCE]
        print("[academic] config 无 academic 源，使用默认检索式")

    failures: list[dict] = []
    raw: list[dict] = []
    for s in academic_sources:
        raw.extend(fetch_mod.fetch_academic(s, s.get("lookback_days", 365),
                                            user_agent=cfg.get("fetch", {}).get("user_agent"),
                                            failures=failures))
    # 跨源去重（按 DOI，空 DOI 按标题）
    seen = set()
    items: list[dict] = []
    for it in raw:
        key = (it.get("doi") or it.get("title") or "").lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(it)
    print(f"[academic] 本周候选论文 {len(items)} 条")

    os.makedirs(RESEARCH_DIR, exist_ok=True)
    os.makedirs(PATCH_DIR, exist_ok=True)
    cards: list[dict] = []
    for it in items:
        card = build_research_card(it, cfg)
        slug = _slug(card["title"]) or _slug(it.get("doi", ""))
        # 避免同日同名覆盖
        base = f"{date_str}-{slug}"
        path = os.path.join(RESEARCH_DIR, f"{base}.md")
        i = 1
        while os.path.exists(path):
            path = os.path.join(RESEARCH_DIR, f"{base}-{i}.md")
            i += 1
        with open(path, "w", encoding="utf-8") as f:
            f.write(_card_markdown(card, date_str))
        # 补丁提案
        patch = make_patch_proposal(card, date_str)
        ppath = os.path.join(PATCH_DIR, f"{os.path.basename(path)[:-3]}.json")
        with open(ppath, "w", encoding="utf-8") as f:
            json.dump(patch, f, ensure_ascii=False, indent=2)
        cards.append(card)

    # 周报 + 索引
    _write_weekly_index(cards, date_str)
    # 抽检清单
    _spotcheck(cards, date_str, n=10)
    # 失败落盘
    fetch_mod.write_failure_report(failures)

    print(f"[academic] 完成：{len(cards)} 张研究卡 → research/，补丁提案 → knowledge/patches/")
    return cards


def _write_weekly_index(cards: list[dict], date_str: str) -> None:
    lines = [
        f"# 学术雷达周报 · {date_str}",
        "",
        f"本周共 {len(cards)} 篇研究卡。详见各 `research/<date>-<slug>.md`。",
        "",
        "| 标题 | 证据等级 | 研究对象 |",
        "| --- | --- | --- |",
    ]
    for c in cards:
        lines.append(f"| {c.get('title','')[:50]} | {c.get('evidence_level','')} "
                     f"| {(c.get('subject','') or '')[:60]} |")
    lines.append("")
    with open(os.path.join(RESEARCH_DIR, f"weekly-{date_str}.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    # latest 指针
    with open(os.path.join(RESEARCH_DIR, "latest.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    import argparse
    ap = argparse.ArgumentParser(description="espresso-daily 每周学术雷达")
    ap.add_argument("--date", default=None, help="覆盖运行日期 YYYY-MM-DD")
    ap.add_argument("cmd", nargs="?", default="run", choices=["run", "apply"],
                    help="run=跑周报（默认）；apply=应用一个知识库补丁提案")
    ap.add_argument("patch", nargs="?", default=None, help="apply 模式的补丁 JSON 路径")
    args = ap.parse_args()
    if args.cmd == "apply":
        if not args.patch:
            print("apply 模式需要一个补丁提案 JSON 路径参数")
            sys.exit(1)
        p = apply_patch(args.patch)
        print(f"已应用补丁：{p}")
    else:
        run_weekly(date_override=args.date)


if __name__ == "__main__":
    main()
