"""抓取信息源（RSS + 搜索 API 适配器）。

- type=rss：标准 RSS / Atom（也适用于自托管 RSSHub 生成的 feed）。
- type=search：调用站点 JSON 搜索接口并归一化（知乎 / B站 / 什么值得买 等）。
  配置示例：
    [[sources]]
    name = "知乎 · 意式浓缩"
    type = "search"
    parser = "zhihu"            # 内置适配器名
    url = "https://www.zhihu.com/api/v4/search_v3?t=general&q=意式浓缩&limit=20"
    category_hint = "mixed"
    lang = "zh"

返回原始条目列表，每条含：
  title, summary, link, published(date str), source, source_url, lang, hint
"""
from __future__ import annotations

import datetime as dt
import email.utils
import json
import os
import re
import subprocess
import time
import zoneinfo
from datetime import datetime, timezone

import feedparser
import httpx

from src.content_loader import load_config

# 默认 UA：config 缺省时回退（与 config.example.toml [fetch].user_agent 保持一致）
DEFAULT_UA = "EspressoDaily/0.1 (+https://github.com/your-org/espresso-daily)"
DEFAULT_SEARCH_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
# 抓取失败报告目录（供阶段二质量报告使用）
REPORTS_DIR = "reports"

# 全文抓取（阶段二）：全文是稀缺资源，仅对白名单来源 + 初筛 accept 的条目按需抓取
FULLTEXT_MAX_CHARS = 12000   # 正文截断上限（避免超长文烧 LLM token）
FULLTEXT_MIN_CHARS = 200     # 低于此长度视为提取失败，回退 RSS 摘要
FULLTEXT_MIN_PARAGRAPH = 40  # 段落最短字符数，短于此的多为导航/版权/按钮文案


# ---------------------------------------------------------------------------
# 搜索适配器：把各站 JSON 搜索结果归一化成统一条目
# 每个适配器：fn(raw_json: dict, source: dict) -> list[dict]
# ---------------------------------------------------------------------------

def _zhihu_parse(raw: dict, source: dict) -> list[dict]:
    out = []
    for item in (raw.get("data") or []):
        obj = (item.get("object") or {})
        title = obj.get("title") or obj.get("name") or ""
        # 知乎正文在 excerpt/description，可能含 HTML
        excerpt = obj.get("excerpt") or obj.get("description") or ""
        link = obj.get("url") or ""
        if not link and obj.get("id"):
            link = f"https://www.zhihu.com/question/{obj['id']}"
        out.append({
            "title": _clean(title),            "summary": _clean(excerpt),
            "link": link,
            # source_url = 文章链接（去重/卡片来源链接用）；空链接回退源站地址
            "source_url": link or source.get("url", ""),
            "published": dt.datetime.now().strftime("%Y-%m-%d"),
            "source": source["name"],
            "lang": source.get("lang", ""), "hint": source.get("category_hint", "mixed"),
        })
    return out


def _bilibili_parse(raw: dict, source: dict) -> list[dict]:
    out = []
    result = (raw.get("data") or {}).get("result") or []
    for grp in result:
        for item in (grp.get("data") or []):
            title = item.get("title") or ""
            desc = item.get("description") or ""
            # 去除搜索高亮标签 <em>
            aid = item.get("aid") or item.get("id")
            link = f"https://www.bilibili.com/video/av{aid}" if aid else ""
            # 发布日期：优先 pubdate（Unix 秒，真实发布时间），缺失回退当天。
            # 2026-08-08 修复：此前写死「今天」，导致旧视频伪装成新内容绕过 lookback 过滤
            # （实测 2022/2023 年视频被判为当日收录）。
            published = dt.datetime.now().strftime("%Y-%m-%d")
            pub = item.get("pubdate") or item.get("senddate")
            if pub:
                try:
                    published = datetime.fromtimestamp(
                        int(pub), tz=zoneinfo.ZoneInfo("Asia/Shanghai")
                    ).strftime("%Y-%m-%d")
                except Exception:
                    pass
            out.append({
                "title": _clean(re.sub(r"<[^>]+>", "", title)),
                "summary": _clean(re.sub(r"<[^>]+>", "", desc)),
                "link": link,
                # source_url = 文章/视频链接（去重、卡片来源链接用）
                "source_url": link or source.get("url", ""),
                "published": published,
                "source": source["name"],
                "lang": source.get("lang", ""), "hint": source.get("category_hint", "mixed"),
            })
    return out


