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

# ---------------------------------------------------------------------------
# content_type（内容性质）× kind（处理方式）—— 两套枚举的对齐（阶段二）
#
# 二者不是竞争关系，而是**正交**的两个维度，故都保留、只做映射，不合并成一套：
#   - content_type：这条内容「是什么」（专家实验 / 独立评测 / 行业消息 / 社区个案 /
#     官方公告 / 学术研究）。决定证据维度打分、卡片上的类型标签。
#   - kind：这条内容「怎么处理」（原样 / 翻译 / 摘要 / 深度解读）。决定正文生成方式。
# 映射只在 LLM 未给出 kind 时兜底，避免重复造词表、也避免前端字段对不上。
# ---------------------------------------------------------------------------
CONTENT_TYPES = (
    "expert_experiment",    # 专家实验/建模（Barista Hustle、Coffee Ad Astra）
    "independent_review",   # 独立测试（非厂商自营的实测评测）
    "news",                 # 行业消息/媒体报道（含品牌教程等中性内容）
    "community_case",       # 社区个案（Reddit 等，有机型/参数/已尝试步骤）
    "announcement",         # 官方公告（新品/规格/固件/召回）
    "research",             # 学术研究（阶段三学术雷达）
)

# 卡片展示用的中文标签
CONTENT_TYPE_LABELS = {
    "expert_experiment": "实验研究",
    "independent_review": "独立测试",
    "news": "行业消息",
    "community_case": "社区验证",
    "announcement": "官方公告",
    "research": "学术研究",
}

# 来源层级（category_hint）→ content_type 的**兜底种子**（LLM 关闭/未返回时用）。
# 注意 tutorial（品牌自营教程，WLL/Clive）在六类里没有精确对应项：它既不是
# independent_review（厂商自营，不独立，标成「独立测试」会误导读者），也不是实验，
# 故归入中性的 news；LLM 初筛可按实际内容改判。
HINT_TO_CONTENT_TYPE = {
    "tech_experiment": "expert_experiment",
    "independent_review": "independent_review",
    "tutorial": "news",
    "industry": "news",
    "community": "community_case",
    "official": "announcement",
    "academic": "research",
}

# content_type → 建议 kind（仅在 LLM 未给出合法 kind 时兜底）
CONTENT_TYPE_TO_KIND = {
    "expert_experiment": "deepdive",
    "research": "deepdive",
    "independent_review": "summary",
    "news": "summary",
    "community_case": "summary",
    "announcement": "translate",
}

# ---------------------------------------------------------------------------
# 六维可解释评分（阶段二）
#
# 刻意**不用「来源分数 × 系数」**：那种做法会让权威但无关的内容自动高分
# （例：Barista Hustle 发一篇滤泡文章也被抬到 80+）。这里来源身份只经由
# 「证据质量」这一维参与打分，另外只影响配额与同分排序。
#
# 2026-08-06 重构：六维满分**按 content_type 差异化**（CONTENT_TYPE_DIM_PROFILES），
# 每种内容类型的维度权重反映「这类内容的实际价值点」；总分恒为 100，min_score 语义不变。
# SCORE_DIMS 仅保留维度顺序与中文标签（落盘/展示用），满分以类型表为准。
# ---------------------------------------------------------------------------
SCORE_DIMS: tuple[tuple[str, str], ...] = (
    ("relevance",     "意式相关性"),
    ("novelty",       "新颖性"),
    ("actionability", "可操作性"),
    ("evidence",      "证据质量"),
    ("params",        "参数具体度"),
    ("timeliness",    "内容有效时间"),   # 2026-08-06 重定义：非「新鲜度」，是内容信息有效期的长度
)
DIM_KEYS: tuple[str, ...] = tuple(k for k, _ in SCORE_DIMS)
DIM_LABELS: dict[str, str] = {k: label for k, label in SCORE_DIMS}

# 各 content_type 的六维满分配置（每行总和 = 100）。
# timeliness = 内容有效时间：原理性/长期恒定有效的内容分值更高（与「新闻新鲜度」相反）。
CONTENT_TYPE_DIM_PROFILES: dict[str, dict[str, int]] = {
    # 行业消息：时效价值大（novelty/timeliness 权重高）；可操作性改为「信息对读者的实用价值」，
    # 不再按操作步骤卡分；参数非必需。
    "news": {"relevance": 30, "novelty": 25, "actionability": 10,
             "evidence": 15, "params": 5, "timeliness": 15},
    # 官方公告：规格参数是核心价值
    "announcement": {"relevance": 25, "novelty": 25, "actionability": 5,
                     "evidence": 15, "params": 20, "timeliness": 10},
    # 专家实验/建模：方法+数据最重要，且常青（有效时间长）
    "expert_experiment": {"relevance": 25, "novelty": 15, "actionability": 10,
                          "evidence": 20, "params": 15, "timeliness": 15},
    # 学术研究：证据质量权重最高、最常青；可操作性不要求
    "research": {"relevance": 20, "novelty": 20, "actionability": 5,
                 "evidence": 25, "params": 15, "timeliness": 15},
    # 独立评测：价值=可照做+参数；评测参考期较长
    "independent_review": {"relevance": 25, "novelty": 10, "actionability": 20,
                           "evidence": 15, "params": 20, "timeliness": 10},
    # 社区个案：evidence 天生低（单人经验）不卡死；参数/可操作性才是价值；故障排查常青
    "community_case": {"relevance": 25, "novelty": 10, "actionability": 20,
                       "evidence": 5, "params": 25, "timeliness": 15},
}

