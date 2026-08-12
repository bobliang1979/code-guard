"""scanner 单元测试。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from code_guard.scanner import parse_diff, scan_diff, scan_code, Finding


def test_parse_diff_tracks_lines():
    diff = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,3 +1,5 @@
 def ok():
+    x = 1
+    eval(x)
-    old = 2
     return x
"""
    rows = parse_diff(diff)
    files = {r[0] for r in rows}
    assert files == {"app.py"}
    # 新增行: x=1 (line 2), eval(x) (line 3)
    assert (rows[0][1], rows[1][1]) == (2, 3)


def test_scan_diff_finds_danger():
    diff = """+++ b/app.py
@@ -1,1 +1,2 @@
+    os.system("rm -rf /")
"""
    findings = scan_diff(diff)
    assert len(findings) == 1
    assert findings[0].severity == "HIGH"
    assert findings[0].file == "app.py"


def test_scan_diff_skips_comments():
    diff = """+++ b/app.py
@@ -1,1 +1,3 @@
+    # os.system("rm -rf /")
+    // eval(x)
+    ok()
"""
    assert scan_diff(diff) == []


def test_scan_code_good_clean():
    good = '''import subprocess
def f(data):
    subprocess.run(["ls", data])
    conn.execute("SELECT * FROM t WHERE id=?", (data,))
    el.textContent = data
'''
    assert scan_code(good) == []


def test_dedupe_same_line():
    """同一行命中多条规则 -> 只保留最高严重度。"""
    diff = """+++ b/app.py
@@ -1,1 +1,2 @@
+    api_key = "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"
"""
    findings = scan_diff(diff)
    assert len(findings) == 1
    assert findings[0].severity == "BLOCKER"


def test_sql_injection_detected():
    diff = """+++ b/db.py
@@ -1,1 +1,2 @@
+    cursor.execute(f"SELECT * FROM users WHERE id={uid}")
"""
    findings = scan_diff(diff)
    assert any(f.severity == "BLOCKER" for f in findings)


def test_innerhtml_detected():
    diff = """+++ b/ui.js
@@ -1,1 +1,2 @@
+    el.innerHTML = userData;
"""
    findings = scan_diff(diff)
    assert any("XSS" in f.message for f in findings)
