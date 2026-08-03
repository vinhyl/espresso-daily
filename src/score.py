"""LLM 质量评估 + 动态自动打标签 + 分级内容处理；无 API 时走规则回退。

设计（按用户要求）：
- 不再使用固定的 theory/technique/product 三分类。
- 由 LLM 为每条内容生成 2-5 个**开放、具体**的主题标签
  （如 "9-bar"、"水温"、"研磨度"、"布粉wdt"、"预浸泡"、"咖啡机"、"磨豆机"、
   "粉碗"、"新手"、"进阶"、"评测"、"对比" 等），标签词表随内容动态生长。
- 网站不分子板块，标签仅作为**可筛选标签**存在；标签由构建期从全量内容
  汇总出词频索引，前端动态渲染筛选 chips。
- 无 LLM 时，按关键词词典回退生成动态标签。

分级内容处理（两阶段，见 config [llm]）：
- **阶段一（轻量评估，不注入知识库）**：输出 tags / summary / score / kind。
- **阶段二（仅 kind=deepdive 的内容）**：注入基础/常青知识库生成「深度解读」。
- kind 四值：
  - `as-is`     ：中文精炼原文，直接输出，不做摘要/改写；
  - `translate` ：英文等非中文精炼原文，翻译成中文输出，不压缩不精炼；
  - `summary`   ：原文冗长/信息密度低，输出精炼中文摘要；
  - `deepdive`  ：原理性强/反常识/信息密度高，输出中文摘要并额外生成深度解读。
- 无 LLM 时规则回退：不产出深度解读，kind 固定为 summary。
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

# 规则回退用的「关键词 -> 动态标签」词典（比固定三分类更细、更具体）。
# 一条内容命中的关键词会映射为对应标签；可命中多个。
TAG_KEYWORDS: dict[str, list[str]] = {
    "9-bar": ["9bar", "9 bar", "九巴", "bar 压力", "水泵压力", "水压"],
    "水温": ["水温", "温度", "temperature", "thermoblock", "锅炉"],
    "研磨度": ["研磨", "研磨度", "粒径", "grind", "刀盘", "burr", "粗细"],
    "布粉wdt": ["布粉", "wdt", "分布针", " Weiss ", "落粉"],
    "填压": ["填压", "tamp", "tamper", "粉锤", "压粉"],
    "预浸泡": ["预浸泡", "preinfusion", "pre-infusion", "预浸润", "低压"],
    "通道效应": ["通道", "channel", "channeling", "萃取不均", "喷溅"],
    "萃取率tds": ["萃取率", "tds", "浓度", "extraction", "金杯", "溶解度"],
    "粉水比": ["粉量", "液重", "粉水比", "ratio", "dose", "yield", "投粉量"],
    "奶泡": ["奶泡", "打奶", "steam", "拉花", "latte art", "蒸汽"],
    "调参dialin": ["调参", "dial", "dial-in", "调试", "校准", "配方"],
    "咖啡机": ["咖啡机", "espresso machine", "machine", "la marzocco", "lelit",
                "rocket", "profitec", "e61", "双锅炉", "单锅炉", "冲煮头"],
    "磨豆机": ["磨豆机", "grinder", "niche", "df64", "mazzer", "eureka", "手磨", "电动磨"],
    "粉碗": ["粉碗", "basket", "ims", "vst", "粉碗", "无底", "bottomless"],
    "秤": ["秤", "scale", "计时", "电子秤"],
    "辅助器具": ["量粉器", "布粉器", "漏斗", "接粉环", "辅助器具", "配件"],
    "新手": ["新手", "入门", "beginner", "基础", "第一次", "如何开始"],
    "进阶": ["进阶", "高级", "advanced", "竞赛", "职业", "深度"],
    "评测": ["评测", "review", "测评", "上手", "体验", "开箱"],
    "对比": ["对比", "comparison", "横评", "pk", "选哪个", "区别"],
    "意式基础": ["espresso", "意式浓缩", "浓缩", "基本原理", "是什么", "入门知识"],
    "冷萃/特调": ["冷萃", "特调", "创意", "dirty", "americano"],
}

# 回退兜底标签（当关键词完全未命中时使用，保证每条至少有标签）
DEFAULT_FALLBACK_TAG = "意式基础"

# kind 合法取值
KINDS = ("as-is", "translate", "summary", "deepdive")

# 「每日总标题」长度阈值（软/硬两级，可在 config [llm] 覆盖）：
# - 软阈值：生成结果超过则触发一次 LLM 压缩重试（保留模型已做的信息选择）；
# - 硬阈值：压缩后仍超过则丢弃，回退当日最高分条目标题。
HEADLINE_SOFT_CHARS = 60
HEADLINE_MAX_CHARS = 100


def _norm_kind(k: str) -> str:
    k = (k or "").strip().lower()
    return k if k in KINDS else "summary"


@dataclass
class Judgment:
    tags: list[str]
    summary: str
    score: int
    kind: str = "summary"  # as-is | translate | summary | deepdive
    deepdive: str = ""  # 「深度解读」：仅 kind=deepdive 时由阶段二生成
    references: list = None  # 深度解读引用的权威源：[(title, url), ...]，仅深度解读使用

    def to_markdown(self, item: dict) -> str:
        tags = ", ".join(self.tags)
        lines = [
            "---",
            f"date: {item['date']}",
            f"tags: {tags}",
            f"title: {item['title']}",
            f"score: {self.score}",
            f"kind: {self.kind}",
        ]
        if item.get("source"):
            lines.append(f"source: {item['source']}")
        if item.get("source_url"):
            lines.append(f"source_url: {item['source_url']}")
        if item.get("author"):
            lines.append(f"author: {item['author']}")
        if item.get("lang"):
            lines.append(f"lang: {item['lang']}")
        # 参考来源：仅深度解读有，挂在「深度解读」区块；格式 "标题|url" 逗号列表
        if self.references:
            ref_items = ", ".join(f'"{t}|{u}"' for t, u in self.references)
            lines.append(f"references: [{ref_items}]")
        lines.append("---")
        lines.append("")
        lines.append(self.summary)
        if self.deepdive:
            lines.append("")
            lines.append("## 深度解读")
            lines.append("")
            lines.append(self.deepdive)
        return "\n".join(lines)


def _norm_tag(t: str) -> str:
    t = t.strip().strip("#").strip()
    # 统一小写英文部分，中文保留
    return t


def _fallback(item: dict, hint: str) -> Judgment:
    text = " ".join([
        item.get("title", ""),
        item.get("summary", ""), " ".join(item.get("tags", [])),
    ]).lower()
    tags: set[str] = set()
    for tag, kws in TAG_KEYWORDS.items():
        if any(kw.lower() in text for kw in kws):
            tags.add(tag)
    if not tags:
        tags.add(DEFAULT_FALLBACK_TAG)
    # 规则回退容易命中过多关键词，限制最多 5 个，保持标签云清爽
    tags = sorted(tags)[:5]
    score = 75 if len(tags) > 1 else 65
    summary = item.get("summary") or item.get("title", "")
    # 无 LLM 时无法做翻译/摘要/深度整理，kind 固定 summary（正文取抓取摘要），
    # deepdive 留空（前端不渲染该区块）
    return Judgment(tags=tags, summary=summary, score=score, kind="summary", deepdive="", references=None)


def _llm_client(cfg: dict):
    """返回 (api_key, base, model, temperature) 或 None（未配置/缺少 key）。"""
    llm = cfg.get("llm", {})
    api_key = os.getenv(llm.get("api_key_env", "ESPRESSO_LLM_API_KEY"), "")
    if not api_key:
        return None
    base = llm.get("base_url", "https://api.deepseek.com/v1").rstrip("/")
    return (api_key, base, llm.get("model", "deepseek-chat"), llm.get("temperature", 0.2))


def _chat_json(api_key: str, base: str, model: str, temperature: float, prompt: str) -> dict | None:
    """调用 OpenAI 兼容 chat/completions，解析 JSON 输出；失败返回 None。"""
    try:
        import httpx
    except ImportError:
        return None
    try:
        resp = httpx.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "temperature": temperature,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        content = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.I | re.M).strip()
        return json.loads(content)
    except Exception as e:  # 任何失败都回退
        print(f"[score] LLM 调用失败，回退规则：{e}")
        return None


def _call_llm_meta(cfg: dict, item: dict, hint: str) -> Judgment | None:
    """阶段一：轻量评估（不注入知识库），输出 tags / summary / score / kind。"""
    client = _llm_client(cfg)
    if client is None:
        return None
    api_key, base, model, temperature = client

    prompt = (
        "你是意式浓缩咖啡资讯的资深编辑。面对一条新闻/资讯，先判断它的「处理方式」(kind)，再输出评估。\n\n"
        "【处理方式 kind 四选一】\n"
        "1. as-is：原文已足够精炼、信息完整、可直接面向读者，且原文为中文——直接原样输出，不做摘要、不改写。\n"
        "2. translate：原文已足够精炼、信息完整，但为英文等非中文——翻译成中文原样输出，"
        "保持原文信息量与结构，不压缩、不精炼。\n"
        "3. summary：原文冗长、结构松散或信息密度低，需要提炼——输出精炼的中文摘要。\n"
        "4. deepdive：内容原理性强、反常识、有争议或信息密度极高，值得结合知识库深度展开——"
        "先输出精炼的中文摘要。\n"
        "【标签要求】\n"
        "1. 不使用固定的 theory/technique/product 这种大类，而是用更具体的小主题，\n"
        "   例如：9-bar、水温、研磨度、布粉wdt、填压、预浸泡、通道效应、萃取率tds、\n"
        "   粉水比、奶泡、调参dialin、咖啡机、磨豆机、粉碗、秤、新手、进阶、评测、对比、意式基础。\n"
        "2. 返回 2-5 个标签，可中可英，尽量精炼（一个标签通常 2-6 个字/词）。\n"
        "3. 标签应反映内容真正讲的知识点/器具/人群，而不是泛泛而谈。\n\n"
        f"【来源分类提示（仅供参考，不要直接当标签）】{hint}\n\n"
        f"标题：{item.get('title','')}\n"
        f"正文/摘要：{item.get('summary','')}\n\n"
        "【输出要求】\n"
        "1. tags：2-5 个具体主题标签（同上）。\n"
        "2. summary：按 kind 说明**处理后作为正文**的内容——as-is=中文原文；"
        "translate=中文翻译原文；summary/deepdive=精炼中文摘要。\n"
        "3. kind：as-is / translate / summary / deepdive 四选一，严格小写。\n"
        "4. score：0-100 质量分（信息价值与可读性）。\n\n"
        '只输出 JSON，格式：{"tags":["标签1","标签2"],"summary":"处理后正文",'
        '"kind":"summary","score":0-100}'
    )
    data = _chat_json(api_key, base, model, temperature, prompt)
    if data is None:
        return None

    tags = [_norm_tag(t) for t in data.get("tags", []) if _norm_tag(t)]
    tags = sorted(set(tags))[:5]
    if not tags:
        tags = [DEFAULT_FALLBACK_TAG]
    return Judgment(
        tags=tags,
        summary=data.get("summary", item.get("summary", "")),
        score=int(data.get("score", 70)),
        kind=_norm_kind(data.get("kind")),
        deepdive="",
        references=None,
    )


def _call_llm_deepdive(cfg: dict, item: dict, hint: str, knowledge_ctx: str):
    """阶段二：仅 kind=deepdive 时调用，注入知识库生成深度解读。

    返回 (deepdive_markdown, references)，references 为 [(title, url), ...]
    （深度解读实际引用的权威源，用于区块末尾的「参考来源」）。失败返回 ("", [])。
    """
    client = _llm_client(cfg)
    if client is None:
        return "", []
    api_key, base, model, temperature = client

    prompt = (
        "你是意式浓缩咖啡资讯的资深编辑。下面这条新闻已被判定为「值得深度解读」。\n"
        "请结合下方的「基础 / 常青知识库」，生成一段「深度解读」Markdown 正文，\n"
        "帮助读者从更多角度理解这件事。\n\n"
        "【要求】\n"
        "1. 不要简单复述新闻（新闻摘要已单独给出），而是结合知识库做**多角度深度整理**。\n"
        "2. 可从原理、操作、器具、横向对比、常见误区等角度展开。\n"
        "3. 涉及某个知识点时**注明其权威来源**（如「据 Barista Hustle…」或附上该来源链接）。\n"
        "4. 可用小标题/列表；篇幅适中，信息密度优先。\n"
        "5. 在 JSON 中额外返回 `references`：一个数组，列出你在解读中**实际引用**到的权威来源，\n"
        "   每个元素为 {\"title\":\"来源名\",\"url\":\"https://...\"}$；只列真正引用到的，\n"
        "   不要列未提及的来源；与新闻原始出处相同的来源也不要重复列入。\n\n"
        f"标题：{item.get('title','')}\n"
        f"新闻摘要：{item.get('summary','')}\n\n"
        "【基础 / 常青知识库】（权威综合，仅供解读时参考；引用其中知识点时注明原始来源）\n"
        f"{knowledge_ctx}\n\n"
        '只输出 JSON，格式：{"deepdive":"Markdown 深度解读正文","references":'
        '[{"title":"来源名","url":"https://..."}]}'
    )
    data = _chat_json(api_key, base, model, temperature, prompt)
    if data is None:
        return "", []
    dive = str(data.get("deepdive", "") or "").strip()
    refs_raw = data.get("references") or []
    references = []
    for r in refs_raw:
        if isinstance(r, dict) and r.get("url"):
            references.append((str(r.get("title", "")).strip(), str(r.get("url")).strip()))
    return dive, references


def judge(item: dict, cfg: dict, hint: str = "mixed", knowledge_ctx: str = "") -> Judgment:
    """对一条内容做两阶段评估（LLM 优先，失败回退规则）。

    - 阶段一：轻量评估（tags/summary/score/kind），不注入知识库；
    - 阶段二：仅 kind=deepdive 时注入知识库生成深度解读（受 deepdive_enabled 控制）。
    - 无 LLM 时回退规则：不产出 deepdive，kind 固定为 summary。
    """
    llm = cfg.get("llm", {})
    if llm.get("enabled"):
        j = _call_llm_meta(cfg, item, hint)
        if j is not None:
            if (
                j.kind == "deepdive"
                and llm.get("deepdive_enabled", True)
                and knowledge_ctx.strip()
            ):
                dive, refs = _call_llm_deepdive(cfg, item, hint, knowledge_ctx)
                j.deepdive = dive
                j.references = refs
                if not dive:
                    print("[score] 阶段二深度解读失败，降级为仅摘要")
            return j
    return _fallback(item, hint)


def _headline_prompt(day_items: list[dict]) -> str:
    """生成「每日总标题」prompt：当天全部条目按 score 降序排列。

    材料用抓取原始 title/summary（空摘要回退 LLM 处理后正文前 200 字），
    不额外注入知识库——总标题只需概括当天资讯，不需要深度解读。
    含预防措施：字数自检指令 + few-shot 正/反例 + 「综合最多 2 条」压缩动机。
    """
    ranked = sorted(day_items, key=lambda it: it.get("score", 0), reverse=True)
    listing = []
    for i, it in enumerate(ranked, 1):
        title = (it.get("title") or "").strip()
        source = (it.get("source") or "").strip()
        score = it.get("score", 0)
        summary = (it.get("summary") or "").strip()
        if not summary:
            summary = ((it.get("processed_summary") or "")[:200]).strip()
        listing.append(
            f"{i}. 【{score} 分 | {source}】{title}"
            + (f"\n   摘要：{summary[:300]}" if summary else "")
        )
    items_text = "\n".join(listing)
    return (
        "你是意式浓缩咖啡资讯的资深编辑。请为**当天整份日报**拟一个「总标题」(headline)，"
        "它将作为这条日报在归档列表和首页「近期日报」卡片上显示的标题。\n\n"
        "【总标题要求】\n"
        "1. 是对当天资讯的概括性提炼：可以聚焦当天最重大/最值得读的一条资讯，"
        "也可以综合**最多 2 条**相关资讯概括成一句标题（概括越多越容易冗长）。\n"
        "2. 不是简单照搬某条条目标题，而是用编辑眼光重新概括。\n"
        "3. 建议 15-40 字，信息明确、有吸引力，但不夸张、不标题党。\n"
        "4. 输出前在心里默数一遍字数：若超过 40 字，先精简到 40 字以内再输出。\n"
        "5. **不要使用「今日速览」「每日简报」之类的固定前缀**——总标题是纯概括文本，"
        "前缀由界面负责展示。\n\n"
        "【示例】\n"
        "✓ 正例（22 字）：「9 bar 水压黄金标准，通道效应与无底手柄诊断」\n"
        "✗ 反例（66 字，过长）：「今日意式浓缩咖啡资讯丰富，涵盖水压水温研磨度原理"
        "以及多款家用咖啡机评测与深度解读等多个方向值得关注」\n\n"
        f"【今日资讯清单】（按评分降序）\n{items_text}\n\n"
        '【输出要求】只输出 JSON，格式：{"headline":"当天日报的概括性总标题"}'
    )


def _compress_headline(api_key: str, base: str, model: str, temperature: float, headline: str) -> str:
    """把超软阈值的 headline 压缩到建议长度，保留核心信息；失败返回空串。"""
    prompt = (
        "你是意式浓缩咖啡资讯的资深编辑。下面这条日报标题**太长了**，"
        "请压缩到 40 字以内，保留最核心的信息与编辑重点，不改变原意。\n\n"
        f"原标题：{headline}\n\n"
        '只输出 JSON，格式：{"headline":"压缩后的标题"}'
    )
    data = _chat_json(api_key, base, model, temperature, prompt)
    if data is None:
        return ""
    return str(data.get("headline", "") or "").strip()


def call_llm_headline(cfg: dict, day_items: list[dict]) -> str:
    """为当天全部条目生成「每日总标题」（预防 + 软硬双阈值）。

    流程：LLM 生成 → 超过软阈值则压缩重试一次（保留模型已做的信息选择）→
    压缩后仍超过硬阈值才丢弃返回空串（调用方回退当日最高分条目标题）。
    是否调用由调用方（pipeline）依据 llm.enabled / headline_enabled 控制。
    """
    if not day_items:
        return ""
    client = _llm_client(cfg)
    if client is None:
        return ""
    api_key, base, model, temperature = client
    llm = cfg.get("llm", {})
    soft = int(llm.get("headline_soft_chars", HEADLINE_SOFT_CHARS))
    hard = int(llm.get("headline_max_chars", HEADLINE_MAX_CHARS))

    data = _chat_json(api_key, base, model, temperature, _headline_prompt(day_items))
    if data is None:
        return ""
    headline = str(data.get("headline", "") or "").strip()
    if len(headline) > soft:
        print(f"[score] headline {len(headline)} 字超过软阈值 {soft}，压缩重试…")
        compressed = _compress_headline(api_key, base, model, temperature, headline)
        if compressed:
            headline = compressed
    if len(headline) > hard:
        print(f"[score] headline 仍超硬阈值 {hard}（{len(headline)} 字），丢弃回退")
        return ""
    return headline
