"""scanner.py — 跨语言危险模式扫描器 (只扫 git diff 新增行)。

核心设计: 扫 diff 的 `+` 行, 而非整个代码库。
- 只报告新增问题, 存量噪音为零 (CI 友好)
- 跨语言: Python/JS/TS/Go/Rust/SQL 通用
- 零依赖, 正则驱动, 每个命中 = 一条 Finding
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

# 严重度 (门禁判定: BLOCKER/HIGH -> 静态门 FAIL)
BLOCKER = "BLOCKER"
HIGH = "HIGH"
MEDIUM = "MEDIUM"
LOW = "LOW"

# 危险模式表: (正则, 严重度, 说明)
# 注意: 所有模式只匹配新增行 (已去除注释行/字符串内误报由规则本身控制)
PATTERNS: List[tuple] = [
    # --- 凭据泄漏 (BLOCKER) ---
    (re.compile(r"(?<![A-Za-z0-9])(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,})(?![A-Za-z0-9])"),
     BLOCKER, "硬编码密钥/令牌 (API key/token) — 必须改为环境变量"),
    (re.compile(r"-----BEGIN (RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
     BLOCKER, "私有密钥被提交 — 立即吊销并移出仓库"),
    (re.compile(r"""(?i)(password|passwd|secret|api[_-]?key|token)\s*[:=]\s*["'][^"']{8,}["']"""),
     BLOCKER, "疑似硬编码口令/密钥赋值"),
    (re.compile(r"""(?i)aws_access_key_id\s*=|aws_secret_access_key\s*=|s3\.amazonaws\.com/[A-Za-z0-9/]{16,}"""),
     BLOCKER, "AWS 凭据泄漏"),

    # --- 代码注入/危险执行 (BLOCKER) ---
    # (?<!["']) 排除字符串字面量内的模式 (如 BLOCKED_PATTERNS=["eval("] 黑名单定义, 非真实调用)
    # \b 前缀排除规则源码自身 (如 r"\beval(" 中 b 和 e 之间无边界)
    (re.compile(r"(?<![\"'])\beval\s*\("), BLOCKER, "eval() — 代码注入风险, 用 ast.literal_eval()"),
    (re.compile(r"(?<![\"'])\bexec\s*\("), BLOCKER, "exec() — 代码注入风险, 需人工审查"),
    (re.compile(r"(?<![\"'])\bos\.system\s*\("), HIGH, "os.system() — 命令注入风险, 用 subprocess.run(shell=False)"),
    (re.compile(r"(?<![\"'])\bsubprocess\.(call|run|Popen)\s*\([^)]*shell\s*=\s*True"), HIGH,
     "subprocess shell=True — 命令注入风险, 传参数列表"),
    (re.compile(r"(?<![\"'])\bos\.popen\s*\("), HIGH, "os.popen() — 命令注入风险"),
    (re.compile(r"(?<![\"'])\bchild_process\.(exec|execSync|spawn|spawnSync)\s*\(\s*[`'\"]"), HIGH,
     "Node child_process 拼接命令 — 注入风险, 用 execFile"),

    # --- 不安全反序列化 (HIGH) ---
    (re.compile(r"(?<![\"'])\bpickle\.(load|loads)\s*\("), HIGH, "pickle 反序列化 — 任意代码执行风险, 用 JSON"),
    (re.compile(r"(?<![\"'])\byaml\.load\s*\([^)]*Loader"), HIGH, "yaml.load 未指定 SafeLoader — 反序列化风险"),
    (re.compile(r"(?<![\"'])\bmarshal\.loads?\s*\("), HIGH, "marshal 反序列化 — 不安全"),

    # --- SQL 注入 (BLOCKER) ---
    (re.compile(r"""(?i)(?<![\"'])\bexecute\s*\(\s*f["']"""), BLOCKER, "SQL f-string 拼接 — 注入风险, 用参数化查询"),
    (re.compile(r"""(?i)(?<![\"'])\b(execute|executemany|query)\s*\(\s*["'][^"']*(\{|%s|%\(|\+)"""),
     BLOCKER, "SQL 字符串拼接 — 注入风险, 用参数化查询"),

    # --- XSS (JS/TS) (HIGH) ---
    (re.compile(r"(?<![\"'])\binnerHTML\s*="), HIGH, "innerHTML 赋值 — XSS 风险, 用 textContent"),
    (re.compile(r"(?<![\"'])\bdocument\.write\s*\("), HIGH, "document.write — XSS 风险"),
    (re.compile(r"(?<![\"'])\bdangerouslySetInnerHTML"), HIGH, "React XSS 属性 — 用 textContent"),

    # --- 路径穿越 (BLOCKER) — 自然编码实测发现 (URL 当文件名, .. 未过滤) ---
    (re.compile(r"url\.replace\([^)]*[/\\\\]|\bslugify\s*\("), BLOCKER,
     "URL/文件名拼路径未防穿越 — 用 basename+白名单"),
    (re.compile(r'join\s*\(\s*[^)]*\.replace\([^)]*[/\\]'), BLOCKER,
     "用户输入拼路径 — 路径穿越风险"),
    (re.compile(r'open\s*\(\s*f["\']'), HIGH, "f-string 拼文件路径 — 路径穿越风险"),

    # --- TLS/安全配置 (MEDIUM) ---
    (re.compile(r"verify\s*=\s*False"), MEDIUM, "SSL 验证被禁用 (verify=False)"),
    (re.compile(r"(?i)ssl_verify\s*=\s*False|insecure\s*=\s*True|allow_insecure"), MEDIUM, "TLS 校验关闭"),

    # --- 调试残留 (LOW) ---
    (re.compile(r"console\.log\s*\(\s*['\"][Pp]assword|print\s*\(\s*['\"][Pp]assword"),
     LOW, "调试打印可能泄漏敏感信息"),
]

# 注释行前缀 (跨语言)
_COMMENT_PREFIXES = ("#", "//", "/*", "*", "--", "<!--")


@dataclass
class Finding:
    file: str
    line: int
    severity: str
    message: str
    code: str = ""

    def to_dict(self) -> dict:
        return {"file": self.file, "line": self.line, "severity": self.severity,
                "message": self.message, "code": self.code[:120]}


def _is_comment(line: str) -> bool:
    stripped = line.lstrip()
    return any(stripped.startswith(p) for p in _COMMENT_PREFIXES) or stripped == ""


def parse_diff(diff_text: str) -> List[tuple]:
    """解析 unified diff, 返回 [(file, line_no, added_line)] 列表。

    只收集新增行 (`+` 开头, 排除 `+++` 文件头), 行号由 @@ hunk 头推算。
    """
    result: List[tuple] = []
    current_file: Optional[str] = None
    new_line = 0  # 当前 hunk 的新文件起始行号

    for raw in diff_text.splitlines():
        line = raw.rstrip("\r")
        if line.startswith("+++ b/"):
            current_file = line[6:]
            continue
        if line.startswith("--- "):
            continue
        m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
        if m:
            new_line = int(m.group(1))
            continue
        if current_file is None or new_line == 0:
            continue
        if line.startswith("+"):
            added = line[1:]
            if not _is_comment(added):
                result.append((current_file, new_line, added))
            new_line += 1
        elif line.startswith("-"):
            pass  # 删除行不推进新行号
        else:
            new_line += 1  # 上下文行

    return result


_SEVERITY_ORDER = {BLOCKER: 3, HIGH: 2, MEDIUM: 1, LOW: 0}


def _dedupe(findings: List[Finding]) -> List[Finding]:
    """同一文件同一行多条命中 -> 只保留最高严重度一条 (减少噪音)。"""
    best: dict = {}
    for f in findings:
        key = (f.file, f.line)
        if key not in best or _SEVERITY_ORDER[f.severity] > _SEVERITY_ORDER[best[key].severity]:
            best[key] = f
    return sorted(best.values(), key=lambda f: (f.file, f.line))


def scan_diff(diff_text: str) -> List[Finding]:
    """扫描 diff 新增行, 返回全部命中 (同行去重, 保留最高严重度)。"""
    findings: List[Finding] = []
    for file, line_no, added in parse_diff(diff_text):
        for pattern, severity, message in PATTERNS:
            if pattern.search(added):
                findings.append(Finding(file=file, line=line_no, severity=severity,
                                        message=message, code=added.strip()))
    return _dedupe(findings)


def scan_code(code: str, filename: str = "<memory>") -> List[Finding]:
    """直接扫描一段代码 (不解析 diff)。用于 demo/自测。"""
    findings: List[Finding] = []
    for i, line in enumerate(code.splitlines(), 1):
        if _is_comment(line):
            continue
        for pattern, severity, message in PATTERNS:
            if pattern.search(line):
                findings.append(Finding(file=filename, line=i, severity=severity,
                                        message=message, code=line.strip()))
    return findings


# ---- 自测 ----

def _demo() -> int:
    """内嵌演示: 一段含 5 类问题的代码, 期望全部命中。"""
    bad = '''import os, pickle, yaml
def handler(data):
    api_key = "sk-1234567890ABCDEFGHIJKLMN"
    os.system(f"rm -rf {data}")
    eval(data)
    pickle.loads(data)
    conn.execute(f"SELECT * FROM t WHERE id={data}")
    el.innerHTML = data
    requests.get(url, verify=False)
    print("password is admin123")
'''
    good = '''import os
def handler(data):
    api_key = os.environ["API_KEY"]
    subprocess.run(["rm", "-rf", data])
    conn.execute("SELECT * FROM t WHERE id=?", (data,))
    el.textContent = data
'''
    bad_findings = scan_code(bad)
    good_findings = scan_code(good)
    severities = {f.severity for f in bad_findings}
    checks = [
        ("坏代码命中 BLOCKER", any(s == BLOCKER for s in severities)),
        ("坏代码命中 HIGH", any(s == HIGH for s in severities)),
        ("坏代码命中 MEDIUM", any(s == MEDIUM for s in severities)),
        ("好代码零命中", len(good_findings) == 0),
    ]
    ok = all(v for _, v in checks)
    print(f"[scanner] 坏代码命中 {len(bad_findings)} 处: {sorted(severities)}")
    for name, passed in checks:
        print(f"  {'✅' if passed else '❌'} {name}")
    print(f"[scanner] {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_demo())
