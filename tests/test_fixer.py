"""fixer 单元测试 — 自动修复建议。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from code_guard.fixer import suggest_fixes, render_fixes, apply_fixes


def _diff(*lines):
    return "+++ b/app.py\n@@ -1,1 +1,5 @@\n" + "\n".join("+    " + l for l in lines)


def test_eval_suggestion():
    fixes = suggest_fixes(_diff("result = eval(user_input)"))
    assert len(fixes) == 1
    f = fixes[0]
    assert f.kind == "eval" and f.confidence == "HIGH"
    assert "ast.literal_eval" in f.after


def test_eval_nested_args_manual():
    """eval(fn(x)) 嵌套调用无法确定性替换 -> manual。"""
    fixes = suggest_fixes(_diff("result = eval(transform(data))"))
    assert fixes and fixes[0].confidence == "MANUAL"


def test_os_system_literal():
    fixes = suggest_fixes(_diff('os.system("rm -rf /tmp/x")'))
    assert fixes and fixes[0].kind == "os_system"
    assert "subprocess.run" in fixes[0].after and "shell=False" in fixes[0].after


def test_os_system_variable_manual():
    fixes = suggest_fixes(_diff('os.system("rm -rf " + user_input)'))
    assert fixes and fixes[0].confidence == "MANUAL"


def test_shell_true_removed():
    fixes = suggest_fixes(_diff('subprocess.run(cmd, shell=True)'))
    assert fixes and fixes[0].kind == "shell_true"
    assert "shell=False" in fixes[0].after and "shell=True" not in fixes[0].after


def test_secret_manual():
    fixes = suggest_fixes(_diff('api_key = "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"'))
    assert fixes and fixes[0].kind == "secret"
    assert fixes[0].confidence == "MANUAL"


def test_clean_code_no_fixes():
    fixes = suggest_fixes(_diff("x = 1", "return x"))
    assert fixes == []


def test_render_fixes_empty():
    assert "无自动修复建议" in render_fixes([])


def test_render_fixes_counts():
    fixes = suggest_fixes(_diff('result = eval(user_input)'))
    text = render_fixes(fixes)
    assert "可自动修复 1 条" in text


def test_apply_fixes_writes_file(tmp_path):
    (tmp_path / "app.py").write_text("    result = eval(user_input)\n    x = 1\n", encoding="utf-8")
    fixes = suggest_fixes(_diff("result = eval(user_input)"))
    fixes[0].file = "app.py"
    fixes[0].line = 1
    applied, errors = apply_fixes(str(tmp_path), fixes)
    assert applied == 1 and errors == []
    content = (tmp_path / "app.py").read_text(encoding="utf-8")
    assert "ast.literal_eval(user_input)" in content


def test_apply_skips_manual(tmp_path):
    (tmp_path / "app.py").write_text("    api_key = \"sk-ABC123\"\n", encoding="utf-8")
    fixes = suggest_fixes(_diff('api_key = "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"'))
    fixes[0].file = "app.py"
    applied, _ = apply_fixes(str(tmp_path), fixes)
    assert applied == 0  # MANUAL 不落地