# 兜底：未匹配类型的维度满分（取 news 配置，避免 KeyError）
DEFAULT_DIM_PROFILE: dict[str, int] = CONTENT_TYPE_DIM_PROFILES["news"]


def dim_profile(content_type: str) -> dict[str, int]:
    """返回某 content_type 的六维满分配置；未知类型回退默认。"""
    return CONTENT_TYPE_DIM_PROFILES.get(content_type, DEFAULT_DIM_PROFILE)


def dim_max(content_type: str, key: str) -> int:
    """某类型某维的满分。"""
    return dim_profile(content_type).get(key, 0)

# 证据等级（用于同分排序：证据等级 > 来源多样性 > 事件是否重复）
EVIDENCE_RANK = {
    "research": 5,
    "expert_experiment": 4,
    "independent_review": 3,
    "announcement": 2,
    "news": 2,
    "community_case": 1,
}


def _norm_content_type(t: str, hint: str = "") -> str:
    t = (t or "").strip().lower().replace("-", "_")
    if t in CONTENT_TYPES:
        return t
    return HINT_TO_CONTENT_TYPE.get((hint or "").strip().lower(), "news")


def _norm_dims(raw: dict | None, content_type: str = "") -> dict[str, int]:
    """把 LLM 返回的六维分数按该类型的满分裁剪到合法区间；缺失维度取该维一半分（中性）。"""
    raw = raw if isinstance(raw, dict) else {}
    profile = dim_profile(content_type)
    dims: dict[str, int] = {}
    for key in DIM_KEYS:
        maxv = profile.get(key, 0)
        v = raw.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            try:
                v = float(str(v))
            except (TypeError, ValueError):
                v = maxv / 2  # 缺失/非法：给中性分，不让单维缺失把总分打死
        dims[key] = max(0, min(int(maxv), int(round(float(v)))))
    return dims


def dims_total(dims: dict[str, int]) -> int:
    return sum(dims.get(k, 0) for k in DIM_KEYS)


def format_dims(dims: dict[str, int]) -> str:
    """紧凑单行表示，落 frontmatter：relevance=28|novelty=16|..."""
    return "|".join(f"{k}={dims.get(k, 0)}" for k in DIM_KEYS)


def parse_dims(s: str) -> dict[str, int]:
    """format_dims 的逆操作（质量报告/模板读取用）。"""
    out: dict[str, int] = {}
    for part in (s or "").split("|"):
        if "=" not in part:
            continue
        k, _, v = part.partition("=")
        try:
            out[k.strip()] = int(v)
        except ValueError:
            continue
    return out


def _one_line(s: str, limit: int = 300) -> str:
    """frontmatter 是逐行 `k: v` 解析的，值里不能带换行；顺手截断超长文本。"""
    return re.sub(r"\s+", " ", str(s or "")).strip()[:limit]

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
    title: str = ""  # 中文标题（LLM 生成/翻译；空则回退 item['title']）
    deepdive: str = ""  # 「深度解读」：仅 kind=deepdive 时由阶段二生成
    references: list = None  # 深度解读引用的权威源：[(title, url), ...]，仅深度解读使用
    # ---- 阶段二新增 ----
    content_type: str = "news"       # 内容性质（见 CONTENT_TYPES）
    dims: dict = None                # 六维明细 {relevance: 28, ...}
    why_read: str = ""               # 「为什么值得读」一句话
    related: list = None             # 同题事件折叠的补充来源 [(title, url), ...]
    prescreen_reason: str = ""       # 初筛判定理由（仅进质量报告，不落 frontmatter）
    used_full_text: bool = False     # 是否基于全文精评（质量报告用）

    @property
    def evidence_rank(self) -> int:
        """证据等级（同分排序第一顺位）。"""
        return EVIDENCE_RANK.get(self.content_type, 1)

    def to_markdown(self, item: dict) -> str:
        tags = ", ".join(self.tags)
        # 标题：LLM 生成的中文标题优先，空则回退抓取原文标题
        title = self.title.strip() or item.get("title", "")
        lines = [
            "---",
            f"date: {item['date']}",
            f"tags: {tags}",
            f"title: {title}",
            f"score: {self.score}",
            f"kind: {self.kind}",
            f"content_type: {self.content_type}",
        ]
        if self.dims:
            lines.append(f"score_dims: {format_dims(self.dims)}")
        if self.why_read:
            lines.append(f"why_read: {_one_line(self.why_read, 120)}")
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
        # 同题补充来源（48h 事件聚类折叠所得）。刻意**不复用 references**：
        # references 是「深度解读引用的权威源」，语义不同，混用会破坏既有机制。
        if self.related:
            rel_items = ", ".join(f'"{t}|{u}"' for t, u in self.related)
            lines.append(f"related: [{rel_items}]")
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