def _smzdm_parse(raw: dict, source: dict) -> list[dict]:
    out = []
    # 什么值得买搜索返回 { rows: [ {article_title, article_content, article_url} ] }
    rows = (raw.get("data") or {}).get("rows") or raw.get("rows") or []
    for item in rows:
        link = item.get("article_url") or item.get("url") or ""
        out.append({
            "title": _clean(item.get("article_title") or item.get("title") or ""),            "summary": _clean(item.get("article_content") or item.get("content") or ""),
            "link": link,
            # source_url = 文章链接（去重、卡片来源链接用）
            "source_url": link or source.get("url", ""),
            "published": dt.datetime.now().strftime("%Y-%m-%d"),
            "source": source["name"],
            "lang": source.get("lang", ""), "hint": source.get("category_hint", "mixed"),
        })
    return out


# ---------------------------------------------------------------------------
# 知乎官方 CLI 适配器（type=zhihu_cli）
# 调用本机安装的 zhihu-cli（Access Secret 认证，走钥匙串），搜索知乎内容。
# 安装与配置见 SOURCES.md「路径 0：知乎官方 CLI」。
# 2026-08-08 接入：官方通道，无反爬；邀测额度知乎搜索 5000 次/天。
# ---------------------------------------------------------------------------

# 本机 CLI 路径（setup.sh 安装；可用 ZHIHU_CLI_BIN 环境变量覆盖）
DEFAULT_ZHIHU_CLI = os.path.expanduser(
    "~/Library/Application Support/zhihu-cli/current/zhihu-cli"
)


def fetch_zhihu_cli(source: dict, lookback_days: int = 3, failures: list | None = None,
                    cli_bin: str | None = None) -> list[dict]:
    """调用知乎官方 CLI 搜索，返回与 RSS 同构的条目列表。

    - cli_bin：CLI 绝对路径，缺省 DEFAULT_ZHIHU_CLI（可被环境变量 ZHIHU_CLI_BIN 覆盖）
    - query：取 source["query"]（搜索词），可带多个用 || 分隔（依次搜索合并去重）
    - lookback_days：回看窗口，仅保留窗口内的条目（知乎搜索按相关度排序，易回旧文；
      2026-08-08 实测近 3 天窗口内常 0 条，属知乎搜索特性，勿放宽——放宽即旧文回流）
    - 输出：`zhihu-cli search zhihu --query <q> --count <n> --pretty` 的 JSON
    """
    bin_path = cli_bin or os.getenv("ZHIHU_CLI_BIN", "") or DEFAULT_ZHIHU_CLI
    if not os.path.exists(bin_path):
        _record_failure(failures, source, "zhihu-cli", FileNotFoundError(
            f"zhihu-cli 未安装（{bin_path}）。见 SOURCES.md「路径 0：知乎官方 CLI」。"))
        return []
    queries = [q.strip() for q in str(source.get("query", "")).split("||") if q.strip()]
    if not queries:
        _record_failure(failures, source, "zhihu-cli",
                        ValueError("type=zhihu_cli 源需要 query 字段（支持 || 分隔多词）"))
        return []
    count = int(source.get("max_per_source") or source.get("count") or 10)
    count = max(1, min(count, 10))   # CLI 上限 10

    # lookback 过滤：与 fetch_rss 的 cutoff 一致（目标时区「今天」为基准）
    tz = zoneinfo.ZoneInfo("Asia/Shanghai")
    cutoff = (dt.datetime.now(tz) - dt.timedelta(days=lookback_days)).date()

    items: list[dict] = []
    seen_urls: set[str] = set()
    for q in queries:
        try:
            proc = subprocess.run(
                [bin_path, "search", "zhihu", "--query", q, "--count", str(count), "--pretty"],
                capture_output=True, text=True, timeout=60,
            )
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.strip() or f"exit {proc.returncode}")
            raw = json.loads(proc.stdout)
        except Exception as e:
            _record_failure(failures, source, f"zhihu-cli search:{q}", e)
            continue
        for it in (raw.get("Data") or {}).get("Items") or []:
            url = (it.get("Url") or "").split("?")[0]   # 去 utm 参数
            if not url or url in seen_urls:
                continue
            # EditTime 为 Unix 秒（可能缺失），截日归档
            published = dt.datetime.now().strftime("%Y-%m-%d")
            et = it.get("EditTime")
            if et:
                try:
                    published = datetime.fromtimestamp(
                        int(et), tz=tz
                    ).strftime("%Y-%m-%d")
                except Exception:
                    pass
            # 旧文过滤：早于 cutoff 丢弃（知乎搜索按相关度排序，天然回旧文）
            try:
                if dt.datetime.strptime(published, "%Y-%m-%d").date() < cutoff:
                    continue
            except Exception:
                pass
            seen_urls.add(url)
            items.append({
                "title": _clean(it.get("Title") or ""),
                "summary": _clean(it.get("ContentText") or ""),
                "link": url,
                "source_url": url,
                "published": published,
                "source": source["name"],
                "lang": source.get("lang", "zh"),
                "hint": source.get("category_hint", "mixed"),
                # 作者/互动量：社区类排序信号
                "author": _clean(it.get("AuthorName") or ""),
                "engagement": int(it.get("VoteUpCount") or 0),
                "max_per_source": source.get("max_per_source"),
                "quota_group": source.get("quota_group"),
                "max_per_group": source.get("max_per_group"),
                "allow_full_text": bool(source.get("full_text", False)),
            })
        print(f"[fetch] 源 {source['name']}（zhihu_cli/{q}）：{len(items)} 条累计")
    return items


