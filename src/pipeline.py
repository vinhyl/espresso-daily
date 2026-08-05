"""每日管线：抓取 → LLM 评估/自动打标签 → 写入 content/ → 生成 public/。

用法:
    python -m src.pipeline                 # 抓取并发布（默认）
    python -m src.pipeline --dry-run       # 只打印将收录的内容，不写盘/不构建
    python -m src.pipeline --date 2026-08-03
"""
from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.content_loader import load_config, parse_frontmatter  # noqa: E402
from src import fetch as fetch_mod  # noqa: E402
from src import score as score_mod  # noqa: E402
from src import build as build_mod  # noqa: E402
from src import knowledge as knowledge_mod  # noqa: E402


# ---------------------------------------------------------------------------
# 来源配额（按 category_hint 分层），每期上限（阶段一 1.3）
#   技术实验 1–2 / 独立测试 1 / 专业教程 1 / 行业媒体 2 / 社区 2 / 官方公告事件触发
# 与 [llm].max_per_day（硬上限，默认 12）共同约束最终收录量。
# ---------------------------------------------------------------------------
LAYER_QUOTA = {
    "tech_experiment": 2,    # Barista Hustle / Coffee Ad Astra
    "independent_review": 1, # CoffeeGeek
    "tutorial": 1,           # Whole Latte Love / Clive（两源再受 quota_group 合计 1 约束）
    "industry": 2,           # Daily Coffee News / Perfect Daily Grind / Sprudge
    "community": 2,          # Reddit r/espresso
    "official": 999,         # 官方公告（事件触发，不硬限）
}


def _existing_keys(content_dir: str):
    """返回已收录内容的去重键集合（source_url 或 title）。

    跳过「每日总标题」sidecar（{date}-00.md / kind: headline）——合成标题
    不参与去重，避免误杀同名真实条目。
    """
    keys = set()
    if not os.path.isdir(content_dir):
        return keys
    for fn in os.listdir(content_dir):
        if not fn.endswith(".md"):
            continue
        if fn.endswith("-00.md"):
            continue  # headline sidecar，按命名兜底跳过
        with open(os.path.join(content_dir, fn), encoding="utf-8") as f:
            meta, _ = parse_frontmatter(f.read())
        if meta.get("kind") == "headline":
            continue  # 双保险：显式 kind 标记也跳过
        if meta.get("source_url"):
            keys.add(("url", meta["source_url"]))
        if meta.get("title"):
            keys.add(("title", meta["title"]))
    return keys


def _next_entry_numbers(content_dir: str) -> dict[str, int]:
    """扫描 content/ 已有条目，返回 {date: 当日已用最大编号}（排除 -00.md headline）。

    防止同一天重复运行管线时，per_date_count 从 0 重新计数而覆盖已有
    {date}-01.md、{date}-02.md 等文件（如 `--date` 手动补跑 / CI 当天重试）。
    只匹配 pipeline 命名 {date}-NN.md（NN>=1），旧式 {date}-kind-slug.md 不匹配。
    """
    nums: dict[str, int] = {}
    if not os.path.isdir(content_dir):
        return nums
    pat = re.compile(r"^(\d{4}-\d{2}-\d{2})-(\d{2})\.md$")
    for fn in os.listdir(content_dir):
        m = pat.match(fn)
        if not m:
            continue
        n = int(m.group(2))
        if n <= 0:
            continue  # -00.md = headline sidecar
        date = m.group(1)
        nums[date] = max(nums.get(date, 0), n)
    return nums


def _headline_markdown(date: str, headline: str) -> str:
    """生成「每日总标题」sidecar 的 Markdown（content/{date}-00.md）。"""
    return (
        "---\n"
        f"date: {date}\n"
        "kind: headline\n"
        f"title: {headline}\n"
        f"headline: {headline}\n"
        "---\n"
    )


