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
            out.append({
                "title": _clean(re.sub(r"<[^>]+>", "", title)),
                "summary": _clean(re.sub(r"<[^>]+>", "", desc)),
                "link": link,
                # source_url = 文章/视频链接（去重、卡片来源链接用）
                "source_url": link or source.get("url", ""),
                "published": dt.datetime.now().strftime("%Y-%m-%d"),
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
    import re
    if not html:
        return ""
    txt = re.sub(r"<[^>]+>", " ", html or "")
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
        _record_failure(
            failures, source, source.get("url", ""),
            Exception(f"feed parse error: {parsed['bozo_exception']}"),
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


def _record_failure(failures: list | None, source: dict, url: str, exc: Exception) -> None:
    """把一次抓取/解析失败结构化为记录，累积进 failures 列表并打印。

    字段：source / url / timestamp / error_type / status_code / rate_limited /
    blocked / message —— 供阶段二质量报告统计（每源失败率、是否限流等）。
    """
    rec = {
        "source": source.get("name", "") if isinstance(source, dict) else str(source),
        "url": url,
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
        if exc and any(k in text for k in exc):
            continue
        if inc and not any(k in text for k in inc):
            continue
        out.append(it)
    if len(out) != len(items):
        print(f"[fetch] 源 {source['name']} 关键词预过滤：{len(items)} → {len(out)} 条")
    return out


def _write_failure_report(failures: list) -> None:
    """把本次运行的抓取失败清单写入 reports/（按日期聚合，供质量报告消费）。"""
    if not failures:
        return
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
        print(f"[fetch] 已写入抓取失败报告：{path}（{len(failures)} 条）")
    except Exception as e:
        print(f"[fetch] 失败报告写入异常（不影响主流程）：{e}")


def fetch_all(cfg: dict | None = None) -> list[dict]:
    cfg = cfg or load_config()
    fcfg = cfg.get("fetch", {})
    lookback = fcfg.get("lookback_days", 3)
    tz = _resolve_tz(fcfg.get("timezone"))
    ua = fcfg.get("user_agent") or DEFAULT_UA
    delay = fcfg.get("per_source_delay") or 0
    sources = [s for s in cfg.get("sources", []) if s.get("enabled")]
    items: list[dict] = []
    failures: list[dict] = []
    for s in sources:
        # 每源可单独覆盖回看窗口（如 Reddit top 周榜需要更宽）
        lb = s.get("lookback_days", lookback)
        if s.get("type") == "rss":
            src_items = fetch_rss(s, lb, tz, user_agent=ua, failures=failures)
        elif s.get("type") == "search":
            src_items = fetch_search(s, lb, user_agent=ua, failures=failures)
        else:
            # manual / 未实现：当前阶段以人工精选为主，标注跳过
            print(f"[fetch] 源 {s['name']}（{s.get('type')}）暂跳过，建议人工精选或接入搜索适配器。")
            continue
        # 源级关键词二次过滤（不耗 LLM），再并入总池
        src_items = _source_prefilter(s, src_items)
        items.extend(src_items)
        # 礼貌抓取：每源间隔（0 或未配置则跳过）
        if delay:
            time.sleep(delay)
    # 抓取失败结构化记录（供阶段二质量报告）
    _write_failure_report(failures)
    # 去重（按 link，空 link 按 title）
    seen = set()
    unique = []
    for it in items:
        key = it["link"] or it["title"]
        if key in seen:
            continue
        seen.add(key)
        unique.append(it)
    return unique


if __name__ == "__main__":
    for it in fetch_all():
        print(f"- [{it['published']}] ({it['source']}) {it['title']}")