SEARCH_PARSERS = {
    "zhihu": _zhihu_parse,
    "bilibili": _bilibili_parse,
    "smzdm": _smzdm_parse,
}


def fetch_search(source: dict, lookback_days: int = 3, user_agent: str | None = None,
                 failures: list | None = None) -> list[dict]:
    ua = user_agent or DEFAULT_SEARCH_UA
    parser = SEARCH_PARSERS.get(source.get("parser"))
    if not parser:
        print(f"[fetch] 源 {source['name']} 的 parser={source.get('parser')} 未实现，跳过。")
        return []
    try:
        headers = {"User-Agent": ua, "Referer": source.get("referer", "https://www.baidu.com/")}
        resp = httpx.get(source["url"], headers=headers, timeout=20, follow_redirects=True)
        resp.raise_for_status()
        raw = resp.json()
        items = parser(raw, source)
    except Exception as e:
        _record_failure(failures, source, source.get("url", ""), e)
        return []
    print(f"[fetch] 源 {source['name']}（search/{source.get('parser')}）：{len(items)} 条")
    return items


def _resolve_tz(tzname: str | None):
    """解析目标时区（aware tzinfo）。

    - 配置了且可用（需 tzdata，Windows 上尤其）则用之；
    - 否则回退机器本地时区，保证零依赖也能按本地时区截日。
    """
    if tzname:
        try:
            return zoneinfo.ZoneInfo(tzname)
        except Exception as e:
            print(f"[fetch] 时区 '{tzname}' 不可用（可能缺 tzdata）：{e}；回退本地时区")
    return dt.datetime.now().astimezone().tzinfo


def _to_date(entry, tz=None) -> str | None:
    """从 RSS 条目提取发布日期（YYYY-MM-DD）。

    feedparser 的 *_parsed 字段均为 UTC。先转目标时区（tz）再截日，
    使海外源（如 Reddit）按本地/目标时区归档，避免「当天内容归到昨天」。
    """
    for key in ("published_parsed", "updated_parsed", "pub_date_parsed"):
        val = entry.get(key)
        if val:
            try:
                utc_dt = datetime(*val[:6], tzinfo=timezone.utc)
                local_dt = utc_dt.astimezone(tz) if tz else utc_dt
                return local_dt.strftime("%Y-%m-%d")
            except Exception:
                pass
    # 退而求其次：尝试解析 RFC 822 日期字符串（无 *_parsed 时）。
    # 标准库 email.utils.parsedate_to_datetime 返回带时区的 datetime；
    # 无时区信息则按 RFC 视为 UTC。
    for key in ("published", "updated", "pubDate"):
        s = entry.get(key)
        if s:
            try:
                dt_obj = email.utils.parsedate_to_datetime(s)
                if dt_obj is None:
                    continue
                if dt_obj.tzinfo is None:
                    dt_obj = dt_obj.replace(tzinfo=timezone.utc)
                local_dt = dt_obj.astimezone(tz) if tz else dt_obj
                return local_dt.strftime("%Y-%m-%d")
            except Exception:
                pass
    return None


def _clean(html: str | None) -> str:
    """去标签 + 解码 HTML 实体 + 压缩空白。

    实体解码不可省：RSS/网页正文里的 &rsquo; &#8217; &amp; 若原样送进 LLM 与页面，
    会变成 "don&rsquo;t" 这类脏字符串。
    """
    import html as _html
    import re
    if not html:
        return ""
    txt = re.sub(r"<[^>]+>", " ", html or "")
    txt = _html.unescape(txt)
    return re.sub(r"\s+", " ", txt).strip()