# ---------------------------------------------------------------------------
# 初筛（Two-Pass 第一段）与规则回退所用的判据词表
#
# 「意式核心」刻意**不含**裸词 coffee / 咖啡：正是这类泛词让「咖啡渣电脑包」
# 「每天五杯咖啡的研究」之类内容混进日报。必须命中意式特有的器具/工艺/参数词。
# ---------------------------------------------------------------------------
ESPRESSO_CORE_KEYWORDS = [
    "espresso", "意式浓缩", "浓缩咖啡", "portafilter", "手柄", "粉碗", "basket",
    "puck", "粉饼", "tamp", "填压", "压粉", "wdt", "布粉", "distribution",
    "preinfusion", "pre-infusion", "预浸", "channeling", "通道效应", "萃取率",
    "extraction yield", "tds", "refractometer", "折光", "9 bar", "9bar",
    "bar 压力", "pressure profil", "压力曲线", "flow profil", "流量曲线",
    "grinder", "磨豆机", "burr", "刀盘", "grind size", "研磨度", "particle size",
    "粒径", "dose", "投粉", "brew ratio", "粉水比", "yield", "液重",
    "shot", "crema", "油脂", "lever", "拉杆", "e61", "group head", "冲煮头",
    "boiler", "锅炉", "pid", "steam wand", "蒸汽棒", "milk texturing", "打奶",
    "latte art", "拉花", "barista", "咖啡师", "dial in", "dial-in", "调参",
    "espresso machine", "意式咖啡机", "半自动", "超自动", "super auto",
    "backflush", "反冲洗", "descal", "除垢", "puck screen", "分水网",
]

# 明显不该进日报的形态：纯展示/求助/购买咨询/广告/健康营养话题
PRESCREEN_REJECT_PATTERNS = [
    "just got", "finally got", "my new setup", "first machine", "rate my",
    "show off", "help me choose", "recommend me", "should i buy", "which one should",
    "looking for a", "gift for", "coupon", "discount code", "sponsored",
    "giveaway", "sale ends", "black friday deal",
    "健康", "养生", "减肥", "抗氧化", "致癌", "喝几杯", "每天几杯",
]

# 手冲/滤泡等其他冲煮方式的强信号词（2026-08-06 新增）
# 用途：① 注入 LLM 初筛 prompt，帮助模型识别「其他冲煮方式」形态；② 规则初筛命中即拒。
# 只收「强手冲信号」词——意式语境几乎不会出现的词；刻意**避开** brew ratio / 粉水比
# 这类意式与手冲共用的两用词（正是 Brew Ratio Bloat 漏网的原因）。
POUROVER_BREW_KEYWORDS = [
    # 器具 / 方式（英文）
    "pour over", "pour-over", "pourover", "v60", "chemex", "kalita", "aeropress",
    "french press", "cold brew", "drip coffee", "filter coffee",
    "gooseneck", "immersion brew", "batch brew",
    # 器具 / 方式（中文）
    "手冲", "滤泡", "滤纸", "滤杯", "法压", "冷萃", "冰滴", "爱乐压", "挂耳",
    "细口壶", "分享壶", "闷蒸", "bloom",
    # 冲煮赛事 / 场景（赛事必然非意式，强信号）
    "brewers cup", "wbrc", "world brewers cup", "冲煮赛", "滤泡赛",
]

# 新颖性信号
NOVELTY_KEYWORDS = [
    "launch", "release", "released", "introduc", "unveil", "announce", "new ",
    "first ", "debut", "patent", "study", "research", "experiment", "finds",
    "redesign", "upgrade", "next-gen", "measur", "tested", "compar", "result",
    "发布", "新品", "首次", "实验", "研究", "专利", "升级", "改版", "实测",
]

# 可操作性信号
ACTION_KEYWORDS = [
    "how to", "guide", "tutorial", "step", "tips", "fix", "troubleshoot",
    "dial", "recipe", "setting", "adjust", "calibrat", "workflow",
    "maintenance", "clean", "教程", "步骤", "如何", "怎么", "方法", "技巧",
    "调整", "校准", "排查", "保养",
]

# 规则回退时，novelty / actionability 这两维靠关键词只能粗测，
# 给一个中性基线再叠加关键词加成——比一律打 0 更接近事实
# （打 0 会让真内容也跌破 60，导致无 LLM 时日报直接空掉）。
RULE_NEUTRAL_BASELINE = {"novelty": 8, "actionability": 8}

# 参数具体度：带单位的数字（9 bar / 93°C / 18g / 36g / 25s / 1:2 / 250µm）
PARAM_PATTERN = re.compile(
    r"\d+(?:\.\d+)?\s*(?:bar|g\b|gram|ml|s\b|sec|秒|克|°\s*c|℃|°\s*f|µm|um|微米|%|:\s*\d)",
    re.I,
)


def _text_of(item: dict, include_full: bool = True) -> str:
    parts = [item.get("title", ""), item.get("summary", "")]
    if include_full and item.get("full_text"):
        parts.append(item["full_text"][:4000])
    return " ".join(p for p in parts if p).lower()


def _core_hits(text: str) -> list[str]:
    return [k for k in ESPRESSO_CORE_KEYWORDS if k in text]


