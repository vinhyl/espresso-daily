"""重新评分脚本：用新评分机制对 content/ 已有条目重新打分，输出新旧对比。

模拟完整流程（prescreen 初筛 → judge 精评），验证新机制对旧内容的判分变化。
默认走规则回退（无需 API key）；设置 ESPRESSO_LLM_ENABLED=1 可启用 LLM 精评。

用法：
    .venv/bin/python scripts/rescore.py
    ESPRESSO_LLM_ENABLED=1 .venv/bin/python scripts/rescore.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.content_loader import parse_frontmatter, load_config
from src import score as score_mod


def _source_to_hint(cfg: dict) -> dict[str, str]:
    """从 config 的 sources 构建 source name → hint 映射。"""
    mapping = {}
    for s in cfg.get("sources", []):
        name = s.get("name", "")
        hint = s.get("category_hint", "mixed")
        if name:
            mapping[name] = hint
    return mapping


def _load_content_files(content_dir: str) -> list[dict]:
    """读取 content/ 所有条目（排除 -00.md headline）。

    用正文（去掉深度解读区块）作为 summary 传入评分。
    """
    items = []
    for fn in sorted(os.listdir(content_dir)):
        if not fn.endswith(".md") or fn.endswith("-00.md"):
            continue
        path = os.path.join(content_dir, fn)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        meta, body = parse_frontmatter(text)
        if meta.get("kind") == "headline":
            continue
        if not meta.get("date") or not meta.get("title"):
            continue
        # 去掉深度解读区块，只保留主正文作为评分材料
        main_body = body.split("## 深度解读")[0].strip()
        items.append({
            "file": fn,
            "title": meta.get("title", ""),
            "summary": main_body,
            "source": meta.get("source", ""),
            "source_url": meta.get("source_url", ""),
            "lang": meta.get("lang", ""),
            "published": meta.get("date", ""),
            "old_score": int(meta.get("score", 0) or 0),
            "old_content_type": meta.get("content_type", ""),
        })
    return items


def main():
    cfg = load_config("config.toml")
    # 默认强制规则回退；环境变量可启用 LLM
    _env_llm = os.getenv("ESPRESSO_LLM_ENABLED", "").strip().lower()
    use_llm = _env_llm in ("1", "true", "yes", "on")
    cfg.setdefault("llm", {})["enabled"] = use_llm

    content_dir = cfg["site"]["content_dir"]
    source_hint = _source_to_hint(cfg)

    items = _load_content_files(content_dir)
    engine = "LLM 精评" if use_llm else "规则回退"
    print(f"[rescore] 加载 {len(items)} 条内容 | 引擎={engine} | min_score={cfg.get('llm',{}).get('min_score',60)}")
    print("=" * 130)

    results = []
    for it in items:
        hint = source_hint.get(it["source"], "mixed")
        # Pass 1：初筛
        pre = score_mod.prescreen(it, cfg, hint)
        # Pass 2：精评（初筛通过才评）
        if pre["accept"]:
            j = score_mod.judge(it, cfg, hint=hint, content_type=pre["content_type"])
            results.append({
                "file": it["file"],
                "title": it["title"],
                "source": it["source"],
                "old_score": it["old_score"],
                "prescreen": "通过",
                "new_score": j.score,
                "content_type": j.content_type,
                "dims": j.dims or {},
                "vetoed": score_mod._relevance_vetoed(j),
            })
        else:
            results.append({
                "file": it["file"],
                "title": it["title"],
                "source": it["source"],
                "old_score": it["old_score"],
                "prescreen": f"拒：{pre['reason'][:24]}",
                "new_score": 0,
                "content_type": pre.get("content_type", ""),
                "dims": {},
                "vetoed": False,
            })

    # ---- 明细表 ----
    print(f"\n{'文件':<22} {'旧分':>4} {'初筛':<28} {'新分':>4} {'类型':<12} {'维度明细'}")
    print("-" * 130)
    for r in results:
        dims_str = " | ".join(f"{k}={v}" for k, v in r["dims"].items()) if r["dims"] else "—"
        ct_short = r["content_type"][:12]
        veto = " [否决]" if r["vetoed"] else ""
        print(f"{r['file']:<22} {r['old_score']:>4} {r['prescreen']:<28} {r['new_score']:>4} {ct_short:<12} {dims_str}{veto}")

    # ---- 统计摘要 ----
    print("\n" + "=" * 130)
    n_total = len(results)
    n_reject = sum(1 for r in results if r["prescreen"] != "通过")
    n_pass = n_total - n_reject
    n_veto = sum(1 for r in results if r["vetoed"])
    min_score = cfg.get("llm", {}).get("min_score", 60)
    n_below_min = sum(1 for r in results if r["prescreen"] == "通过" and r["new_score"] < min_score)
    n_would_publish = n_pass - n_below_min
    print(f"[统计] 总数 {n_total} | 初筛拒 {n_reject} | 初筛通过 {n_pass}"
          f" | relevance否决 {n_veto} | 通过但<{min_score}分 {n_below_min}"
          f" | 最终可发布 {n_would_publish}")

    # 分数变化分布（仅通过条目）
    changes = [r["new_score"] - r["old_score"] for r in results if r["prescreen"] == "通过"]
    if changes:
        print(f"[分数变化] 通过条目 新分-旧分：min={min(changes)} max={max(changes)} avg={sum(changes)/len(changes):+.1f}")

    # ---- 典型变化：旧分高但新分低/被拒 ----
    print("\n[典型变化] 旧分≥70 但新分<60 或被初筛拒的条目（新机制应拦下的旧问题内容）：")
    flagged = False
    for r in results:
        if r["old_score"] >= 70 and (r["new_score"] < 60 or r["prescreen"] != "通过"):
            print(f"  {r['file']} | {r['title'][:42]} | 旧{r['old_score']} → 新{r['new_score']}（{r['prescreen']}）")
            flagged = True
    if not flagged:
        print("  （无）")

    # ---- 被初筛拒的条目明细 ----
    if n_reject:
        print(f"\n[初筛拒绝明细] 共 {n_reject} 条：")
        for r in results:
            if r["prescreen"] != "通过":
                print(f"  {r['file']} | 旧{r['old_score']}分 | {r['prescreen']} | {r['title'][:40]}")

    # ---- 新分≥85 的条目（新机制应识别出的优质内容）----
    high = [r for r in results if r["new_score"] >= 85]
    if high:
        print(f"\n[新分≥85] 共 {len(high)} 条（新机制识别出的强证据内容）：")
        for r in high:
            print(f"  {r['file']} | 旧{r['old_score']} → 新{r['new_score']} | {r['title'][:40]}")


if __name__ == "__main__":
    main()