def fetch_rss(source: dict, lookback_days: int = 3, tz=None,
              user_agent: str | None = None, failures: list | None = None) -> list[dict]:
    ua = user_agent or DEFAULT_UA
    try:
        resp = httpx.get(source["url"], headers={"User-Agent": ua}, timeout=20, follow_redirects=True)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
    except Exception as e:
        _record_failure(failures, source, source.get("url", ""), e)
        return []

    # 解析异常（feedparser bozo）：仅在确实无条目时记录，避免噪声
    if parsed.get("bozo") and parsed.get("bozo_exception") and not parsed.entries:
        ctype = resp.headers.get("content-type", "")
        # 响应头前 120 字符：CI 被反爬时返回 HTML 质询页/403 页而非 XML，
        # 记下来便于区分「源挂了」与「被拦截」（见 2026-08-08 CI 日志 PDG/BH）
        probe = re.sub(r"\s+", " ", resp.text or "")[:120]
        _record_failure(
            failures, source, source.get("url", ""),
            Exception(f"feed parse error: {parsed['bozo_exception']} "
                      f"[content-type={ctype} | body={probe!r}]"),
        )

    # cutoff 以目标时区的「今天」为基准，与归档日期同一时区，避免时区错位
    today = (dt.datetime.now(tz) if tz else dt.datetime.now()).date()
    cutoff = today - dt.timedelta(days=lookback_days)
    items: list[dict] = []
    for e in parsed.entries:
        date = _to_date(e, tz)
        if date:
            try:
                if dt.datetime.strptime(date, "%Y-%m-%d").date() < cutoff:
                    continue
            except Exception:
                pass
        items.append({
            "title": (e.get("title") or "").strip(),
            "summary": _clean(e.get("summary") or e.get("description")),
            "link": e.get("link", ""),
            # source_url = 文章链接（去重、卡片来源链接用）；空链接回退源站地址
            "source_url": e.get("link", "") or source.get("url", ""),
            "published": date or dt.datetime.now().strftime("%Y-%m-%d"),
            "source": source["name"],
            "lang": source.get("lang", ""),
            "hint": source.get("category_hint", "mixed"),
            # 互动量（Reddit 等带赞/评论的源）：社区类作排序信号
            "engagement": _extract_engagement(e),
            # 配额元数据：透传给 pipeline，按每源/每组上限裁剪
            "max_per_source": source.get("max_per_source"),
            "quota_group": source.get("quota_group"),
            "max_per_group": source.get("max_per_group"),
            # 全文白名单：仅 config 中 full_text=true 的源允许在初筛通过后抓全文
            "allow_full_text": bool(source.get("full_text", False)),
        })
    print(f"[fetch] 源 {source['name']}：{len(items)} 条（近 {lookback_days} 天）")
    return items


def _extract_engagement(entry: dict) -> int:
    """从 RSS 条目抽取互动量（赞/分），用于社区类排序信号；无则 0。"""
    for key in ("ups", "score", "likes", "rating"):
        v = entry.get(key)
        if isinstance(v, (int, float)) and v > 0:
            return int(v)
    return 0


def _record_failure(failures: list | None, source: dict, url: str, exc: Exception,
                    stage: str = "feed") -> None:
    """把一次抓取/解析失败结构化为记录，累积进 failures 列表并打印。

    字段：source / url / stage / timestamp / error_type / status_code /
    rate_limited / blocked / message —— 供阶段二质量报告统计
    （每源失败率、是否限流、失败发生在 feed 还是 fulltext 阶段等）。
    """
    rec = {
        "source": source.get("name", "") if isinstance(source, dict) else str(source),
        "url": url,
        "stage": stage,   # feed | fulltext | academic
        "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
        "error_type": "unknown",
        "status_code": None,
        "rate_limited": False,
        "blocked": False,
        "message": str(exc),
    }
    if isinstance(exc, httpx.HTTPStatusError):
        rec["error_type"] = "http_error"
        rec["status_code"] = exc.response.status_code
        rec["rate_limited"] = exc.response.status_code == 429
        rec["blocked"] = exc.response.status_code in (401, 403, 407, 429)
    elif isinstance(exc, httpx.HTTPError):
        rec["error_type"] = "http_error"
    if failures is not None:
        failures.append(rec)
    name = rec["source"] or url
    print(f"[fetch] 源 {name} 抓取/解析失败：{exc}")


def _kw_hit(k: str, text: str) -> bool:
    """exclude 关键词命中：纯英文单词用「全词边界」匹配，避免子串误杀。

    2026-08-08 修复：exclude 里的 "tea" 会子串命中 "steam"/"teach"/"team"，
    导致 Clive/CoffeeGeek 意式教程文（必讲蒸汽奶泡）被整源误杀（CI 日志
    Clive 1→0 条）。全词边界 \btea\b 只匹配独立词 tea 及其复数 teas。
    策略：exclude 宁可漏杀（漏掉的由 LLM 初筛/评分兜底）也不可误杀；
    词根意图词（如 DCN 的 "nutrit"→nutrition）无法用全词边界覆盖，
    已在 config 里显式展开为 nutrition/nutritional。
    非纯字母词（短语/数字/中文）回退子串，保召回。
    """
    if re.fullmatch(r"[A-Za-z]+", k):
        return re.search(rf"\b{re.escape(k)}(?:s|es)?\b", text) is not None
    return k in text