def _rule_prescreen(item: dict, hint: str) -> dict:
    """无 LLM 时的初筛回退。

    设计取舍：规则回退**只挡明显非意式 / 低质形态**（纯展示、求助选购、广告、
    咖啡健康营养话题），其余一律放行到六维评分阶段，由 min_score 门槛决定去留。
    不在这里自行做「是否意式核心」的硬判定——因为：
      1) 源级关键词预过滤（fetch 层 include_any）已经把泛咖啡内容挡在门外，
         能走到初筛的条目基本是意式相关源里筛过的；
      2) 真正的水/泛内容（咖啡渣周边、每天几杯咖啡研究）即便放行，六维评分也会
         因 relevance→0 / evidence 低而跌破 60（已单测验证），不必在初筛重复拦截；
      3) 若初筛也卡核心词，无 LLM 时日报会直接空掉，违背「宁缺毋滥但要有内容」。
    带 LLM 时走 _llm_prescreen，做更准的语义初筛。
    """
    text = _text_of(item, include_full=False)
    hits = _core_hits(text)
    espresso_core = len(hits) >= 1
    ctype = HINT_TO_CONTENT_TYPE.get(hint, "news")
    for pat in PRESCREEN_REJECT_PATTERNS:
        if pat in text:
            return {"accept": False, "content_type": ctype, "espresso_core": espresso_core,
                    "reason": f"命中排除形态「{pat.strip()}」（纯展示/求助/广告/健康话题）"}
    for pat in POUROVER_BREW_KEYWORDS:
        if pat in text:
            return {"accept": False, "content_type": ctype, "espresso_core": espresso_core,
                    "reason": f"命中手冲/滤泡信号「{pat.strip()}」，非意式冲煮方式"}
    # 未命中排除形态：放行至评分；espresso_core 仅作质量报告信息字段
    reason = (f"命中意式核心词 {len(hits)} 个：{', '.join(hits[:4])}"
              if hits else "源级预过滤已通过，放行至六维评分")
    return {"accept": True, "content_type": ctype, "espresso_core": espresso_core,
            "reason": reason}


def _llm_prescreen(cfg: dict, item: dict, hint: str) -> dict | None:
    """Two-Pass 第一段：只用标题 + RSS 摘要 + 来源身份做判断，**不抓全文**。

    这一段的存在意义就是「便宜」：先淘汰掉不值得花全文抓取与精评成本的内容。

    判定哲学（2026-08-06 重写）：
    初筛是**快速闸门**，不是精读裁决。它只拦截「明显与意式无关」或「明显无信息价值」
    的内容；边界模糊的一律放行，让下一轮精评的六维评分（意式相关性满分 30）+ 
    min_score=60 做最终裁决——宁放过、勿误杀，否则日报会空掉。
    """
    client = _llm_client(cfg)
    if client is None:
        return None
    api_key, base, model, temperature = client
    prompt = (
        "你是意式浓缩咖啡日报的资深编辑，正在做**初筛**（快速闸门：只看标题与摘要，"
        "决定这条要不要进入下一轮精读）。\n\n"
        "【先判意式相关：命中以下任意一类 = 意式相关，不要因标题不含 espresso 字样就拒绝】\n"
        "1. 意式操作/技术直接相关：萃取原理与参数（水压/水温/研磨度/粉水比/萃取率/TDS/压力曲线）、"
        "意式器具（咖啡机/磨豆机/粉碗/手柄/拉杆机/锅炉/蒸汽棒/粉锤）、工艺（填压/布粉/WDT/预浸泡/"
        "通道效应）、配方调参、奶咖操作（打奶/拉花/拿铁/卡布奇诺）。\n"
        "2. 意式生态/行业相关：意式设备品牌的新品发布、商用设备动态、咖啡师教育/赛事/行业活动，"
        "或研究对象是意式饮品/器具的研究（如 espresso、moka pot、意式机萃取）——"
        "即便标题不含 espresso 字样也放行。\n"
        "3. 明确为意式服务：意式浓缩用豆/烘焙（专讲 espresso blend 或意式烘焙），"
        "或意式社区含具体机型+参数+已尝试步骤的可复用讨论。\n\n"
        "【形态检查：命中以下任一明显形态才拒绝（accept=false）】\n"
        "1. 其他冲煮方式专题：手冲/滤泡/法压/冷萃/冰滴/爱乐压等非意式器具与流程。\n"
        "   手冲强信号词供参考（命中多个或语境明显为手冲时优先判拒）：\n"
        f"   {', '.join(POUROVER_BREW_KEYWORDS)}\n"
        "   **注意**：即使来源是技术源（如 Barista Hustle）、或内容含 brew ratio/粉水比等"
        "意式也用的两用词，只要语境是冲煮赛/滤泡器具/手冲流程 → 一律拒绝。\n"
        "2. 泛咖啡健康/营养研究：研究主体是「咖啡」整体的健康效应（每天几杯、抗氧化、肝病、"
        "心血管等），结论不涉及意式萃取或奶咖操作。注意：研究主体是 espresso / moka pot 等"
        "意式饮品本身的 → 放行。\n"
        "3. 种植/产地/农业/供应链：豆种培育、产地风土、虫害、贸易价格、公平贸易（与意式用户可操作无关）。\n"
        "4. 咖啡店商业/空间/人物：店铺开业展示(Build-Outs)、门店空间设计、非技术性人物访谈、品牌营销故事。\n"
        "5. 咖啡周边商品：咖啡渣再利用、咖啡主题周边（电脑包/杯具/服饰等）。\n"
        "6. 纯展示帖：晒机器/晒吧台/晒浓缩/晒拉花，无参数、无结论、无可复用信息。\n"
        "7. 求助/选购咨询帖：无结论的「帮我选哪台」「值得买吗」「推荐一下」。\n"
        "8. 广告/促销/软文/抽奖/优惠码。\n\n"
        "【拿不准时】边界模糊、无法确定是否意式相关 → **放行（accept=true）**，"
        "reason 注明「边界模糊交精评」。初筛宁放过、勿误杀——精评六维评分会把无关内容"
        "打到 60 分以下自然淘汰。\n\n"
        "【content_type 六选一】\n"
        "- expert_experiment：专家做的实验/建模/测量，有方法与数据。\n"
        "- independent_review：**独立第三方**实测评测。厂商/经销商自营内容不算独立，归 news。\n"
        "- news：行业消息、媒体报道、品牌教程等中性内容。\n"
        "- community_case：社区个案，含具体机型/参数/已尝试步骤。\n"
        "- announcement：官方新品/规格/固件/召回公告。\n"
        "- research：学术论文/预印本。\n\n"
        "【espresso_core】这条是否真正围绕意式浓缩展开（true/false）。"
        "意式相关行业动态/研究可判 true；只是顺带提到 espresso 一词的不算。\n\n"
        f"【来源】{item.get('source','')}（来源层级提示：{hint}）\n"
        f"【标题】{item.get('title','')}\n"
        f"【摘要】{(item.get('summary') or '')[:1200]}\n\n"
        '只输出 JSON：{"accept":true/false,"content_type":"news",'
        '"espresso_core":true/false,"reason":"20 字以内的中文判定理由"}'
    )
    data = _chat_json(api_key, base, model, temperature, prompt)
    if data is None:
        return None
    return {
        "accept": bool(data.get("accept", False)),
        "content_type": _norm_content_type(str(data.get("content_type", "")), hint),
        "espresso_core": bool(data.get("espresso_core", False)),
        "reason": _one_line(data.get("reason", ""), 60),
    }


