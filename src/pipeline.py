"""每日管线：抓取 → LLM 评估/自动打标签 → 写入 content/ → 生成 public/。

用法:
    python -m src.pipeline                 # 抓取并发布（默认）
    python -m src.pipeline --dry-run       # 只打印将收录的内容，不写盘/不构建
    python -m src.pipeline --date 2026-08-03
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.content_loader import load_config, parse_frontmatter  # noqa: E402
from src import fetch as fetch_mod  # noqa: E402
from src import score as score_mod  # noqa: E402
from src import build as build_mod  # noqa: E402
from src import knowledge as knowledge_mod  # noqa: E402
from src import quality_report as quality_mod  # noqa: E402


# ---------------------------------------------------------------------------
# 来源配额（按 category_hint 分层），每期上限（阶段一 1.3）
#   技术实验 1–2 / 独立测试 1 / 专业教程 1 / 行业媒体 2 / 社区 2 / 官方公告事件触发
# 与 [llm].max_per_day（硬上限，默认 12）共同约束最终收录量。
# ---------------------------------------------------------------------------
LAYER_QUOTA = {
    "tech_experiment": 2,    # Barista Hustle / Scott Rao / Decent Espresso（3 源共享每期 2 条）
    "independent_review": 1, # CoffeeGeek
    "tutorial": 1,           # Clive Coffee（quota_group=gear_tutorials 合计 1；WLL 已停用）
    "industry": 2,           # Daily Coffee News / Perfect Daily Grind（Sprudge 已停用）
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
    t_start = time.time()
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

    # —— 启动摘要（诊断用）：确认 LLM 是否启用、key 是否存在、阈值 ——
    llm_cfg = cfg.get("llm", {})
    _llm_on = bool(llm_cfg.get("enabled"))
    _key_env = llm_cfg.get("api_key_env", "ESPRESSO_LLM_API_KEY")
    _key = os.getenv(_key_env, "").strip()
    print("=" * 60)
    print(f"[pipeline] 启动摘要：run_date={date_override or dt.datetime.now().strftime('%Y-%m-%d')}")
    print(f"[pipeline]   llm.enabled={_llm_on} | {_key_env} 已配置={'是' if _key else '否'}"
          f" | min_score={min_score} | max_per_day={max_per_day}")
    print(f"[pipeline]   启用源数={sum(1 for s in cfg.get('sources', []) if s.get('enabled'))}"
          f" | lookback_days={cfg.get('fetch', {}).get('lookback_days', 3)}")
    print("=" * 60)

    today = dt.datetime.now().strftime("%Y-%m-%d")
    run_date = date_override or today
    fcfg = cfg.get("fetch", {})
    ua = fcfg.get("user_agent") or fetch_mod.DEFAULT_UA
    # 全文抓取成本闸门（阶段二）：全文是稀缺资源，按预算/开关/间隔约束
    fulltext_enabled = bool(fcfg.get("fulltext_enabled", True))
    fulltext_budget = int(fcfg.get("fulltext_max_per_run", 12))
    fulltext_timeout = float(fcfg.get("fulltext_timeout", 20))
    fulltext_delay = float(fcfg.get("fulltext_delay", 0)) or 0
    ft_count = 0

    # 抓取失败清单由 pipeline 持有，全文抓取结束后统一落盘（阶段二质量报告消费）
    failures: list[dict] = []
    t_fetch = time.time()
    items = fetch_mod.fetch_all(cfg, failures=failures)
    print(f"[pipeline] 阶段一 抓取：{len(items)} 条候选 / 耗时 {time.time()-t_fetch:.1f}s")
    existing = _existing_keys(content_dir)
    print(f"[pipeline] 已收录去重键：{len(existing)} 个")

    # 基础/常青知识库：加载一次，供每条新闻注入背景上下文（最全面、无额外依赖）
    knowledge_entries = knowledge_mod.load_knowledge(cfg)
    if knowledge_entries:
        print(f"[pipeline] 已加载常青知识库 {len(knowledge_entries)} 个主题（作为深度解读背景）")

    # 运行质量报告（阶段二）：贯穿整轮，最后落盘
    quality = quality_mod.QualityReport(cfg, run_date)

    # —— 1) 两阶段评估：初筛（便宜闸门）→ 按需全文 → 多维精评 ——
    #    源级关键词预过滤已在 fetch 层完成；这里先初筛淘汰不值钱的内容，
    #    再对「白名单 + 初筛通过」的条目抓全文（稀缺资源），最后精评。
    judged = []
    n_prescreen_pass = n_prescreen_reject = 0
    n_score_reject = 0
    n_llm_engine = n_rule_engine = 0
    n_fulltext_ok = n_fulltext_fail = 0
    prescreen_reasons: dict[str, int] = {}
    for it in items:
        hint = it.get("hint", "mixed")

        # Pass 1：初筛（LLM 优先，未启用回退关键词）
        pre = score_mod.prescreen(it, cfg, hint)
        quality.record_candidate(it, pre.get("espresso_core", False))
        if not pre["accept"]:
            print(f"[pipeline] 初筛拒 [{pre.get('engine','?')}] {it.get('source','')}："
                  f"{it['title'][:60]} —— {pre.get('reason','')}")
            quality.record_reject(it, pre["reason"], "prescreen")
            n_prescreen_reject += 1
            prescreen_reasons[pre.get("reason") or "未知"] = prescreen_reasons.get(pre.get("reason") or "未知", 0) + 1
            continue
        n_prescreen_pass += 1

        # Pass 1.5：按需全文抓取（仅白名单源；稀缺资源，初筛通过才抓，受预算约束）
        if (fulltext_enabled and it.get("allow_full_text") and it.get("link")
                and ft_count < fulltext_budget):
            ft = fetch_mod.fetch_full_article(
                {"name": it.get("source", "")}, it["link"],
                user_agent=ua, failures=failures, timeout=fulltext_timeout,
            )
            if ft:
                it["full_text"] = ft
                ft_count += 1
                n_fulltext_ok += 1
                if fulltext_delay:
                    time.sleep(fulltext_delay)
            else:
                n_fulltext_fail += 1

        # Pass 2：多维精评（按 content_type + lang 选维度集；有全文则基于全文，避免虚构参数）
        kb_ctx = knowledge_mod.build_context(it, knowledge_entries, cfg)
        j = score_mod.judge(
            it, cfg, hint=hint, knowledge_ctx=kb_ctx,
            content_type=pre["content_type"],
        )
        j.prescreen_reason = pre["reason"]
        if pre.get("engine") == "llm":
            n_llm_engine += 1
        else:
            n_rule_engine += 1
        _dims = j.dims or {}
        _ft = "全文" if it.get("full_text") else "摘要"
        _d = " | ".join(f"{k}={_dims.get(k, 0)}" for k in score_mod.dim_keys(j.content_type))
        if j.score < min_score:
            print(f"[pipeline] 精评拒 [{j.score}分<{min_score} | {_ft} | {_d}] "
                  f"{it.get('source','')}：{it['title'][:60]}")
            quality.record_reject(it, f"score {j.score} < {min_score}", "score")
            n_score_reject += 1
            continue
        print(f"[pipeline] 精评过 [{j.score}分 | {_ft} | {_d}] {it.get('source','')}：{it['title'][:60]}")

        date = date_override or it.get("published") or today
        it["date"] = date
        it["tags"] = []
        key_url = ("url", it["source_url"]) if it.get("source_url") else None
        key_title = ("title", it["title"])
        if (key_url and key_url in existing) or key_title in existing:
            print(f"[pipeline] 跳过重复：{it['title']}")
            quality.record_reject(it, "已收录（去重）", "dedup")
            quality.dedup_skipped += 1
            continue
        judged.append((date, it, j))
        quality.record_accept(it, j)

    print(f"[pipeline] 阶段二 初筛：通过 {n_prescreen_pass} / 拒绝 {n_prescreen_reject}"
          f"（理由分布：{dict(sorted(prescreen_reasons.items(), key=lambda kv: -kv[1]))}）")
    print(f"[pipeline] 阶段三 全文抓取：成功 {n_fulltext_ok} / 失败 {n_fulltext_fail}")
    print(f"[pipeline] 阶段四 精评引擎：LLM {n_llm_engine} / 规则 {n_rule_engine}"
          f" | 低于 min_score({min_score}) 被拒 {n_score_reject}")

    # —— 2) 48h 事件聚类：同题只留最完整一条，其余折叠进 related ——
    before = len(judged)
    judged = score_mod.cluster_events(judged, window_hours=48)
    quality.cluster_folds += (before - len(judged))

    # —— 3) 排序：评分降序；社区类按互动量（赞/评论）做同分 tiebreaker ——
    judged.sort(key=lambda t: (t[2].score, t[1].get("engagement", 0)), reverse=True)

    # —— 4) 配额 + 硬上限（按 category_hint 分层 + 每源/每组上限 + max_per_day）——
    selected = _apply_quota(judged, cfg)
    if len(judged) != len(selected):
        print(f"[pipeline] 配额过滤：{len(judged)} 条候选 → 选中 {len(selected)} 条")

    # —— 5) 生成 Markdown（仅对最终入选者，避免为被淘汰项浪费 LLM/算力）——
    accepted = [(date, it, j, j.to_markdown(it)) for date, it, j in selected]

    # —— 每日总标题（headline）：按日聚合生成，供归档列表/首页近期卡片使用 ——
    headlines = _generate_headlines(cfg, accepted, content_dir)

    # —— 运行质量报告 + 抓取失败落盘（阶段二，始终产出；reports/ 已 gitignore）——
    fetch_mod.write_failure_report(failures)
    quality.merge_failures(failures)
    quality.write()

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
    print(f"[pipeline] 完成，新增 {written} 条，总标题 {headline_written} 个。"
          f"（总耗时 {time.time()-t_start:.1f}s）")


def main():
    ap = argparse.ArgumentParser(description="espresso-daily 每日管线")
    ap.add_argument("--config", default="config.toml")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    run(args.config, dry_run=args.dry_run, date_override=args.date)


if __name__ == "__main__":
    main()