def _source_prefilter(source: dict, items: list[dict]) -> list[dict]:
    """按源的 include_any / exclude_any 关键词做二次过滤（不消耗 LLM）。

    - include_any：若设置，标题+摘要须至少命中其一（意式相关性闸门）；
    - exclude_any：若设置，命中任一即丢弃（晒图/购买咨询/健康/公平贸易等）。
    """
    inc = [k.lower() for k in (source.get("include_any") or [])]
    exc = [k.lower() for k in (source.get("exclude_any") or [])]
    if not inc and not exc:
        return items
    out = []
    for it in items:
        text = (it.get("title", "") + " " + it.get("summary", "")).lower()
        if exc and any(_kw_hit(k, text) for k in exc):
            continue
        if inc and not any(k in text for k in inc):
            continue
        out.append(it)
    if len(out) != len(items):
        print(f"[fetch] 源 {source['name']} 关键词预过滤：{len(items)} → {len(out)} 条")
    return out


# ---------------------------------------------------------------------------
# 按需全文抓取（阶段二前置）
#
# 为什么需要：RSS 摘要普遍被截断（几十到两百字），基于截断摘要做精评容易让 LLM
# 「补全」出原文没有的参数与结论。全文能消除这类虚构，但抓全文有流量与封禁成本，
# 因此它是**稀缺资源**：只对 ① 白名单来源（config 里 `full_text = true`）
# ② 初筛 accept 的条目，二者同时满足才抓。
#
# 实现取舍：不引入 readability-lxml / beautifulsoup 等重依赖（CI 装依赖只有 5 个包，
# 且 daily.yml 未装它们），改用「去样板块 + 取段落」的轻量启发式：
#   1) 剥离 script/style/nav/header/footer/aside/form/figure 等非正文块；
#   2) 优先在 <article> / <main> 容器内找正文，找不到再退回全文档；
#   3) 收集 <p>/<li> 文本，丢弃过短段落（导航、版权、按钮），拼接成纯文本。
# 提取不到足够长度（< FULLTEXT_MIN_CHARS）就返回空串，调用方回退 RSS 摘要。
# ---------------------------------------------------------------------------

_BOILERPLATE_TAGS = (
    "script", "style", "nav", "header", "footer", "aside",
    "form", "figure", "figcaption", "noscript", "iframe", "svg",
)


def _strip_boilerplate(html: str) -> str:
    """移除脚本/样式/导航等非正文块与 HTML 注释。"""
    out = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    for tag in _BOILERPLATE_TAGS:
        out = re.sub(rf"<{tag}\b.*?</{tag}\s*>", " ", out, flags=re.S | re.I)
        out = re.sub(rf"<{tag}\b[^>]*/?>", " ", out, flags=re.I)
    return out


def _main_container(html: str) -> str:
    """优先返回 <article> / <main> 容器内容；无则返回原文档。

    多个 <article> 时取最长的一个（列表页每条摘要也是 <article>，正文页正文最长）。
    """
    for tag in ("article", "main"):
        blocks = re.findall(rf"<{tag}\b[^>]*>(.*?)</{tag}\s*>", html, flags=re.S | re.I)
        if blocks:
            best = max(blocks, key=len)
            if len(re.sub(r"<[^>]+>", "", best)) >= FULLTEXT_MIN_CHARS:
                return best
    return html


def _extract_paragraphs(html: str, min_len: int = FULLTEXT_MIN_PARAGRAPH) -> str:
    """收集 <p>/<li> 文本，过滤过短段落后拼接为纯文本。"""
    chunks: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(r"<(p|li)\b[^>]*>(.*?)</\1\s*>", html, flags=re.S | re.I):
        text = _clean(m.group(2))
        if len(text) < min_len or text in seen:
            continue
        seen.add(text)
        chunks.append(text)
    return "\n\n".join(chunks)


def extract_article_text(html: str, max_chars: int = FULLTEXT_MAX_CHARS) -> str:
    """从 HTML 抽取正文纯文本；提取不到足够内容返回空串。"""
    if not html:
        return ""
    cleaned = _strip_boilerplate(html)
    text = _extract_paragraphs(_main_container(cleaned))
    if len(text) < FULLTEXT_MIN_CHARS:
        # 容器内段落太少：退回整篇文档再试一次（部分站点不用 <p> 包正文）
        text = _extract_paragraphs(cleaned)
    if len(text) < FULLTEXT_MIN_CHARS:
        # 仍不足：放宽段落长度门槛（短句排版的站点）
        text = _extract_paragraphs(cleaned, min_len=20)
    if len(text) < FULLTEXT_MIN_CHARS:
        return ""
    return text[:max_chars].strip()


