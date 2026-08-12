"""llm_review.py — LLM 独立评审门 (v0.4, 可选启用)。

设计:
- OpenAI 兼容协议 (chat/completions), 支持 DeepSeek/OpenAI/本地 vLLM 等任意 provider
- fail-closed: LLM 报告 security/logic 问题 -> FAIL; API 不可用/超时/解析失败 -> SKIP (不阻断 CI)
- 只评审静态门漏掉的部分: 逻辑错误/边界条件/设计问题 — 与静态正则互补
- 零依赖: 纯 stdlib urllib
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass, field
from typing import List, Optional

from .scanner import Finding

DEFAULT_BASE = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_TIMEOUT = 60
MAX_DIFF_CHARS = 8000  # 防超长 diff 爆 token

_REVIEW_PROMPT = """你是独立代码评审员。你没有任何关于这些代码改动的上下文, 只依据下面材料判断。

任务: 审查 git diff, 找出【静态扫描器无法发现】的问题。重点关注:
1. LOGIC: 逻辑错误 (条件反转/边界错误/死代码/错误处理缺失)
2. SECURITY: 静态扫描器漏掉的逻辑级安全问题 (权限绕过/竞态/敏感数据流)
3. DESIGN: 明显设计缺陷 (仅当影响正确性时)

规则:
- 只报确定的问题, 不确定的不要报 (误报成本高)
- 纯风格/性能建议不报
- 返回严格 JSON, 不要任何其他文字

<static_scan_findings>
{static}
</static_scan_findings>

<code_diff>
{diff}
</code_diff>

返回格式:
{{"passed": true或false, "issues": [{{"type": "LOGIC|SECURITY|DESIGN", "file": "", "line": 0, "desc": "具体问题描述"}}], "summary": "一句话结论"}}
passed=false 当且仅当 issues 非空且类型为 LOGIC 或 SECURITY。"""


@dataclass
class LlmReviewResult:
    name: str = "llm"
    status: str = "SKIP"  # PASS / FAIL / SKIP
    detail: str = ""
    issues: List[dict] = field(default_factory=list)
    model: str = ""

    def to_dict(self) -> dict:
        return {"name": "llm", "status": self.status, "detail": self.detail,
                "findings": self.issues, "model": self.model}


def _build_prompt(diff_text: str, findings: List[Finding]) -> str:
    static_txt = "\n".join(
        f"{f.file}:{f.line} [{f.severity}] {f.message}" for f in findings[:20]) or "无"
    diff = diff_text[:MAX_DIFF_CHARS]
    if len(diff_text) > MAX_DIFF_CHARS:
        diff += f"\n... [diff 截断, 共 {len(diff_text)} 字符]"
    return _REVIEW_PROMPT.format(static=static_txt, diff=diff)


def _call_api(prompt: str, base_url: str, model: str, api_key: str,
              timeout: int) -> Optional[str]:
    """调用 OpenAI 兼容 chat/completions, 返回 content 文本。失败返回 None。"""
    url = base_url.rstrip("/") + "/chat/completions"
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "你是资深代码评审员, 输出严格 JSON。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 1500,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except Exception:
        return None


def _parse_verdict(content: str) -> Optional[dict]:
    """从 LLM 输出提取 JSON verdict。容忍 markdown 围栏/前后杂文。"""
    if not content:
        return None
    m = re.search(r"\{.*\}", content, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def llm_review(diff_text: str, findings: List[Finding],
               base_url: Optional[str] = None, model: Optional[str] = None,
               api_key: Optional[str] = None, timeout: int = DEFAULT_TIMEOUT) -> LlmReviewResult:
    """执行 LLM 独立评审门。API 未配置/不可用 -> SKIP (不阻断)。"""
    key = api_key or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        return LlmReviewResult(status="SKIP", detail="未配置 LLM API key (DEEPSEEK_API_KEY/OPENAI_API_KEY)")
    base = base_url or os.environ.get("LLM_BASE_URL") or DEFAULT_BASE
    mdl = model or os.environ.get("LLM_MODEL") or DEFAULT_MODEL

    prompt = _build_prompt(diff_text, findings)
    content = _call_api(prompt, base, mdl, key, timeout)
    if content is None:
        return LlmReviewResult(status="SKIP", detail=f"LLM API 调用失败 (base={base}, model={mdl})")

    verdict = _parse_verdict(content)
    if verdict is None:
        return LlmReviewResult(status="SKIP", detail=f"LLM 响应无法解析为 JSON: {content[:200]}")

    issues = verdict.get("issues", [])
    blocking = [i for i in issues if i.get("type") in ("LOGIC", "SECURITY")]
    if blocking:
        detail = "; ".join(f"{i.get('file','?')}:{i.get('line','?')} [{i.get('type')}] {i.get('desc','')}"
                           for i in blocking[:5])
        return LlmReviewResult(status="FAIL", detail=f"LLM 发现 {len(blocking)} 处逻辑/安全问题: {detail}",
                               issues=blocking, model=mdl)
    return LlmReviewResult(status="PASS",
                           detail=verdict.get("summary", "LLM 评审通过") or "LLM 评审通过",
                           issues=issues, model=mdl)


if __name__ == "__main__":
    # 自测: 无 API key 时应 SKIP
    r = llm_review("+++ b/x.py\n+    x = 1\n", [])
    print(f"no-key -> {r.status}: {r.detail}")
