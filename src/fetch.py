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
import re
import zoneinfo
from datetime import datetime, timezone

import feedparser
import httpx

from src.content_loader import load_config


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


def fetch_search(source: dict, lookback_days: int = 3) -> list[dict]:
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
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
        print(f"[fetch] 源 {source['name']} 搜索抓取失败：{e}")
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


def fetch_rss(source: dict, lookback_days: int = 3, tz=None) -> list[dict]:
    ua = "EspressoDaily/0.1 (+https://github.com/your-org/espresso-daily)"
    try:
        resp = httpx.get(source["url"], headers={"User-Agent": ua}, timeout=20, follow_redirects=True)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
    except Exception as e:
        print(f"[fetch] 源 {source['name']} 抓取失败：{e}")
        return []

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
            "title": (e.get("title") or "").strip(),            "summary": _clean(e.get("summary") or e.get("description")),
            "link": e.get("link", ""),
            # source_url = 文章链接（去重、卡片来源链接用）；空链接回退源站地址
            "source_url": e.get("link", "") or source.get("url", ""),
            "published": date or dt.datetime.now().strftime("%Y-%m-%d"),
            "source": source["name"],
            "lang": source.get("lang", ""),
            "hint": source.get("category_hint", "mixed"),
        })
    print(f"[fetch] 源 {source['name']}：{len(items)} 条（近 {lookback_days} 天）")
    return items


def fetch_all(cfg: dict | None = None) -> list[dict]:
    cfg = cfg or load_config()
    lookback = cfg.get("fetch", {}).get("lookback_days", 3)
    tz = _resolve_tz(cfg.get("fetch", {}).get("timezone"))
    sources = [s for s in cfg.get("sources", []) if s.get("enabled")]
    items: list[dict] = []
    for s in sources:
        if s.get("type") == "rss":
            items.extend(fetch_rss(s, lookback, tz))
        elif s.get("type") == "search":
            items.extend(fetch_search(s, lookback))
        else:
            # manual / 未实现：当前阶段以人工精选为主，标注跳过
            print(f"[fetch] 源 {s['name']}（{s.get('type')}）暂跳过，建议人工精选或接入搜索适配器。")
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
