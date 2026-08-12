"""ledger 单元测试 — 账本记录/加载/聚合。"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from code_guard.ledger import record, load, stats, render_stats, ledger_path


def _report(verdict="BLOCK", gate_status=None, issue_detail="eval() 风险"):
    gates = [
        {"name": "static", "status": gate_status or "FAIL",
         "detail": f"{issue_detail} — 代码注入" if gate_status != "PASS" else ""},
        {"name": "tests", "status": "SKIP", "detail": ""},
        {"name": "coverage", "status": "WARN",
         "detail": "⚠ 生产代码改动但测试零改动"},
    ]
    return {"version": "0.1.0", "verdict": verdict, "gates": gates,
            "summary": "x"}


def test_record_and_load(tmp_path):
    path = record(_report(), str(tmp_path), base="HEAD~1")
    assert path is not None
    assert path == ledger_path(str(tmp_path))
    records = load(str(tmp_path))
    assert len(records) == 1
    assert records[0]["verdict"] == "BLOCK"
    assert records[0]["base"] == "HEAD~1"
    assert records[0]["gates"]["static"] == "FAIL"
    assert len(records[0]["issues"]) == 2  # static FAIL + coverage WARN


def test_record_append_multiple(tmp_path):
    for _ in range(3):
        record(_report(), str(tmp_path))
    assert len(load(str(tmp_path))) == 3


def test_load_missing_dir_returns_empty(tmp_path):
    assert load(str(tmp_path)) == []


def test_load_tolerates_corrupt_lines(tmp_path):
    p = ledger_path(str(tmp_path))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write('{"verdict": "PASS"}\n')
        f.write("NOT-JSON-LINE\n")
        f.write('{"verdict": "BLOCK"}\n')
    assert len(load(str(tmp_path))) == 2


def test_stats_aggregation(tmp_path):
    record(_report(gate_status="FAIL", issue_detail="eval()"), str(tmp_path))
    record(_report(gate_status="FAIL", issue_detail="eval()"), str(tmp_path))
    record(_report(gate_status="FAIL", issue_detail="os.system()"), str(tmp_path))
    record(_report(verdict="PASS", gate_status="PASS"), str(tmp_path))
    s = stats(str(tmp_path))
    assert s["total_checks"] == 4
    assert s["verdicts"] == {"BLOCK": 3, "PASS": 1}
    # 3 BLOCK x 2 issues (static+coverage) + 1 PASS x 1 issue (coverage WARN)
    assert s["issue_count"] == 7, s["issue_count"]
    # coverage 模式出现 4 次 (每条都有) > static eval 2 次 -> top1 是 coverage
    patterns = dict(s["top_patterns"])
    assert patterns.get("static: eval() — 代码注入") == 2
    assert patterns.get("static: os.system() — 代码注入") == 1
    assert s["top_patterns"][0][0].startswith("coverage:")


def test_stats_days_filter(tmp_path):
    import time
    record(_report(), str(tmp_path))
    s = stats(str(tmp_path), days=1)
    assert s["total_checks"] == 1
    time.sleep(1.1)  # 跨秒, 确保 ts < cutoff
    s0 = stats(str(tmp_path), days=0)  # 0 天窗口 -> 无记录
    assert s0["total_checks"] == 0


def test_render_stats_contains_sections(tmp_path):
    record(_report(), str(tmp_path))
    text = render_stats(stats(str(tmp_path)))
    assert "失败归因账本" in text
    assert "检查次数" in text
    assert "高频失败模式" in text
