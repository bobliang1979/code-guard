"""gates 单元测试。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from code_guard.gates import static_gate, fake_pass_gate, detect_test_command


def test_static_gate_blocks_blocker():
    diff = """+++ b/app.py
@@ -1,1 +1,2 @@
+    eval(user_input)
"""
    r = static_gate(diff)
    assert r.status == "FAIL"
    assert len(r.findings) == 1


def test_static_gate_passes_clean():
    r = static_gate("+++ b/app.py\n@@ -1,1 +1,2 @@\n+    x = 1\n")
    assert r.status == "PASS"


def test_static_gate_medium_only_is_pass():
    diff = """+++ b/app.py
@@ -1,1 +1,2 @@
+    requests.get(url, verify=False)
"""
    r = static_gate(diff)
    assert r.status == "PASS"  # MEDIUM 不阻断


def test_fake_pass_gate_no_tests():
    diff = """+++ b/app.py
@@ -1,1 +1,2 @@
+    x = 1
"""
    r = fake_pass_gate(diff, require_tests=True)
    assert r.status == "FAIL"


def test_fake_pass_gate_with_tests():
    diff = """+++ b/app.py
@@ -1,1 +1,2 @@
+    x = 1
+++ b/test_app.py
@@ -1,1 +1,2 @@
+    assert x == 1
"""
    r = fake_pass_gate(diff)
    assert r.status == "PASS"


def test_fake_pass_gate_warn_by_default():
    diff = """+++ b/app.py
@@ -1,1 +1,2 @@
+    x = 1
"""
    r = fake_pass_gate(diff)
    assert r.status == "WARN"


def test_detect_test_command_fallback(tmp_path):
    (tmp_path / "test_x.py").write_text("def test_x(): pass")
    cmd = detect_test_command(str(tmp_path))
    assert cmd is not None and cmd[-1] == "--tb=no"


def test_detect_test_command_none(tmp_path):
    (tmp_path / "main.py").write_text("print(1)")
    assert detect_test_command(str(tmp_path)) is None