def prescreen(item: dict, cfg: dict, hint: str = "mixed") -> dict:
    """初筛入口：LLM 优先，失败/未启用回退关键词规则。

    返回 {accept, content_type, espresso_core, reason, engine}。
    与 fetch 层的 `_source_prefilter` 串联——那一层是更前置、零成本的源级关键词
    闸门，这一层是带语义判断的便宜 LLM 闸门，两者不冲突。
    """
    if cfg.get("llm", {}).get("enabled"):
        res = _llm_prescreen(cfg, item, hint)
        if res is not None:
            res["engine"] = "llm"
            return res
    res = _rule_prescreen(item, hint)
    res["engine"] = "rule"
    return res


# ---------------------------------------------------------------------------
# 48h 轻量事件聚类（阶段二）
#
# 目的：「同题事件不重复」——同一个新品发布 / 同一篇研究的媒体报道 / 同一个
# 调参讨论，在多家源或 48h 内会被重复收录，聚类后只保留最完整（评分最高）的
# 一条作为主卡，其余折叠进主卡的 `related` 字段（补充来源），不再单独成卡。
#
# 设计取舍：**不引向量库**。只用「显著签名词」做集合交并：
#   - 意式核心词命中（ESPRESSO_CORE_KEYWORDS，但排除最泛的 espresso/意式浓缩）；
#   - 标题里的实体专名（多词大写专有名词，如 Zerno Z1 / La Marzocco）；
#   - 机型/型号代码（如 Micra / DE1 / Z1）。
# 两条内容共享 ≥2 个显著签名词，或共享 ≥1 个实体/型号，即判为同题。
# 这是关键词聚类，零外部依赖、可复现、结果可解释。
# ---------------------------------------------------------------------------

# 聚类时**排除**的泛化 token：只靠它们会把所有「提到 espresso 的」都并到一起
_CLUSTER_GENERIC = {
    "espresso", "意式浓缩", "浓缩咖啡", "espresso machine", "意式咖啡机",
    "半自动", "super auto", "超自动", "barista", "咖啡师", "coffee",
}

_ENTITY_RE = re.compile(r"\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2})\b")
_MODEL_RE = re.compile(r"\b([A-Za-z]{1,3}\d{1,3}(?:[A-Za-z]+)?)\b")
_ENTITY_STOP = {"The", "New", "How", "Why", "This", "That", "What", "When",
                "Best", "Top", "Our", "Your", "Review", "Guide"}


def _topic_signature(item: dict) -> set[str]:
    """提取一条内容的「显著签名词」集合，用于聚类判断。"""
    text = _text_of(item).lower()
    sig: set[str] = set(_core_hits(text)) - _CLUSTER_GENERIC
    title = item.get("title", "")
    # 标题里的实体专名（多词大写）
    for m in _ENTITY_RE.finditer(title):
        parts = m.group(1).split()
        if parts and parts[0] in _ENTITY_STOP:
            parts = parts[1:]
        if not parts:
            continue
        ent = " ".join(parts).lower()
        if len(ent) >= 4:
            sig.add("ent:" + ent)
    # 机型/型号代码（标题与摘要都看）
    for m in _MODEL_RE.finditer(title + " " + (item.get("summary") or "")):
        sig.add("model:" + m.group(1).lower())
    return sig


