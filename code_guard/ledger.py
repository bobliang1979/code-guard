"""ledger.py — 失败归因账本 (v0.5)。

跨 PR/commit 统计 code-guard 拦截的失败模式, 帮助企业看到:
"哪类危险模式/回归反复出现" → 反哺改进 LLM 代理提示词与工程规则。

存储: JSONL 追加 (零依赖, 每行一条记录), 默认 <repo>/.code-guard/ledger.jsonl
设计: check 每次自动记录 (写失败绝不阻断); stats 聚合。
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timedelta
from typing import Dict, List, Optional

LEDGER_DIR = ".code-guard"
LEDGER_FILE = "ledger.jsonl"


def ledger_path(repo_dir: str) -> str:
    return os.path.join(repo_dir, LEDGER_DIR, LEDGER_FILE)


def record(report: dict, repo_dir: str, base: str = "") -> Optional[str]:
    """追加一条检查记录到账本。失败返回 None (绝不阻断 CI)。"""
    try:
        path = ledger_path(repo_dir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        entry = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "verdict": report.get("verdict"),
            "base": base,
            "gates": {g["name"]: g["status"] for g in report.get("gates", [])},
            # 失败模式: 每个 FAIL/WARN 门的详情 (去重, 截断)
            "issues": [
                {"gate": g["name"], "detail": g["detail"][:300]}
                for g in report.get("gates", [])
                if g["status"] in ("FAIL", "WARN") and g.get("detail")
            ],
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return path
    except OSError:
        return None


def load(repo_dir: str) -> List[dict]:
    """读取全部账本记录。文件不存在/损坏行 -> 跳过 (容错)。"""
    path = ledger_path(repo_dir)
    records: List[dict] = []
    if not os.path.isfile(path):
        return records
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # 损坏行跳过
    except OSError:
        pass
    return records


def stats(repo_dir: str, days: Optional[int] = None) -> Dict:
    """聚合统计。days=None 全部; days=N 只看最近 N 天。"""
    records = load(repo_dir)
    if days is not None:  # days=0 也过滤 (0 是 falsy, 不能用 if days:)
        cutoff = (datetime.now() - timedelta(days=days)).replace(microsecond=0)
        records = [r for r in records
                   if datetime.fromisoformat(r.get("ts", "")[:19]) >= cutoff]

    gate_status = Counter()
    issue_patterns: Counter = Counter()
    verdicts = Counter(r.get("verdict", "?") for r in records)
    issue_count = 0

    for r in records:
        for g, st in r.get("gates", {}).items():
            gate_status[f"{g}={st}"] += 1
        for iss in r.get("issues", []):
            issue_count += 1
            # 模式提取: 取 detail 首段 (门名 + 前 60 字) 归并
            pattern = f"{iss['gate']}: {iss['detail'][:60]}"
            issue_patterns[pattern] += 1

    return {
        "total_checks": len(records),
        "verdicts": dict(verdicts),
        "gate_status": dict(gate_status),
        "issue_count": issue_count,
        "top_patterns": issue_patterns.most_common(10),
    }


def render_stats(s: Dict, days: Optional[int] = None) -> str:
    window = f" (最近 {days} 天)" if days else " (全部)"
    lines = [f"code-guard 失败归因账本{window}",
             f"  检查次数: {s['total_checks']}  拦截问题: {s['issue_count']}"]
    lines.append("  verdict 分布: " + ", ".join(f"{k}={v}" for k, v in s["verdicts"].items()))
    lines.append("  门状态: " + ", ".join(f"{k}={v}" for k, v in s["gate_status"].items()))
    if s["top_patterns"]:
        lines.append("  高频失败模式 (Top 10):")
        for pat, cnt in s["top_patterns"]:
            lines.append(f"    x{cnt:<3} {pat}")
    else:
        lines.append("  暂无失败模式记录")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        d = int(sys.argv[2]) if len(sys.argv) > 2 else None
        print(render_stats(stats(sys.argv[1], d), d))
    else:
        print("usage: python ledger.py <repo_dir> [days]")