def _apply_quota(judged: list, cfg: dict) -> list:
    """按 category_hint 分层配额 + 每源/每组上限 + max_per_day 硬上限做裁剪。

    输入 judged 已按 (score 降序, engagement 降序) 排序；这里贪心选取：
    - 每层累计不超过 LAYER_QUOTA（未知 hint 归入 industry）；
    - 同 source 累计不超过其 max_per_source；
    - 同 quota_group 累计不超过其 max_per_group（如 WLL+Clive 合计 1）；
    - 总数不超过 max_per_day（硬上限）。
    返回选中的 (date, it, j) 三元组列表（不含 markdown，由调用方生成）。
    """
    quotas = dict(LAYER_QUOTA)
    max_per_day = int(cfg.get("llm", {}).get("max_per_day", 12))
    accepted: list = []
    layer_count: dict[str, int] = {}
    source_count: dict[str, int] = {}
    group_count: dict[str, int] = {}
    for date, it, j in judged:
        layer = it.get("hint") or "industry"
        if layer not in quotas:
            layer = "industry"
        if layer_count.get(layer, 0) >= quotas[layer]:
            continue
        src = it.get("source", "")
        mps = it.get("max_per_source")
        if mps and source_count.get(src, 0) >= int(mps):
            continue
        grp = it.get("quota_group")
        mpg = it.get("max_per_group")
        if grp and mpg and group_count.get(grp, 0) >= int(mpg):
            continue
        accepted.append((date, it, j))
        layer_count[layer] = layer_count.get(layer, 0) + 1
        if src:
            source_count[src] = source_count.get(src, 0) + 1
        if grp:
            group_count[grp] = group_count.get(grp, 0) + 1
        if len(accepted) >= max_per_day:
            break
    return accepted


def _generate_headlines(cfg: dict, accepted: list, content_dir: str) -> dict[str, str]:
    """按日期聚合已收录条目，为每个日期生成「每日总标题」。

    - 仅当 llm.enabled 且 headline_enabled 时调用 LLM；否则不生成（构建期回退
      当日最高分条目标题，行为与现状一致）。
    - {date}-00.md 已存在则跳过（幂等，保留人工编辑），并把已有 headline 读回，
      供 dry-run 预览。
    - 返回本次可写盘的 {date: headline}。
    """
    llm = cfg.get("llm", {})
    use_llm = bool(llm.get("enabled")) and bool(llm.get("headline_enabled", True))
    by_date: dict[str, list] = {}
    for date, it, j, _md in accepted:
        item = dict(it)  # 浅拷贝，避免污染原 item
        item["score"] = j.score
        item["processed_summary"] = j.summary
        by_date.setdefault(date, []).append(item)

    result: dict[str, str] = {}
    for date, day_items in by_date.items():
        path = os.path.join(content_dir, f"{date}-00.md")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                meta, _ = parse_frontmatter(f.read())
            headline = str(meta.get("headline") or meta.get("title") or "").strip()
            if headline:
                result[date] = headline
                print(f"[pipeline] {date} headline 已存在，跳过生成：{headline}")
            continue
        if not use_llm:
            print(f"[pipeline] {date} 未启用 LLM 总标题（llm.enabled/headline_enabled），跳过")
            continue
        headline = score_mod.call_llm_headline(cfg, day_items)
        if not headline:
            print(f"[pipeline] {date} headline 生成失败/为空，回退构建期派生（最高分标题）")
            continue
        result[date] = headline
    return result