def _cluster_union_find(n: int, pairs: list[tuple[int, int]]) -> list[list[int]]:
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for a, b in pairs:
        union(a, b)
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def cluster_events(judged: list, window_hours: int = 48) -> list:
    """对评分通过（score ≥ min）的条目做 48h 同题聚类。

    输入 judged：list of (date, it, j) 三元组（j 为 Judgment，可变）。
    返回裁剪后的 judged 列表（同题只保留评分最高的一条，其余折叠进 related）。

    说明：fetch 窗口一般 ≤3 天，故入参条目天然落在 48h/周窗口内；这里不强行
    按日期裁，避免把「同一事件隔日报道」误拆。若未来要跨更长窗口，再按
    published 时间戳过滤即可（接口已留 window_hours）。
    """
    n = len(judged)
    if n <= 1:
        return judged
    sigs = [_topic_signature(it) for _, it, _j in judged]
    pairs: list[tuple[int, int]] = []
    for i in range(n):
        for k in range(i + 1, n):
            shared = sigs[i] & sigs[k]
            if not shared:
                continue
            strong = {t for t in shared if t.startswith(("ent:", "model:"))}
            if len(shared) >= 2 or strong:
                pairs.append((i, k))
    groups = _cluster_union_find(n, pairs)
    kept_idx: list[int] = []
    folds = 0
    for members in groups:
        if len(members) == 1:
            kept_idx.append(members[0])
            continue
        # 同组内按评分降序；评分相同则证据等级高者优先（见 EVIDENCE_RANK）
        members_sorted = sorted(
            members,
            key=lambda i: (judged[i][2].score, judged[i][2].evidence_rank),
            reverse=True,
        )
        canon = members_sorted[0]
        related: list[tuple[str, str]] = []
        for mi in members_sorted[1:]:
            _d, it, _j = judged[mi]
            url = it.get("source_url") or it.get("link", "")
            if url:
                related.append((it.get("title", ""), url))
        # 折叠进主卡的 related（Mutable Judgment，直接改属性即可）
        judged[canon][2].related = related
        folds += len(related)
        kept_idx.append(canon)
    if folds:
        print(f"[score] 事件聚类：{n} 条 → {len(kept_idx)} 条，折叠 {folds} 条为补充来源")
    # 重新按评分降序，保持下游排序一致
    kept = [judged[i] for i in kept_idx]
    kept.sort(key=lambda t: t[2].score, reverse=True)
    return kept


# ---------------------------------------------------------------------------
# 规则回退评分（无 LLM）：同样输出六维明细，保证两条路径的字段一致
# ---------------------------------------------------------------------------

def _days_since(item: dict) -> int:
    from datetime import date, datetime as _dtm
    s = str(item.get("published") or "")
    try:
        d = _dtm.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return 0
    return max(0, (date.today() - d).days)


def _rule_dims(item: dict, hint: str, content_type: str) -> dict[str, int]:
    """启发式六维打分。来源身份只经「证据质量」一维参与，不做全局乘法加权。

    2026-08-06 重构：各维按该 content_type 的满分（CONTENT_TYPE_DIM_PROFILES）裁剪；
    timeliness 按「内容有效时间」启发式——类型基线（研究/实验类常青高、新闻/公告类短命低）
    + 原理性信号词加成。
    """
    text = _text_of(item)
    title = (item.get("title") or "").lower()
    profile = dim_profile(content_type)
    mx = lambda k: profile.get(k, 0)  # noqa: E731

    hits = _core_hits(text)
    title_hits = _core_hits(title)
    # 意式相关性：按核心词命中密度阶梯给分（标题命中额外加权，说明是主题而非顺带提及）。
    if len(hits) >= 4:
        relevance = 30
    elif len(hits) >= 2:
        relevance = 24
    elif len(hits) == 1:
        relevance = 16
    else:
        relevance = 6
    relevance = min(mx("relevance"), relevance + min(6, len(title_hits) * 3))

    novelty = min(mx("novelty"), RULE_NEUTRAL_BASELINE["novelty"]
                  + sum(4 for k in NOVELTY_KEYWORDS if k in text))
    actionability = min(mx("actionability"), RULE_NEUTRAL_BASELINE["actionability"]
                        + sum(4 for k in ACTION_KEYWORDS if k in text))

    # 证据质量：由内容性质（来源身份的体现）决定基准，再按类型满分裁剪
    evidence = min(mx("evidence"), {
        "research": 13, "expert_experiment": 11, "independent_review": 10,
        "announcement": 8, "news": 7, "community_case": 5,
    }.get(content_type, 6))

    params = min(mx("params"), len(PARAM_PATTERN.findall(text)) * 2)

    # 内容有效时间（非新鲜度）：类型基线 + 原理性信号词加成
    #   研究/专家实验：原理性内容长期有效 → 基线高分
    #   新闻/公告：行业动态/新品短命 → 基线低分
    #   社区个案/评测：故障排查与长期评测参考期长 → 中分基线
    _evergreen_baseline = {
        "research": 0.85, "expert_experiment": 0.85, "independent_review": 0.65,
        "community_case": 0.65, "news": 0.45, "announcement": 0.35,
    }.get(content_type, 0.5)
    _evergreen_signal = any(k in text for k in (
        "study", "research", "experiment", "physics", "principle", "theory",
        "model", "methodology", "mechanism", "原理", "机制", "方法论", "建模",
    ))
    if _evergreen_signal:
        _evergreen_baseline = min(1.0, _evergreen_baseline + 0.2)
    timeliness = max(0, min(mx("timeliness"), int(round(mx("timeliness") * _evergreen_baseline))))

    return {
        "relevance": relevance, "novelty": novelty, "actionability": actionability,
        "evidence": evidence, "params": params, "timeliness": timeliness,
    }


def _fallback(item: dict, hint: str, content_type: str = "") -> Judgment:
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
    ctype = content_type or HINT_TO_CONTENT_TYPE.get(hint, "news")
    dims = _rule_dims(item, hint, ctype)
    summary = item.get("summary") or item.get("title", "")
    # 无 LLM 时无法做翻译/摘要/深度整理，kind 固定 summary（正文取抓取摘要），
    # deepdive 留空（前端不渲染该区块）
    return Judgment(
        tags=tags, summary=summary, score=dims_total(dims), kind="summary",
        deepdive="", references=None, content_type=ctype, dims=dims,
        why_read="", related=None,
    )


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


