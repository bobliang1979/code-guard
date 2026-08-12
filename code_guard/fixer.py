"""fixer.py — 自动修复建议 (v0.2)。

只做确定性安全替换 (正则驱动的行级变换), 不做 LLM 生成式修复:
- eval(...) -> ast.literal_eval(...)  (需 import ast 已存在时)
- os.system("...") -> subprocess.run([...], shell=False)  (字面量参数)
- subprocess.*(shell=True) -> 移除 shell=True
- 硬编码密钥 -> 标记 manual (无法自动改)

安全设计:
- 只建议不落盘: fix 命令默认输出建议 diff, --apply 才写文件
- 保守: 变换失败/参数非字面量 -> manual 标记, 绝不生成错误代码
- 修复后可复扫验证 (--check)
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .scanner import parse_diff


@dataclass
class FixSuggestion:
    file: str
    line: int
    kind: str        # eval/os_system/shell_true/secret/manual
    before: str
    after: str
    confidence: str  # HIGH (确定性替换) / MANUAL (需人工)
    note: str = ""

    def to_dict(self) -> dict:
        return {"file": self.file, "line": self.line, "kind": self.kind,
                "before": self.before, "after": self.after,
                "confidence": self.confidence, "note": self.note}


# eval(x) -> ast.literal_eval(x)。只处理单行简单调用。
_EVAL_RE = re.compile(r"^(?P<indent>\s*)(?P<prefix>.*?)\beval\s*\((?P<args>[^()]*)\)(?P<suffix>.*)$")

# os.system("literal") -> subprocess.run(["literal"], shell=False)
_OS_SYSTEM_RE = re.compile(r"""^(?P<indent>\s*)(?P<prefix>.*?)os\.system\s*\(\s*["'](?P<cmd>[^"']*)["']\s*\)(?P<suffix>.*)$""")

# subprocess.run/call/Popen(..., shell=True) -> 移除 shell=True
_SHELL_TRUE_RE = re.compile(r"(shell\s*=\s*True)")


def _suggest_eval(line: str) -> Optional[str]:
    m = _EVAL_RE.match(line)
    if not m:
        return None
    # 参数必须是简单标识符/字面量 (无嵌套调用) 才 HIGH
    args = m.group("args").strip()
    if not args or re.search(r"[(){};]", args):
        return None
    if "import ast" not in args:  # 不能是 import 语句本身
        pass
    return f"{m.group('indent')}{m.group('prefix')}ast.literal_eval({m.group('args')}){m.group('suffix')}"


def _suggest_os_system(line: str) -> Optional[str]:
    m = _OS_SYSTEM_RE.match(line)
    if not m:
        return None
    cmd = m.group("cmd")
    return (f"{m.group('indent')}{m.group('prefix')}"
            f"subprocess.run([{cmd!r}], shell=False){m.group('suffix')}")


def _suggest_shell_true(line: str) -> Optional[str]:
    if _SHELL_TRUE_RE.search(line):
        return _SHELL_TRUE_RE.sub("shell=False", line)
    return None


def suggest_fixes(diff_text: str) -> List[FixSuggestion]:
    """对 diff 新增行生成修复建议。"""
    fixes: List[FixSuggestion] = []
    seen: set = set()
    for file, line_no, added in parse_diff(diff_text):
        key = (file, line_no)
        if key in seen:
            continue
        seen.add(key)

        # eval -> literal_eval
        after = _suggest_eval(added)
        if after and after != added:
            fixes.append(FixSuggestion(file=file, line=line_no, kind="eval",
                                       before=added, after=after,
                                       confidence="HIGH",
                                       note="eval() 改为 ast.literal_eval() (需 import ast)"))
            continue

        # os.system("literal") -> subprocess.run
        after = _suggest_os_system(added)
        if after and after != added:
            fixes.append(FixSuggestion(file=file, line=line_no, kind="os_system",
                                       before=added, after=after,
                                       confidence="HIGH",
                                       note="os.system() 改为 subprocess.run(shell=False)"))
            continue

        # shell=True -> shell=False
        after = _suggest_shell_true(added)
        if after and after != added:
            fixes.append(FixSuggestion(file=file, line=line_no, kind="shell_true",
                                       before=added, after=after,
                                       confidence="HIGH",
                                       note="shell=True 关闭 (禁用 shell 解释)"))
            continue

        # 密钥 -> manual
        if re.search(r"(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})", added):
            fixes.append(FixSuggestion(file=file, line=line_no, kind="secret",
                                       before=added, after="",
                                       confidence="MANUAL",
                                       note="硬编码密钥: 需人工改为环境变量 (os.environ), 无法自动替换"))
            continue

        # eval/exec/os.system 但无法安全变换 -> manual
        if re.search(r"\beval\s*\(|\bexec\s*\(|os\.system\s*\(", added):
            fixes.append(FixSuggestion(file=file, line=line_no, kind="manual",
                                       before=added, after="",
                                       confidence="MANUAL",
                                       note="危险调用无法确定性替换 (参数非字面量/嵌套调用): 需人工审查"))
    return fixes


def render_fixes(fixes: List[FixSuggestion]) -> str:
    if not fixes:
        return "无自动修复建议"
    lines = [f"共 {len(fixes)} 条修复建议:"]
    for f in fixes:
        tag = "🔧" if f.confidence == "HIGH" else "⚠️"
        lines.append(f"  {tag} {f.file}:{f.line} [{f.kind}] {f.note}")
        if f.confidence == "HIGH":
            lines.append(f"      - {f.before.strip()}")
            lines.append(f"      + {f.after.strip()}")
    auto = sum(1 for f in fixes if f.confidence == "HIGH")
    manual = len(fixes) - auto
    lines.append(f"  可自动修复 {auto} 条, 需人工 {manual} 条 (--apply 落地自动修复)")
    return "\n".join(lines)


def apply_fixes(repo_dir: str, fixes: List[FixSuggestion]) -> Tuple[int, List[str]]:
    """落地 HIGH 置信度修复。返回 (成功数, 错误列表)。MANUAL 跳过。"""
    # 按文件分组, 行号倒序应用 (避免行号偏移)
    by_file: dict = {}
    for f in fixes:
        if f.confidence != "HIGH":
            continue
        by_file.setdefault(f.file, []).append(f)
    applied = 0
    errors: List[str] = []
    for file, file_fixes in by_file.items():
        path = os.path.join(repo_dir, file)
        try:
            with open(path, encoding="utf-8") as fp:
                lines = fp.read().splitlines()
            for fix in sorted(file_fixes, key=lambda x: -x.line):
                idx = fix.line - 1
                if 0 <= idx < len(lines) and lines[idx].strip() == fix.before.strip():
                    lines[idx] = fix.after
                    applied += 1
                else:
                    errors.append(f"{file}:{fix.line} 内容已变化, 跳过")
            with open(path, "w", encoding="utf-8", newline="") as fp:
                fp.write("\n".join(lines) + "\n")
        except OSError as e:
            errors.append(f"{file}: {e}")
    return applied, errors


import os  # noqa: E402  (apply_fixes 使用)
