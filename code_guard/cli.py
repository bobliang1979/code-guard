"""cli.py — code-guard 命令行入口。

用法:
  code-guard check [--dir .] [--base <git-ref>] [--diff <file|->] [--json]
                   [--require-tests] [--update-baseline] [--timeout 120]
  code-guard demo          # 内嵌演示
  code-guard --version

退出码: 0=PASS, 1=BLOCK, 2=ERROR (diff 无法获取/内部错误)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import List, Optional

from . import __version__
from .gates import load_baseline, run_all, save_baseline
from .scanner import _demo


def _git_diff(base: Optional[str], repo_dir: str) -> Optional[str]:
    """获取 git diff 文本。优先 working tree (base=None 时 = git diff), 否则 base..HEAD。"""
    try:
        if base:
            proc = subprocess.run(["git", "diff", f"{base}..HEAD", "--"],
                                  cwd=repo_dir, capture_output=True, text=True, timeout=60)
        else:
            proc = subprocess.run(["git", "diff", "--cached", "--"],
                                  cwd=repo_dir, capture_output=True, text=True, timeout=60)
            if not proc.stdout.strip():
                proc = subprocess.run(["git", "diff", "--"],
                                      cwd=repo_dir, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            return None
        return proc.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def _read_diff(path: Optional[str], repo_dir: str, base: Optional[str]) -> Optional[str]:
    if path == "-":
        return sys.stdin.read()
    if path:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError:
            return None
    return _git_diff(base, repo_dir)


def _render_text(report: dict) -> str:
    lines = [f"code-guard v{report['version']} — verdict: {report['verdict']}"]
    for g in report["gates"]:
        lines.append(f"  [{g['status']:<4}] {g['name']}: {g['detail']}")
        for f in g.get("findings", [])[:10]:
            # findings 可能是 Finding dict (severity/message) 或 LLM issue dict (type/desc)
            if "severity" in f:
                lines.append(f"         {f['file']}:{f['line']} [{f['severity']}] {f['message']}")
            else:
                lines.append(f"         [{f.get('type','?')}] {f.get('file','?')}:{f.get('line','?')} {f.get('desc','')}")
        if len(g.get("findings", [])) > 10:
            lines.append(f"         ... 共 {len(g['findings'])} 处")
    lines.append(f"summary: {report['summary']}")
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="code-guard",
        description="编码代理安全护栏 — 拦截 LLM 生成代码的危险模式/回归/假PASS")
    sub = p.add_subparsers(dest="command")

    check = sub.add_parser("check", help="对当前 diff 执行三扇门检查")
    check.add_argument("--dir", default=".", help="仓库根目录 (默认当前目录)")
    check.add_argument("--base", default=None,
                       help="git 基线 ref, 对比 base..HEAD (默认: 暂存区+工作区 diff)")
    check.add_argument("--diff", default=None,
                       help="diff 文件路径, '-' 表示 stdin (默认自动从 git 获取)")
    check.add_argument("--json", action="store_true", help="输出 JSON 报告")
    check.add_argument("--require-tests", action="store_true",
                       help="严格模式: 生产代码改动必须带测试, 否则 BLOCK")
    check.add_argument("--include-tests", action="store_true",
                       help="静态门也扫描测试文件 (默认跳过 — 测试常含故意构造样例)")
    check.add_argument("--llm-review", action="store_true",
                       help="启用 LLM 独立评审门 (找静态扫描器漏掉的逻辑/安全问题; API 不可用自动 SKIP)")
    check.add_argument("--update-baseline", action="store_true",
                       help="把本次测试失败数存为 baseline 供下次对比")
    check.add_argument("--timeout", type=int, default=120, help="测试超时秒数")

    sub.add_parser("demo", help="内嵌演示 (扫描器自测)")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "demo":
        return _demo()
    if args.command is None:
        _build_parser().print_help()
        return 2
    if args.command == "check":
        diff_text = _read_diff(args.diff, args.dir, args.base)
        if diff_text is None:
            print("ERROR: 无法获取 diff (不是 git 仓库? 或 --diff 文件不存在)", file=sys.stderr)
            return 2
        if not diff_text.strip():
            print("code-guard: diff 为空, 无改动可检查")
            return 0
        baseline = load_baseline(args.dir) if not args.update_baseline else None
        report = run_all(diff_text, args.dir,
                         require_tests=args.require_tests,
                         timeout=args.timeout, baseline=baseline,
                         include_tests=args.include_tests,
                         llm_review=args.llm_review)
        if args.update_baseline:
            save_baseline(args.dir, report)
        out = json.dumps(report, ensure_ascii=False, indent=2) if args.json else _render_text(report)
        print(out)
        return 0 if report["verdict"] == "PASS" else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