def _dim_rubric(content_type: str = "") -> str:
    """六维评分标准（写进 prompt，保证可解释、可复现）。

    2026-08-06 重构：各维**满分按 content_type 差异化**（见 CONTENT_TYPE_DIM_PROFILES），
    每种内容类型只对该类型的价值点给满权重；总分恒为 100，min_score 语义不变。
    timeliness 重定义为「内容有效时间」——信息有效期越长分值越高（与新闻新鲜度相反）。
    """
    profile = dim_profile(content_type)
    mx = lambda k: profile.get(k, 0)  # noqa: E731
    return (
        f"【六维评分标准】本条内容性质 = {content_type or '未判定'}，"
        "总分 = 六维之和（满分 100，各维满分随内容性质不同）。每一维都要独立判断，"
        "不要凭「来源有名」整体拔高。各维满分如下：\n"
        f"1. relevance 意式相关性（0-{mx('relevance')}）：是否直接服务于意式浓缩的萃取/器具/参数/工艺。\n"
        f"   满分档 = 通篇围绕意式核心；中档 = 意式占一部分；低档 = 泛咖啡内容顺带提及；近 0 = 基本无关。\n"
        f"2. novelty 新颖性（0-{mx('novelty')}）：是否提供了新信息/新发现/反常识结论。\n"
        f"   高分 = 颠覆共识/新数据/新产品实质信息；中分 = 有内容但非首创；低分 = 常见复述。\n"
        f"3. actionability 可操作性/实用价值（0-{mx('actionability')}）：读者能否据此改变操作或决策。\n"
        f"   对操作类（评测/实验/社区个案）：高分 = 给出可直接照做的步骤/参数；中分 = 有方向需自行试；低分 = 仅启发。\n"
        f"   对资讯类（news/announcement）：改为评「信息对读者的实用/决策价值」——行业动态/新品信息本身即有价值，"
        f"不要因「无法操作」给 0-2 分。\n"
        f"4. evidence 证据质量（0-{mx('evidence')}）：**这是来源身份唯一参与打分的地方**。\n"
        f"   满分档 = 同行评审论文/可复现实验；中高档 = 专家实验/独立实测/有出处的行业报道；\n"
        f"   中低档 = 厂商规格/社区个案但过程具体；低分 = 无据断言、营销话术。\n"
        f"   **注意**：社区个案(community_case)的 evidence 满分本就低（5 分），不要因「不是权威来源」再额外压分。\n"
        f"5. params 参数具体度（0-{mx('params')}）：是否给出具体数值（粉量、液重、时间、压力、温度、粒径、TDS 等）。\n"
        f"   高分 = 完整配方或成套实验参数；中分 = 有部分关键数值；低分 = 零星提及；0 = 全无数值。"
        f"   按材料中**可见**信息打分：材料里写了参数就给分，没写则给 0——与是否抓到全文无关。\n"
        f"6. timeliness 内容有效时间（0-{mx('timeliness')}）：**信息有效期的长度**，不是发布新鲜度。\n"
        f"   满分档 = 原理性/长期恒定有效（萃取物理、标准配方逻辑、通用调参方法论）；\n"
        f"   中高分 = 数年有效（成熟机型长期评测、行业基础共识）；\n"
        f"   中低分 = 数月有效（当季新品、短期行业趋势）；\n"
        f"   低分 = 一次性/即时新闻（单日事件、价格变动、临时活动）。\n"
        "【分档参考】85+ 罕见强证据；70-84 日报主内容；60-69 确有补充价值才收；60 以下不发布。\n"
        "务必拉开区分度：多数条目应落在 55-80，不要集中打 70-75。\n"
    )