def fetch_full_article(source: dict, link: str, user_agent: str | None = None,
                       failures: list | None = None, timeout: float = 20,
                       max_chars: int = FULLTEXT_MAX_CHARS) -> str:
    """按需抓取单篇文章全文，返回正文纯文本；失败/提取不到返回空串。

    调用方（pipeline）负责判断「是否该抓」——白名单 + 初筛 accept，本函数只管抓。
    失败复用 `_record_failure`，统一进 reports/fetch_failures_<date>.json。
    """
    if not link:
        return ""
    ua = user_agent or DEFAULT_UA
    # 部分站点（实测 Whole Latte Love）对 bot UA 直接断连，重试一次浏览器 UA
    last_exc: Exception | None = None
    for attempt_ua in (ua, DEFAULT_SEARCH_UA):
        try:
            resp = httpx.get(
                link,
                headers={"User-Agent": attempt_ua, "Accept": "text/html,application/xhtml+xml"},
                timeout=timeout, follow_redirects=True,
            )
            resp.raise_for_status()
            ctype = resp.headers.get("content-type", "")
            if ctype and "html" not in ctype.lower():
                return ""
            text = extract_article_text(resp.text, max_chars=max_chars)
            if not text:
                print(f"[fetch] 全文提取为空（回退摘要）：{link}")
            return text
        except Exception as e:
            last_exc = e
            continue
    _record_failure(failures, source, link, last_exc or Exception("unknown"), stage="fulltext")
    return ""


def write_failure_report(failures: list) -> None:
    """把本次运行的抓取失败清单写入 reports/（按日期聚合，供质量报告消费）。

    公开函数：全文抓取发生在 pipeline 初筛之后，因此由 pipeline 在全部抓取
    动作结束后统一落盘，避免 feed 阶段先写一次、全文阶段的失败漏记。
    """
    # 始终覆盖写入（即使为空）：保证按日期聚合的文件只反映「本次运行」，
    # 避免上一次运行残留的失败记录污染当次质量报告的「抓取失败维度」。
    try:
        os.makedirs(REPORTS_DIR, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y-%m-%d")
        path = os.path.join(REPORTS_DIR, f"fetch_failures_{stamp}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
                    "failures": failures,
                },
                f, ensure_ascii=False, indent=2,
            )
        if failures:
            print(f"[fetch] 已写入抓取失败报告：{path}（{len(failures)} 条）")
    except Exception as e:
        print(f"[fetch] 失败报告写入异常（不影响主流程）：{e}")


# ---------------------------------------------------------------------------
# 学术雷达适配器（阶段三）：OpenAlex + Crossref
#
# 与每日 RSS **解耦**——学术源只在周级 CI（src/academic.py + weekly.yml）里被调用，
# 不进每日 pipeline（每日 config 不含 academic 源）。这里仍挂在 fetch_all 的
# type 分发上，是为了让「按 type 分发」的契约完整、未来也可复用。
#
# 检索策略（严格，避免召回泛咖啡论文）：
#   - academic_must：多个词，全部以 abstract_search 串联 → AND 约束；
#   - academic_exclude：标题/摘要命中任一即丢弃（手冲/茶/零售等非意式主题）；
#   - academic_filters：透传 OpenAlex filter 串（如 from_publication_date）。
# OpenAlex 与 Crossref 双源取并集，按 DOI 去重。
# ---------------------------------------------------------------------------
OPENALEX_MAILTO = "espresso-daily@example.com"
_OPENALEX_API = "https://api.openalex.org/works"
_CROSSREF_API = "https://api.crossref.org/works"


def _oa_reconstruct_abstract(inv: dict | None) -> str:
    """OpenAlex 摘要以倒排索引给出（{词: [位置,...]}），重建为可读文本。"""
    if not inv:
        return ""
    slots: list[str] = []
    for word, positions in inv.items():
        for p in positions:
            if p >= len(slots):
                slots.extend([""] * (p - len(slots) + 1))
            slots[p] = word
    return " ".join(slots).strip()


def _strip_jats(xml: str | None) -> str:
    """Crossref 摘要是 JATS XML，剥掉标签并解码实体。"""
    if not xml:
        return ""
    import re
    txt = re.sub(r"<[^>]+>", " ", xml)
    try:
        import html as _html
        txt = _html.unescape(txt)
    except Exception:
        pass
    return re.sub(r"\s+", " ", txt).strip()


def _oa_evidence_level(w: dict) -> str:
    otype = (w.get("type") or "").lower()
    if otype == "preprint":
        return "预印本"
    if otype in ("article", "journal-article"):
        return "同行评审"
    if otype in ("review", "peer_review"):
        return "综述"
    return "其他"


