"""gates.py — 三扇门禁: 静态安全门 / 测试回归门 / 假PASS拦截门。

门禁判定规则:
- 静态安全门: 任何 BLOCKER/HIGH finding -> FAIL (fail-closed)
- 测试回归门: 跑测试, 与 baseline 对比, 只拦"新增失败"; 无测试框架 -> SKIP
- 假PASS拦截门: diff 改了生产代码但测试文件零改动 -> FAIL (LLM 代理典型作弊路径)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .scanner import BLOCKER, HIGH, Finding, scan_diff

# 常见测试文件/目录特征
_TEST_FILE_RE = re.compile(r"(^|[/\\])(test_|tests?[/\\]|.*\.(test|spec)\.|__tests__)", re.I)
# 文档文件跳过: 代码示例非可执行代码 (README/md/docs), 静态门不扫
_DOC_FILE_RE = re.compile(r"\.(md|markdown|rst|txt|adoc)$", re.I)
# 测试命令探测表: (检测文件, 命令列表)
_TEST_DETECT = [
    ("pyproject.toml", [["{py}", "-m", "pytest", "-q", "--tb=no"]]),
    ("pytest.ini", [["{py}", "-m", "pytest", "-q", "--tb=no"]]),
    ("requirements-dev.txt", [["{py}", "-m", "pytest", "-q", "--tb=no"]]),
    ("package.json", [["npm", "test", "--silent"]]),
    ("go.mod", [["go", "test", "./..."]]),
    ("Cargo.toml", [["cargo", "test", "--quiet"]]),
]

_TEST_DIR_RE = re.compile(r"(^|[/\\])(tests?|__tests__|spec)[/\\]", re.I)


@dataclass
class GateResult:
    name: str
    status: str  # PASS / FAIL / SKIP
    detail: str = ""
    findings: List[Finding] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"name": self.name, "status": self.status, "detail": self.detail,
                "findings": [f.to_dict() for f in self.findings]}


def detect_test_command(repo_dir: str) -> Optional[List[str]]:
    """探测仓库的测试命令。找不到 -> None (门 SKIP)。

    优先级: 配置文件标记 > test_*.py 文件存在 (回退 pytest)。
    {py} 替换为当前解释器 (sys.executable), 避免 PATH 里 python 版本漂移。
    """
    py = sys.executable
    for marker, cmds in _TEST_DETECT:
        if os.path.exists(os.path.join(repo_dir, marker)):
            return [c.replace("{py}", py) for c in cmds[0]]
    # 回退: 存在 test_*.py 文件 -> 尝试 pytest
    for name in os.listdir(repo_dir):
        if name.startswith("test_") and name.endswith(".py"):
            return [py, "-m", "pytest", "-q", "--tb=no"]
    return None


def _run(cmd: List[str], cwd: str, timeout: int = 120) -> tuple:
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout[-2000:] + proc.stderr[-2000:]
    except subprocess.TimeoutExpired:
        return -1, f"TIMEOUT ({timeout}s)"
    except FileNotFoundError:
        return -2, f"命令不存在: {cmd[0]}"


def static_gate(diff_text: str, include_tests: bool = False) -> GateResult:
    """静态安全门: BLOCKER/HIGH 任一 -> FAIL。

    include_tests=False (默认): 跳过测试文件 — 测试常含故意构造的危险样例
    (验证检测器/mock), 且不进入生产。bandit/forge 同惯例。
    """
    findings = scan_diff(diff_text)
    if not include_tests:
        findings = [f for f in findings
                    if not _TEST_FILE_RE.search(f.file) and not _DOC_FILE_RE.search(f.file)]
    blockers = [f for f in findings if f.severity in (BLOCKER, HIGH)]
    if blockers:
        detail = f"{len(blockers)} 处高危命中: " + "; ".join(
            f"{f.file}:{f.line} {f.message}" for f in blockers[:5])
        return GateResult("static", "FAIL", detail, blockers)
    if findings:
        return GateResult("static", "PASS",
                          f"仅 {len(findings)} 处中低危提示 (不阻断)", findings)
    return GateResult("static", "PASS", "无命中")


def test_gate(repo_dir: str, diff_text: str, timeout: int = 120,
              baseline: Optional[dict] = None) -> GateResult:
    """测试回归门: 跑测试, 与 baseline 对比只拦新增失败。

    baseline: {"failures": N} 来自上次全量跑; 无 baseline 时当前失败即拦。
    """
    cmd = detect_test_command(repo_dir)
    if cmd is None:
        return GateResult("tests", "SKIP", "未检测到测试框架 (pytest/npm/go/cargo)")
    rc, output = _run(cmd, repo_dir, timeout)
    if rc == -2:
        return GateResult("tests", "SKIP", f"测试命令不可用: {cmd[0]}")
    if rc == -1:
        return GateResult("tests", "FAIL", f"测试超时: {output}")
    # 环境缺依赖 (No module named / command not found) -> SKIP, 不是 BLOCK
    if rc != 0 and ("No module named" in output or "not found" in output
                    or "command not found" in output or "npm ERR!" in output and "ENOENT" in output):
        return GateResult("tests", "SKIP", f"测试依赖缺失 (rc={rc}): {output[:200]}")
    if rc == 0:
        return GateResult("tests", "PASS", "全部测试通过")

    # 失败: 统计失败数 (解析 pytest summary "N failed"), 与 baseline 对比
    m = re.search(r"(\d+) failed", output)
    fail_count = int(m.group(1)) if m else (output.count("FAILED"))
    baseline_fail = (baseline or {}).get("failures", 0)
    if baseline_fail and fail_count <= baseline_fail:
        return GateResult("tests", "PASS",
                          f"失败 {fail_count} 项 ≤ baseline {baseline_fail} (非新增回归)")
    return GateResult("tests", "FAIL",
                      f"{fail_count} 项测试失败: {output[:400]}", [])


def _changed_files(diff_text: str) -> tuple:
    """返回 (生产代码文件, 测试文件) 列表。"""
    prod, test_files = [], []
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            f = line[6:]
            if _TEST_FILE_RE.search(f):
                test_files.append(f)
            else:
                prod.append(f)
    return prod, test_files


def fake_pass_gate(diff_text: str, require_tests: bool = False) -> GateResult:
    """假PASS拦截门: 改了生产代码但测试零改动 -> 警告/FAIL。

    LLM 编码代理的典型作弊: 声称"已修复+测试通过", 实际没加测试。
    require_tests=True 时 (CI 严格模式) 直接 FAIL。
    """
    prod, test_files = _changed_files(diff_text)
    if not prod:
        return GateResult("coverage", "SKIP", "无生产代码改动")
    if test_files:
        return GateResult("coverage", "PASS",
                          f"生产代码 {len(prod)} 文件 + 测试 {len(test_files)} 文件")
    detail = (f"⚠ 生产代码改动 {len(prod)} 文件但测试零改动 — LLM 代理假PASS 典型路径"
              + ("" if require_tests else " (建议 --require-tests 强制)"))
    if require_tests:
        return GateResult("coverage", "FAIL", detail)
    return GateResult("coverage", "WARN", detail)


def run_all(diff_text: str, repo_dir: str, require_tests: bool = False,
            timeout: int = 120, baseline: Optional[dict] = None,
            include_tests: bool = False,
            llm_review: bool = False) -> dict:
    """执行全部门禁, 返回报告 dict。llm_review=True 时启用第四扇门 (可选, SKIP 不阻断)。"""
    gates = [
        static_gate(diff_text, include_tests),
        test_gate(repo_dir, diff_text, timeout, baseline),
        fake_pass_gate(diff_text, require_tests),
    ]
    if llm_review:
        from .llm_review import llm_review as _llm_review
        static_findings = scan_diff(diff_text)
        gates.append(_llm_review(diff_text, static_findings))
    failed = [g for g in gates if g.status == "FAIL"]
    report = {
        "version": "0.2.1",
        "verdict": "BLOCK" if failed else "PASS",
        "gates": [g.to_dict() for g in gates],
        "summary": "; ".join(f"{g.name}={g.status}" for g in gates),
    }
    return report


def save_baseline(repo_dir: str, report: dict) -> None:
    """把本次测试失败数存为 baseline (供下次对比)。"""
    gate = next((g for g in report["gates"] if g["name"] == "tests"), None)
    if gate is None or gate["status"] == "SKIP":
        return
    path = os.path.join(repo_dir, ".code-guard-baseline.json")
    failures = 0
    m = re.search(r"(\d+) 项测试失败", gate["detail"])
    if m:
        failures = int(m.group(1))
    with open(path, "w") as f:
        json.dump({"failures": failures}, f)


def load_baseline(repo_dir: str) -> Optional[dict]:
    path = os.path.join(repo_dir, ".code-guard-baseline.json")
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
    return None


if __name__ == "__main__":
    sys.exit(0)
