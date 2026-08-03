"""静态站生成器：读 content/ -> 渲染 public/。

用法:
    python -m src.build            # 使用 config.toml（缺失则 config.example.toml）
    python -m src.build --config config.toml
"""
from __future__ import annotations

import argparse
import datetime
import os
import re
import shutil
import sys
import urllib.parse

from jinja2 import Environment, FileSystemLoader, select_autoescape

# 允许以脚本或模块方式运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.content_loader import (  # noqa: E402
    load_config,
    load_entries,
    load_day_headlines,
    build_months,
    build_tag_index,
    filter_by_date,
    filter_by_tag,
)


def _env(templates_dir: str) -> Environment:
    return Environment(
        loader=FileSystemLoader(templates_dir),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def build(config_path: str = "config.toml"):
    cfg = load_config(config_path)
    site = cfg["site"]
    content_dir = site["content_dir"]
    out_dir = site["output_dir"]
    # 前端展示开关：是否显示标签功能（筛选 / 标签云 / 标签页）
    # 观察期硬约束：默认关闭（config.toml 漏写 [ui] 段也不应意外显示），
    # 待实测观察标签质量后再改回 true。
    show_tags = bool(cfg.get("ui", {}).get("show_tags", False))

    entries = load_entries(content_dir)
    # 每日总标题（LLM 生成，content/{date}-00.md）：归档列表/首页近期卡片优先使用，
    # 缺失日期回退当日最高分条目标题（现状行为）。
    day_headlines = load_day_headlines(content_dir)
    # 阅读时长：基于正文字数（含深度解读），约 350 字/分钟，至少 1 分钟
    for _e in entries:
        _chars = len(_e.get("body_text", ""))
        _dive = _e.get("deepdive_html", "")
        if _dive:
            _chars += len(re.sub(r"<[^>]+>", "", _dive))
        _e["reading_time"] = max(1, (_chars + 349) // 350)
    months = build_months(entries)
    all_tags = build_tag_index(entries) if show_tags else []
    latest_date = entries[0]["date"] if entries else "—"
    total = len(entries)

    # —— 首页「日报仪表盘」所需数据 ——
    # 日期全集（倒序，已去重）
    seen_dates = []
    for e in entries:
        if e["date"] not in seen_dates:
            seen_dates.append(e["date"])
    days_covered = len(seen_dates)

    today = latest_date
    today_entries = [e for e in entries if e["date"] == today]
    today_total_time = sum(e.get("reading_time", 0) for e in today_entries)
    # 今日精选：按编辑评分取前 2（首页直出全文）
    featured = sorted(today_entries, key=lambda e: e.get("score", 0), reverse=True)[:2]
    # 今日其余条目（非精选）：供今日入口条预览，避免与上方精选全文标题重复
    today_rest = [e for e in today_entries if e not in featured]

    _wd = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

    def _weekday(d: str) -> str:
        try:
            return _wd[datetime.date.fromisoformat(d).weekday()]
        except Exception:
            return ""

    today_weekday = _weekday(today)
    today_topscore = max((e.get("score", 0) for e in today_entries), default=0)

    # 近期日报：今日之前最近 6 天，每天一个摘要卡（预览列多条标题）
    recent_days = []
    for d in [x for x in seen_dates if x != today][:6]:
        day_es = [e for e in entries if e["date"] == d]
        top = max(day_es, key=lambda e: e.get("score", 0))
        ranked = sorted(day_es, key=lambda e: e.get("score", 0), reverse=True)
        recent_days.append({
            "date": d,
            "day": f"{d[5:7]}.{d[8:]}",      # 「08.02」单一日号，不再与完整日期重复
            "weekday": _weekday(d),
            "headline": day_headlines.get(d, top["title"]),
            "count": len(day_es),
            "topscore": top.get("score", 0),
            "link": f"days/{d}.html",
            "titles": [{"title": e["title"], "score": e.get("score", 0),
                        "dive": bool(e.get("deepdive_html"))} for e in ranked[:3]],
        })

    # 归档页：年 → 月嵌套树（年份收敛到目录与月标题，行内不再重复）
    archive_tree = []
    for _m in months:  # months 已按日期倒序（最新在前）
        ym = _m["label"]
        year, mon = ym[:4], ym[5:]
        day_set = list(dict.fromkeys(e["date"] for e in _m["days"]))
        days = []
        for d in day_set:
            de = [e for e in entries if e["date"] == d]
            top = max(de, key=lambda e: e.get("score", 0))
            days.append({
                "date": d, "day": d[8:], "weekday": _weekday(d),
                "headline": day_headlines.get(d, top["title"]), "count": len(de),
            })
        node = next((y for y in archive_tree if y["year"] == year), None)
        if node is None:
            node = {"year": year, "days": 0, "count": 0, "months": []}
            archive_tree.append(node)
        month_count = sum(x["count"] for x in days)
        node["months"].append({"label": ym, "month": mon, "days": days, "count": month_count})
        node["days"] += len(days)
        node["count"] += month_count
    archive_stats = {
        "count": total,
        "days": days_covered,
        "months": sum(len(y["months"]) for y in archive_tree),
        "years": len(archive_tree),
    }

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    templates_dir = os.path.join(root, "src", "templates")
    env = _env(templates_dir)

    # 清空并重建输出目录（days/tags/assets 由构建重新生成）
    # 注意：部分受限环境会拦截 rmtree（安全删除沙箱），这里做容错——
    # 删除失败时改为清空目录内文件，保证构建不中断。
    out_abs = os.path.join(root, out_dir)
    for sub in ("days", "tags", "assets"):
        d = os.path.join(out_abs, sub)
        if os.path.isdir(d):
            try:
                shutil.rmtree(d)
            except Exception:
                # 容错：逐文件删除（兼容无法 rmtree 的环境）
                for fn in os.listdir(d):
                    try:
                        os.remove(os.path.join(d, fn))
                    except Exception:
                        pass
        os.makedirs(d, exist_ok=True)

    # 复制静态资源
    assets_src = os.path.join(root, "assets")
    assets_dst = os.path.join(out_abs, "assets")
    for f in os.listdir(assets_src):
        shutil.copy2(os.path.join(assets_src, f), os.path.join(assets_dst, f))

    # 缓存失效版本号：按资源文件 mtime 精确取值，模板里 ?v={{ asset_ver('app.js') }} 使用
    def _asset_ver(fn: str) -> str:
        try:
            return str(int(os.path.getmtime(os.path.join(assets_src, fn))))
        except OSError:
            return "0"

    base_ctx = dict(site=site, months=months,
                    all_tags=all_tags, latest_date=latest_date, total=total,
                    days_covered=days_covered, latest_weekday=_weekday(latest_date),
                    show_tags=show_tags, asset_ver=_asset_ver)

    # 首页（日报仪表盘）
    idx = env.get_template("index.html").render(
        entries=entries, rel="",
        today=today, today_entries=today_entries, featured=featured,
        today_rest=today_rest,
        today_weekday=today_weekday,
        issue_num=days_covered, today_total_time=today_total_time,
        recent_days=recent_days, **base_ctx)
    with open(os.path.join(out_abs, "index.html"), "w", encoding="utf-8") as f:
        f.write(idx)
    print(f"[build] index.html  ({total} 条)")

    # 归档页（年-月索引 · 双栏布局）
    arch = env.get_template("archive.html").render(
        rel="", archive_tree=archive_tree, archive_stats=archive_stats, **base_ctx)
    with open(os.path.join(out_abs, "archive.html"), "w", encoding="utf-8") as f:
        f.write(arch)
    print(f"[build] archive.html  ({archive_stats['months']} 个月 / {archive_stats['years']} 年)")

    # 单日页
    for i, date in enumerate(seen_dates):
        day_entries = filter_by_date(entries, date)
        # seen_dates 倒序（最新在前）：上一日=更早(idx+1)，下一日=更新(idx-1)
        prev_date = seen_dates[i + 1] if i + 1 < len(seen_dates) else None
        next_date = seen_dates[i - 1] if i - 1 >= 0 else None
        html = env.get_template("day.html").render(
            date=date, entries=day_entries, rel="../",
            prev_date=prev_date, next_date=next_date, **base_ctx)
        with open(os.path.join(out_abs, "days", f"{date}.html"), "w", encoding="utf-8") as f:
            f.write(html)
    print(f"[build] days: {len(seen_dates)} 个日期页")

    # 标签页（动态标签，替代固定分类页）：每个标签一个页面
    tag_tpl = env.get_template("tag.html")
    for tag in all_tags:
        name = tag["name"]
        slug = urllib.parse.quote(name, safe="")
        tag_entries = filter_by_tag(entries, name)
        html = tag_tpl.render(
            tag_name=name, tag_count=len(tag_entries),
            entries=tag_entries, rel="../", **base_ctx)
        with open(os.path.join(out_abs, "tags", f"{slug}.html"), "w", encoding="utf-8") as f:
            f.write(html)
    print(f"[build] tags: {len(all_tags)} 个标签页")

    print(f"[build] 完成 -> {out_dir}/")
    return out_abs


def main():
    ap = argparse.ArgumentParser(description="生成 espresso-daily 静态站")
    ap.add_argument("--config", default="config.toml")
    args = ap.parse_args()
    build(args.config)


if __name__ == "__main__":
    main()