# 咖啡领域确认词（不含查询词 espresso/extraction 本身，避免 ESPReSSO 单点登录等
# 缩写/领域歧义误报）。命中其一才视为真正的咖啡主题。
_COFFEE_DOMAIN = [
    "coffee", "bean", "beans", "roast", "roasting", "brew", "brewing", "crema",
    "barista", "caffeine", "beverage", "grinder", "portafilter", "arabica",
    "robusta", "tamp", "puck", "ristretto", "lungo", "foam", "steam", "dose",
    "shot", "shots", "tds", "extraction yield", "coffee machine", "espresso machine",
]
# 强非咖啡排除词：命中即直接排除（与 academic_exclude 配置互补）。
_STRONG_NON_COFFEE = [
    "single sign", "sign-on", "sign on", "sso", "login", "authentication",
    "identity management", "oauth", "authorization", "password", "harpsichord",
    "cembalo", "piano", "violin",
]


def fetch_academic(source: dict, lookback_days: int = 365, user_agent: str | None = None,
                   failures: list | None = None) -> list[dict]:
    """抓取学术源（OpenAlex + Crossref），返回与 RSS 同构的条目。

    额外字段（供研究卡使用）：doi / authors / venue / evidence_level / otype。
    """
    ua = user_agent or DEFAULT_UA
    must = [str(t).strip() for t in (source.get("academic_must")
                                      or [source.get("academic_query")] or []) if str(t).strip()]
    exclude = [str(t).lower() for t in (source.get("academic_exclude") or [])]
    extra = source.get("academic_filters") or ""
    per_page = int(source.get("max_per_source") or source.get("academic_per_page") or 10)
    if not must:
        print(f"[fetch] 学术源 {source.get('name')} 未配置 academic_must，跳过")
        return []

    items: list[dict] = []
    seen_doi: set[str] = set()

    def _excluded(title: str, abstract: str, enforce_must: bool = True) -> bool:
        blob = f"{title} {abstract}".lower()
        # 1) 配置化的排除词（tea/cold brew/sensory 等）
        if exclude and any(t in blob for t in exclude):
            return True
        # 2) 强非咖啡词（单点登录/乐器等缩写歧义）
        if any(t in blob for t in _STRONG_NON_COFFEE):
            return True
        # 3) 咖啡领域确认：至少命中一个咖啡领域词。
        #    有摘要时以「标题+摘要」为准；无摘要（老论文）只以标题为准——
        #    这样 ESPReSSO(SSO)/cembalo 之类无咖啡词的标题会被正确排除。
        scope = blob if abstract else title.lower()
        if not any(t in scope for t in _COFFEE_DOMAIN):
            return True
        # 4) must 词严格 AND（仅 Crossref 需要；OpenAlex 的 abstract.search 已内置 AND，
        #    且其匹配项的摘要可能因 abstract_inverted_index 缺失而无法本地重建，重检会误杀）。
        if enforce_must and not all(m in scope for m in must):
            return True
        return False

    def _mk(title, abstract, date, doi, authors, venue, evidence_level, otype, landing,
            enforce_must: bool = True):
        if _excluded(title, abstract, enforce_must):
            return
        if len(abstract) > 4000:
            abstract = abstract[:4000]
        # DOI 可能已是完整 URL（Crossref/OpenAlex 均返回 https://doi.org/...），
        # 避免重复拼接前缀导致 https://doi.org/https://doi.org/...
        if doi:
            link = doi if str(doi).startswith("http") else f"https://doi.org/{doi}"
        else:
            link = landing or ""
        items.append({
            "title": _clean(title),
            "summary": abstract,
            "published": (date or "")[:10],
            "source": source.get("name", "Academic"),
            "source_url": link,
            "link": link,
            "hint": "research",
            "doi": doi or "",
            "authors": authors,
            "venue": venue,
            "evidence_level": evidence_level,
            "otype": otype,
            "engagement": 0,
        })

    # —— OpenAlex ——
    try:
        # 注意：OpenAlex 过滤键是 abstract.search（点号），不是 abstract_search
        filters = [f"abstract.search:{t}" for t in must]
        if extra:
            filters.append(extra)
        params = {
            "filter": ",".join(filters),
            "per-page": per_page,
            "mailto": OPENALEX_MAILTO,
        }
        r = httpx.get(_OPENALEX_API, headers={"User-Agent": ua}, params=params,
                      timeout=30, follow_redirects=True)
        r.raise_for_status()
        for w in r.json().get("results", []):
            doi = (w.get("doi") or "").lower()
            if doi:
                if doi in seen_doi:
                    continue
                seen_doi.add(doi)
            abstract = _oa_reconstruct_abstract(w.get("abstract_inverted_index"))
            authors = [a.get("author", {}).get("display_name", "")
                       for a in w.get("authorships", [])][:6]
            venue = ((w.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
            landing = ((w.get("primary_location") or {}).get("landing_page_url")
                       or doi or "")
            _mk(w.get("title_display") or w.get("title") or "", abstract,
                w.get("publication_date") or "",
                doi, authors, venue, _oa_evidence_level(w), w.get("type") or "", landing,
                enforce_must=False)
    except Exception as e:
        _record_failure(failures, source, _OPENALEX_API, e, stage="academic-openalex")

    # —— Crossref（补足 OpenAlex 未覆盖的期刊，按 DOI 去重）——
    try:
        params = {
            "query": " ".join(must),
            "rows": per_page,
            "select": "title,DOI,abstract,issued,author,container-title,URL,type",
        }
        r = httpx.get(_CROSSREF_API, headers={"User-Agent": ua}, params=params,
                      timeout=30, follow_redirects=True)
        r.raise_for_status()
        for it in r.json().get("message", {}).get("items", []):
            doi = (it.get("DOI") or "").lower()
            if doi:
                if doi in seen_doi:
                    continue
                seen_doi.add(doi)
            title = " ".join(it.get("title", [])) if it.get("title") else ""
            abstract = _strip_jats(it.get("abstract"))
            # Crossref issued 日期
            parts = (it.get("issued", {}).get("date-parts") or [[]])[0]
            date = "-".join(str(p) for p in (parts or [])[:3])
            authors = [a.get("given", "") + " " + a.get("family", "")
                       for a in it.get("author", [])][:6]
            authors = [a.strip() for a in authors if a.strip()]
            venue = " ".join(it.get("container-title", []) or [])
            _mk(title, abstract, date, doi, authors, venue, "同行评审",
                it.get("type") or "", it.get("URL") or "")
    except Exception as e:
        _record_failure(failures, source, _CROSSREF_API, e, stage="academic-crossref")

    print(f"[fetch] 学术源 {source.get('name')}：{len(items)} 条（OpenAlex+Crossref 去重后）")
    return items


def fetch_all(cfg: dict | None = None, failures: list | None = None) -> list[dict]:
    """抓取全部启用源并归一化去重。

    `failures` 传入时由调用方（pipeline）持有并在全文抓取后统一落盘；
    不传则本函数自行创建并立即写报告（保持独立运行 `python -m src.fetch` 的行为）。
    """
    cfg = cfg or load_config()
    fcfg = cfg.get("fetch", {})
    lookback = fcfg.get("lookback_days", 3)
    tz = _resolve_tz(fcfg.get("timezone"))
    ua = fcfg.get("user_agent") or DEFAULT_UA
    delay = fcfg.get("per_source_delay") or 0
    sources = [s for s in cfg.get("sources", []) if s.get("enabled")]
    items: list[dict] = []
    own_failures = failures is None
    failures = [] if failures is None else failures
    t0 = time.time()
    for s in sources:
        # 每源可单独覆盖回看窗口（如 Reddit top 周榜需要更宽）
        st = time.time()
        lb = s.get("lookback_days", lookback)
        if s.get("type") == "rss":
            src_items = fetch_rss(s, lb, tz, user_agent=ua, failures=failures)
        elif s.get("type") == "search":
            src_items = fetch_search(s, lb, user_agent=ua, failures=failures)
        elif s.get("type") == "zhihu_cli":
            src_items = fetch_zhihu_cli(s, lb, failures=failures)
        elif s.get("type") == "academic":
            # 学术雷达：周级 CI 调用；每日 config 一般不含此类源
            src_items = fetch_academic(s, lb, user_agent=ua, failures=failures)
        else:
            # manual / 未实现：当前阶段以人工精选为主，标注跳过
            print(f"[fetch] 源 {s['name']}（{s.get('type')}）暂跳过，建议人工精选或接入搜索适配器。")
            continue
        # 源级关键词二次过滤（不耗 LLM），再并入总池
        src_items = _source_prefilter(s, src_items)
        items.extend(src_items)
        print(f"[fetch] 源 {s['name']}：{len(src_items)} 条 / {time.time()-st:.1f}s")
        # 礼貌抓取：每源间隔（0 或未配置则跳过）
        if delay:
            time.sleep(delay)
    # 抓取失败结构化记录（供阶段二质量报告）；由 pipeline 持有时延后统一落盘
    if own_failures:
        write_failure_report(failures)
    # 去重（按 link，空 link 按 title）
    seen = set()
    unique = []
    for it in items:
        key = it["link"] or it["title"]
        if key in seen:
            continue
        seen.add(key)
        unique.append(it)
    print(f"[fetch] 汇总：{len(sources)} 个启用源 → 原始 {len(items)} 条 → 去重后 {len(unique)} 条"
          f" / 失败 {len(failures)} 次 / 总耗时 {time.time()-t0:.1f}s")
    for rec in failures:
        print(f"[fetch]   失败记录：{rec.get('source')} | {rec.get('error_type')} | {rec.get('message')[:100]}")
    return unique


if __name__ == "__main__":
    for it in fetch_all():
        print(f"- [{it['published']}] ({it['source']}) {it['title']}")
