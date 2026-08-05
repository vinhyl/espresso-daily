"""运行质量报告（阶段二）。

每次运行在 reports/ 落两份产物：
  - quality_<date>.json：机器可读，供趋势统计 / CI 断言；
  - quality_<date>.md  ：人类可读摘要，贴 Issue / 周报用。

核心指标（接手规格要求的验收项）：
  - 每源：候选数 / 入选数 / 拒绝数 / 拒绝原因分布 / 平均分；
  - 全局：来源占比、重复率（去重跳过 + 事件折叠）、意式核心占比、
          85+ 强证据条数、深度解读数；
  - 合并 fetch_failures_<date>.json 的失败维度（每源失败率、限流/封禁标记）。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re

from src import fetch as fetch_mod
from src import score as score_mod

REPORTS_DIR = fetch_mod.REPORTS_DIR
SCORE_85 = 85  # 罕见强证据阈值


class QualityReport:
    def __init__(self, cfg: dict, date_str: str):
        self.cfg = cfg
        self.date = date_str
        self.sources: dict[str, dict] = {}
        self.total_candidates = 0
        self.espresso_core_hits = 0
        self.rejects: list[dict] = []          # {title, source, stage, reason}
        self.scores: list[int] = []
        self.count_85plus = 0
        self.count_deepdive = 0
        self.dedup_skipped = 0                 # 因已收录（source_url/title）跳过
        self.cluster_folds = 0                 # 事件聚类折叠掉的条数
        self.fetch_failures: list[dict] = []

    # ---- 累积 ----
    def record_candidate(self, it: dict, espresso_core: bool) -> None:
        self.total_candidates += 1
        if espresso_core:
            self.espresso_core_hits += 1
        name = it.get("source", "(unknown)")
        s = self.sources.setdefault(name, {
            "candidates": 0, "accepted": 0, "rejected": 0,
            "scores": [], "reject_reasons": {},
        })
        s["candidates"] += 1

    def record_reject(self, it: dict, reason: str, stage: str) -> None:
        name = it.get("source", "(unknown)")
        s = self.sources.setdefault(name, {
            "candidates": 0, "accepted": 0, "rejected": 0,
            "scores": [], "reject_reasons": {},
        })
        s["rejected"] += 1
        s["reject_reasons"][f"[{stage}] {reason}"] = \
            s["reject_reasons"].get(f"[{stage}] {reason}", 0) + 1
        self.rejects.append({
            "title": it.get("title", ""), "source": name,
            "stage": stage, "reason": reason,
        })

    def record_accept(self, it: dict, j) -> None:
        name = it.get("source", "(unknown)")
        s = self.sources.setdefault(name, {
            "candidates": 0, "accepted": 0, "rejected": 0,
            "scores": [], "reject_reasons": {},
        })
        s["accepted"] += 1
        s["scores"].append(j.score)
        self.scores.append(j.score)
        if j.score >= SCORE_85:
            self.count_85plus += 1
        if j.kind == "deepdive" and j.deepdive:
            self.count_deepdive += 1

    # ---- 合并抓取失败维度 ----
    def merge_failures(self, failures: list[dict] | None = None) -> None:
        # 注意：传空列表 [] 也要采纳（表示本次运行无失败），不能用 `if failures:`（空列表为假）。
        if failures is not None:
            self.fetch_failures = list(failures)
            return
        # 回退：直接读当日 fetch_failures 文件
        path = os.path.join(REPORTS_DIR, f"fetch_failures_{self.date}.json")
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                self.fetch_failures = data.get("failures", [])
            except Exception:
                pass

    # ---- 输出 ----
    def summary(self) -> dict:
        total_acc = sum(s["accepted"] for s in self.sources.values())
        total_rej = sum(s["rejected"] for s in self.sources.values())
        avg = (sum(self.scores) / len(self.scores)) if self.scores else 0.0
        # 来源占比（入选）
        src_ratio = {}
        if total_acc:
            for name, s in self.sources.items():
                if s["accepted"]:
                    src_ratio[name] = round(s["accepted"] / total_acc, 3)
        # 重复率 = (去重跳过 + 聚类折叠) / 候选
        dup = self.dedup_skipped + self.cluster_folds
        dup_rate = round(dup / self.total_candidates, 3) if self.total_candidates else 0.0
        core_ratio = round(self.espresso_core_hits / self.total_candidates, 3) \
            if self.total_candidates else 0.0
        # 失败按源聚合
        fail_by_src: dict[str, dict] = {}
        for fr in self.fetch_failures:
            nm = fr.get("source", "(unknown)")
            d = fail_by_src.setdefault(nm, {"count": 0, "rate_limited": 0, "blocked": 0, "stages": {}})
            d["count"] += 1
            d["rate_limited"] += 1 if fr.get("rate_limited") else 0
            d["blocked"] += 1 if fr.get("blocked") else 0
            st = fr.get("stage", "feed")
            d["stages"][st] = d["stages"].get(st, 0) + 1
        return {
            "date": self.date,
            "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "totals": {
                "candidates": self.total_candidates,
                "accepted": total_acc,
                "rejected": total_rej,
                "accept_rate": round(total_acc / self.total_candidates, 3) if self.total_candidates else 0,
                "score_avg": round(avg, 2),
                "score_85plus": self.count_85plus,
                "deepdive": self.count_deepdive,
                "espresso_core_ratio": core_ratio,
                "dup_rate": dup_rate,
                "dedup_skipped": self.dedup_skipped,
                "cluster_folds": self.cluster_folds,
            },
            "source_ratio": src_ratio,
            "per_source": {
                name: {
                    "candidates": s["candidates"],
                    "accepted": s["accepted"],
                    "rejected": s["rejected"],
                    "score_avg": round(sum(s["scores"]) / len(s["scores"]), 2) if s["scores"] else 0,
                    "reject_reasons": s["reject_reasons"],
                }
                for name, s in self.sources.items()
            },
            "fetch_failures": {"total": len(self.fetch_failures), "by_source": fail_by_src},
        }

    def write(self) -> str | None:
        os.makedirs(REPORTS_DIR, exist_ok=True)
        data = self.summary()
        json_path = os.path.join(REPORTS_DIR, f"quality_{self.date}.json")
        md_path = os.path.join(REPORTS_DIR, f"quality_{self.date}.md")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(self._to_markdown(data))
        print(f"[quality] 已写质量报告：{json_path}")
        print(f"[quality] 已写质量报告：{md_path}")
        return md_path

    def _to_markdown(self, d: dict) -> str:
        t = d["totals"]
        lines = [
            f"# 运行质量报告 · {d['date']}",
            "",
            f"> 生成时间：{d['generated_at']}",
            "",
            "## 总览",
            "",
            f"- 候选条目：**{t['candidates']}**　入选：**{t['accepted']}**　拒绝：**{t['rejected']}**",
            f"- 入选率：{t['accept_rate']*100:.1f}%　平均分：{t['score_avg']}",
            f"- 85+ 强证据：**{t['score_85plus']} 条**　深度解读：**{t['deepdive']} 条**",
            f"- 意式核心占比：{t['espresso_core_ratio']*100:.1f}%　重复率：{t['dup_rate']*100:.1f}%",
            f"  - 去重跳过 {t['dedup_skipped']} · 事件聚类折叠 {t['cluster_folds']}",
            "",
        ]
        if d["source_ratio"]:
            lines.append("## 来源占比（入选）")
            lines.append("")
            for name, r in sorted(d["source_ratio"].items(), key=lambda x: -x[1]):
                lines.append(f"- {name}：{r*100:.1f}%")
            lines.append("")
        lines.append("## 每源明细")
        lines.append("")
        lines.append("| 来源 | 候选 | 入选 | 拒绝 | 平均分 | 主要拒绝原因 |")
        lines.append("| --- | ---: | ---: | ---: | ---: | --- |")
        for name, s in sorted(d["per_source"].items(), key=lambda x: -x[1]["accepted"]):
            top_reasons = "；".join(
                f"{k}×{v}" for k, v in list(s["reject_reasons"].items())[:3]
            ) or "—"
            lines.append(
                f"| {name} | {s['candidates']} | {s['accepted']} | {s['rejected']} "
                f"| {s['score_avg']} | {top_reasons} |"
            )
        lines.append("")
        ff = d["fetch_failures"]
        lines.append("## 抓取失败维度")
        lines.append("")
        if ff["total"] == 0:
            lines.append("- 本次无抓取失败。")
        else:
            lines.append(f"- 失败总数：**{ff['total']}**")
            for nm, info in ff["by_source"].items():
                flags = []
                if info["rate_limited"]:
                    flags.append("限流")
                if info["blocked"]:
                    flags.append("封禁")
                flag_s = f"（{'/'.join(flags)}）" if flags else ""
                stages = "、".join(f"{k}×{v}" for k, v in info["stages"].items())
                lines.append(f"- {nm}{flag_s}：{info['count']} 次（{stages}）")
        lines.append("")
        return "\n".join(lines)