def _call_llm_meta(cfg: dict, item: dict, hint: str, content_type: str = "") -> Judgment | None:
    """Two-Pass 第二段：精评。输出 title / tags / summary / kind / 六维分 / why_read。

    若 item 带 `full_text`（初筛通过后按需抓取所得），优先基于全文精评——
    这正是「先初筛、后全文」的收益：不再基于截断摘要虚构参数与结论。
    """
    client = _llm_client(cfg)
    if client is None:
        return None
    api_key, base, model, temperature = client

    full_text = (item.get("full_text") or "").strip()
    if full_text:
        body_label = "正文（原文全文，已抓取）"
        body = full_text[:9000]
    else:
        body_label = "正文/摘要（RSS 截断摘要，可能不完整）"
        body = item.get("summary", "")

    # 统一评分指令：不再按有无全文区分——评分完全交给下方 rubric 的六维定义，
    # 此处只约束「禁止虚构」。params/evidence 按材料中可见信息如实打分，
    # 不被「是否抓到全文」这一采集状态影响。
    body_note = (
        "请严格基于上方材料如实打分，严禁虚构材料未提到的数据、参数或结论；"
        "信息不足时如实写「原文未展开」。\n"
    )

    prompt = (
        "你是意式浓缩咖啡资讯的资深编辑。面对一条新闻/资讯，先判断它的「处理方式」(kind)，再输出评估。\n\n"
        "【处理方式 kind 四选一】\n"
        "1. as-is：原文已足够精炼、信息完整、可直接面向读者，且原文为中文——直接原样输出，不做摘要、不改写。\n"
        "2. translate：原文已足够精炼、信息完整，但为英文等非中文——翻译成中文原样输出，"
        "保持原文信息量与结构，不压缩、不精炼。\n"
        "3. summary：原文冗长、结构松散或信息密度低，需要提炼——输出中文摘要，保留关键信息。\n"
        "4. deepdive：内容原理性强、反常识、有争议或信息密度极高，值得结合知识库深度展开——"
        "先输出中文摘要，后续会再生成深度解读。\n"
        "【标题要求】\n"
        "1. 把原文标题**改写为简洁的中文标题**（如原文已是中文则润色即可）：翻译 + 提炼，"
        "15-30 字为宜，不用引号、不带「今日/快讯」等前缀。\n"
        "2. 保留关键专名：机型/品牌/人名/机构（如 Zerno Z1、Gaggia、Barista Hustle）保留原拼写，"
        "技术词用中文（如 磨豆机、预浸泡、萃取率）。\n"
        "3. 是编辑标题而非机械翻译：抓住最核心的信息点（谁/什么/结果），删掉修饰与营销话术。\n"
        "【标签要求】\n"
        "1. 不使用固定的 theory/technique/product 这种大类，而是用更具体的小主题，\n"
        "   例如：9-bar、水温、研磨度、布粉wdt、填压、预浸泡、通道效应、萃取率tds、\n"
        "   粉水比、奶泡、调参dialin、咖啡机、磨豆机、粉碗、秤、新手、进阶、评测、对比、意式基础。\n"
        "2. 返回 2-5 个标签，可中可英，尽量精炼（一个标签通常 2-6 个字/词）。\n"
        "3. 标签应反映内容真正讲的知识点/器具/人群，而不是泛泛而谈。\n\n"
        f"【来源分类提示（仅供参考，不要直接当标签）】{hint}\n\n"
        + _dim_rubric(content_type) + "\n"
        f"【来源】{item.get('source','')}　【内容性质（初筛判定）】{content_type or '未判定'}\n"
        f"标题：{item.get('title','')}\n"
        f"{body_note}"
        f"{body_label}：{body}\n\n"
        "【输出要求】\n"
        "1. title：中文标题（同上）。\n"
        "2. tags：2-5 个具体主题标签（同上）。\n"
        "3. summary：按 kind 说明**处理后作为正文**的内容——as-is=中文原文；"
        "translate=中文翻译原文；summary/deepdive=中文摘要。\n"
        "   **摘要长度按来源类型区分**：\n"
        "   - 新闻媒体类（Sprudge/Perfect Daily Grind/Daily Coffee News 等）：200-400 字，"
        "     保留时间、具体数据、关键结论、人物引述，用 2-3 个要点或自然段，禁止一句话概括；\n"
        "   - 社区讨论类（Reddit/论坛）：150-300 字，保留机型、参数、优缺点、结论；\n"
        "   - 原文信息本身很少（<100 字）时：如实转述即可，不要为凑字数注水。\n"
        "4. kind：as-is / translate / summary / deepdive 四选一，严格小写。\n"
        "5. scores：六维明细对象，键为 relevance/novelty/actionability/evidence/params/timeliness，"
        "值为该维整数分（不得超过各维满分）。**不要自己算总分**，由程序求和。\n"
        "6. content_type：expert_experiment / independent_review / news / community_case / "
        "announcement / research 六选一（可修正初筛判定）。\n"
        "7. why_read：一句「为什么值得读」，30 字以内，说清读者能得到什么；"
        "不要写「值得一读」这种空话。\n\n"
        '只输出 JSON，格式：{"title":"中文标题","tags":["标签1","标签2"],'
        '"summary":"处理后正文","kind":"summary","content_type":"news",'
        '"scores":{"relevance":0,"novelty":0,"actionability":0,"evidence":0,'
        '"params":0,"timeliness":0},"why_read":"一句话"}'
    )
    data = _chat_json(api_key, base, model, temperature, prompt)
    if data is None:
        return None

    tags = [_norm_tag(t) for t in data.get("tags", []) if _norm_tag(t)]
    tags = sorted(set(tags))[:5]
    if not tags:
        tags = [DEFAULT_FALLBACK_TAG]
    ctype = _norm_content_type(str(data.get("content_type", "")), hint) if data.get("content_type") \
        else (content_type or HINT_TO_CONTENT_TYPE.get(hint, "news"))
    dims = _norm_dims(data.get("scores"), ctype)
    kind = data.get("kind")
    return Judgment(
        tags=tags,
        summary=data.get("summary", item.get("summary", "")),
        score=dims_total(dims),
        # LLM 未给出合法 kind 时，按 content_type 兜底映射（两套枚举的对齐点）
        kind=_norm_kind(kind) if kind else CONTENT_TYPE_TO_KIND.get(ctype, "summary"),
        title=str(data.get("title", "") or "").strip(),
        deepdive="",
        references=None,
        content_type=ctype,
        dims=dims,
        why_read=_one_line(data.get("why_read", ""), 120),
        used_full_text=bool(full_text),
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


def judge(item: dict, cfg: dict, hint: str = "mixed", knowledge_ctx: str = "",
          content_type: str = "") -> Judgment:
    """精评：六维打分 + 标签 + 正文（LLM 优先，失败回退规则）。

    - 精评（本函数）：tags/summary/六维分/kind/why_read，不注入知识库；
      若 item 带 `full_text` 则基于全文，否则基于 RSS 摘要并提示模型不得虚构。
    - 深度解读：仅 kind=deepdive 时注入知识库生成（受 deepdive_enabled 控制）。
    - 无 LLM 时回退规则：不产出 deepdive，kind 固定为 summary。
    - `content_type` 由初筛（prescreen）传入，LLM 可在精评时修正。
    """
    llm = cfg.get("llm", {})
    if llm.get("enabled"):
        j = _call_llm_meta(cfg, item, hint, content_type=content_type)
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
                    print("[score] 深度解读生成失败，降级为仅摘要")
            return j
    return _fallback(item, hint, content_type)


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