def run(config_path: str = "config.toml", dry_run: bool = False, date_override: str | None = None):
    cfg = load_config(config_path)
    # 环境变量可强制启用 LLM（CI/定时任务用）：ESPRESSO_LLM_ENABLED=1|true|yes
    # 允许 workflow 在不修改 config.toml 的情况下启用 LLM（API key 走 ESPRESSO_LLM_API_KEY）。
    _env_llm = os.getenv("ESPRESSO_LLM_ENABLED", "").strip().lower()
    if _env_llm in ("1", "true", "yes", "on"):
        cfg.setdefault("llm", {})["enabled"] = True
    site = cfg["site"]
    content_dir = site["content_dir"]
    min_score = cfg.get("llm", {}).get("min_score", 60)
    max_per_day = cfg.get("llm", {}).get("max_per_day", 30)

    items = fetch_mod.fetch_all(cfg)
    existing = _existing_keys(content_dir)

    # 基础/常青知识库：加载一次，供每条新闻注入背景上下文（最全面、无额外依赖）
    knowledge_entries = knowledge_mod.load_knowledge(cfg)
    if knowledge_entries:
        print(f"[pipeline] 已加载常青知识库 {len(knowledge_entries)} 个主题（作为深度解读背景）")

    # —— 1) 评估所有存活条目（规则回退快；LLM 启用时也先评估再配额）——
    #    源级关键词预过滤已在 fetch 层完成，这里不再被无关内容浪费 LLM/算力。
    judged = []
    for it in items:
        kb_ctx = knowledge_mod.build_context(it, knowledge_entries, cfg)
        j = score_mod.judge(it, cfg, hint=it.get("hint", "mixed"), knowledge_ctx=kb_ctx)
        if j.score < min_score:
            continue
        date = date_override or it.get("published") or __import__("datetime").datetime.now().strftime("%Y-%m-%d")
        it["date"] = date
        it["tags"] = []
        key_url = ("url", it["source_url"]) if it.get("source_url") else None
        key_title = ("title", it["title"])
        if (key_url and key_url in existing) or key_title in existing:
            print(f"[pipeline] 跳过重复：{it['title']}")
            continue
        judged.append((date, it, j))

    # —— 2) 排序：评分降序；社区类按互动量（赞/评论）做同分 tiebreaker ——
    judged.sort(key=lambda t: (t[2].score, t[1].get("engagement", 0)), reverse=True)

    # —— 3) 配额 + 硬上限（按 category_hint 分层 + 每源/每组上限 + max_per_day）——
    selected = _apply_quota(judged, cfg)
    if len(judged) != len(selected):
        print(f"[pipeline] 配额过滤：{len(judged)} 条候选 → 选中 {len(selected)} 条")

    # —— 4) 生成 Markdown（仅对最终入选者，避免为被淘汰项浪费 LLM/算力）——
    accepted = [(date, it, j, j.to_markdown(it)) for date, it, j in selected]

    # —— 每日总标题（headline）：按日聚合生成，供归档列表/首页近期卡片使用 ——
    headlines = _generate_headlines(cfg, accepted, content_dir)

    if dry_run:
        print(f"\n[dry-run] 将收录 {len(accepted)} 条：")
        for date, it, j, _ in accepted:
            dd = " · 深度解读✓" if j.deepdive else ""
            print(f"  {date}  kind={j.kind:<9} [{','.join(j.tags)}]{dd} {it['title']}")
        if headlines:
            print("\n[dry-run] 每日总标题：")
            for date, h in sorted(headlines.items()):
                print(f"  {date}  {h}")
        return

    # 写入 content/（续号：从当天已有最大编号 +1 开始，避免覆盖已有文件）
    os.makedirs(content_dir, exist_ok=True)
    written = 0
    next_nums = _next_entry_numbers(content_dir)
    for date, it, j, md in accepted:
        n = next_nums.get(date, 0) + 1
        next_nums[date] = n
        path = os.path.join(content_dir, f"{date}-{n:02d}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(md + "\n")
        written += 1
        print(f"[pipeline] 写入 {os.path.basename(path)}  [{','.join(j.tags)}]")

    # 写入每日总标题 sidecar（{date}-00.md，kind: headline；已存在则上面已跳过）
    headline_written = 0
    for date, headline in headlines.items():
        path = os.path.join(content_dir, f"{date}-00.md")
        if os.path.exists(path):
            continue
        with open(path, "w", encoding="utf-8") as f:
            f.write(_headline_markdown(date, headline))
        headline_written += 1
        print(f"[pipeline] 写入 {os.path.basename(path)}  [每日总标题]")

    # 生成静态站
    if written:
        build_mod.build(config_path)
    print(f"[pipeline] 完成，新增 {written} 条，总标题 {headline_written} 个。")


def main():
    ap = argparse.ArgumentParser(description="espresso-daily 每日管线")
    ap.add_argument("--config", default="config.toml")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    run(args.config, dry_run=args.dry_run, date_override=args.date)


if __name__ == "__main__":
    main()
