"""llm_review 单元测试 — mock API 响应测门禁逻辑 (不真调网络)。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import code_guard.llm_review as lr
from code_guard.scanner import Finding


def test_no_key_skips(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    r = lr.llm_review("+++ b/x.py\n+    x = 1\n", [])
    assert r.status == "SKIP"
    assert "API key" in r.detail


def test_parse_verdict_markdown_fence():
    content = '```json\n{"passed": false, "issues": [{"type": "LOGIC", "file": "a.py", "line": 3, "desc": "off-by-one"}], "summary": "x"}\n```'
    v = lr._parse_verdict(content)
    assert v is not None and v["passed"] is False


def test_parse_verdict_with_prose_prefix():
    content = 'Review complete.\n{"passed": true, "issues": [], "summary": "looks good"}'
    v = lr._parse_verdict(content)
    assert v is not None and v["passed"] is True


def test_parse_verdict_garbage():
    assert lr._parse_verdict("not json at all") is None
    assert lr._parse_verdict("") is None


def test_build_prompt_contains_diff_and_static():
    findings = [Finding(file="a.py", line=1, severity="HIGH", message="eval()")]
    prompt = lr._build_prompt("+++ b/a.py\n+    x = eval(y)\n", findings)
    assert "a.py:1" in prompt and "eval" in prompt


def test_call_api_failure_skips(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    def fake_call(prompt, base, model, key, timeout):
        return None
    monkeypatch.setattr(lr, "_call_api", fake_call)
    r = lr.llm_review("+++ b/x.py\n+    x = 1\n", [])
    assert r.status == "SKIP"
    assert "失败" in r.detail


def test_llm_findings_block(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    def fake_call(prompt, base, model, key, timeout):
        return '{"passed": false, "issues": [{"type": "SECURITY", "file": "a.py", "line": 5, "desc": "race condition"}], "summary": "has issue"}'
    monkeypatch.setattr(lr, "_call_api", fake_call)
    r = lr.llm_review("+++ b/a.py\n+    x = 1\n", [])
    assert r.status == "FAIL"
    assert "race condition" in r.detail


def test_llm_clean_passes(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    def fake_call(prompt, base, model, key, timeout):
        return '{"passed": true, "issues": [], "summary": "clean"}'
    monkeypatch.setattr(lr, "_call_api", fake_call)
    r = lr.llm_review("+++ b/a.py\n+    x = 1\n", [])
    assert r.status == "PASS"


def test_design_issues_not_blocking(monkeypatch):
    """DESIGN 类问题不阻断 (只 LOGIC/SECURITY 阻断)。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    def fake_call(prompt, base, model, key, timeout):
        return '{"passed": true, "issues": [{"type": "DESIGN", "file": "a.py", "line": 1, "desc": "could be simpler"}], "summary": "ok"}'
    monkeypatch.setattr(lr, "_call_api", fake_call)
    r = lr.llm_review("+++ b/a.py\n+    x = 1\n", [])
    assert r.status == "PASS"
