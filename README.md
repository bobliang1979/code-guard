# code-guard — LLM Agent Code Guard / 编码代理安全护栏

[![CI](https://github.com/bobliang1979/code-guard/actions/workflows/ci.yml/badge.svg)](https://github.com/bobliang1979/code-guard/actions)
[![action-self-test](https://github.com/bobliang1979/code-guard/actions/workflows/action-self-test.yml/badge.svg)](https://github.com/bobliang1979/code-guard/actions/workflows/action-self-test.yml)
[![License](https://img.shields.io/github/license/bobliang1979/code-guard)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](pyproject.toml)
[![PyPI](https://img.shields.io/badge/PyPI-pending-blueviolet)](https://pypi.org/project/code-guard/)

> **A zero-dependency guardrail that blocks dangerous code written by LLM coding agents (Cursor / Claude Code / Codex) before it lands in your repository.**
>
> **零依赖的编码护栏——在 LLM 编码代理（Cursor / Claude Code / Codex）生成的危险代码进入仓库之前拦截它。**

---

## Table of Contents / 目录

- [Why / 为什么存在](#why--为什么存在)
- [Features / 特性](#features--特性)
- [The Five Gates / 五扇门](#the-five-gates--五扇门)
- [Quick Start / 快速开始](#quick-start--快速开始)
- [Installation / 安装](#installation--安装)
- [CLI Reference / 命令行参考](#cli-reference--命令行参考)
- [GitHub Actions Integration / CI 接入](#github-actions-integration--ci-接入)
- [LLM Review Gate / LLM 独立评审门](#llm-review-gate--llm-独立评审门)
- [Auto-Fix / 自动修复](#auto-fix--自动修复)
- [Failure Ledger / 失败归因账本](#failure-ledger--失败归因账本)
- [Architecture / 架构设计](#architecture--架构设计)
- [False-Positive Prevention / 误报治理](#false-positive-prevention--误报治理)
- [Known Limitations / 已知边界](#known-limitations--已知边界)
- [Roadmap / 路线图](#roadmap--路线图)
- [Development / 开发](#development--开发)
- [License / 许可证](#license--许可证)

---

## Why / 为什么存在

**English:** LLM coding agents are now part of the daily workflow, but they introduce three classes of risk that human review often misses:

1. **Dangerous patterns** — hardcoded secrets (`sk-...`, `AKIA...`), `eval`/`exec`, command injection via `os.system`, SQL string concatenation, XSS via `innerHTML`.
2. **Test regression** — the agent claims "all tests pass" while silently breaking existing suites.
3. **Fake PASS** — production code changes shipped with zero test changes, the classic LLM-agent shortcut.

code-guard automates the review layer that catches all three, with **deterministic, reproducible, zero-cost checks** that run in seconds inside CI.

**中文：** LLM 编码代理已成为日常工作流的一部分，但它们引入了三类人工评审经常漏掉的风险：

1. **危险模式** — 硬编码密钥（`sk-...`、`AKIA...`）、`eval`/`exec`、通过 `os.system` 的命令注入、SQL 字符串拼接、通过 `innerHTML` 的 XSS。
2. **测试回归** — 代理声称"全部测试通过"，实则悄悄破坏了存量测试。
3. **假 PASS** — 生产代码改动伴随零测试改动就提交——LLM 代理的典型捷径。

code-guard 将这三类问题的审查层自动化，提供**确定性、可复现、零成本**的检查，在 CI 内数秒完成。

---

## Features / 特性

| Feature / 特性 | Description / 说明 |
|---|---|
| 🚪 **Five gates** / 五扇门 | static security / test regression / fake-PASS / LLM review / auto-fix |
| 🎯 **Diff-scoped scanning** / 只扫 diff | Only added lines are inspected — zero noise from pre-existing code |
| 🌐 **Cross-language** / 跨语言 | Python, JavaScript/TypeScript, Go, Rust, SQL patterns in one engine |
| 🔌 **Zero dependencies** / 零依赖 | Pure stdlib (urllib/re/json) — installs in any environment instantly |
| ⚙️ **GitHub Actions one-liner** / 一行接入 CI | `uses: bobliang1979/code-guard@v0.2.0` |
| 🤖 **Optional LLM review** / 可选 LLM 评审 | DeepSeek / OpenAI / any OpenAI-compatible provider |
| 🔧 **Auto-fix with re-verify loop** / 自动修复+复扫闭环 | Deterministic safe replacements, `--apply --check` |
| 📊 **Failure ledger** / 失败归因账本 | Cross-PR failure-pattern statistics for agent-prompt improvement |
| 🧪 **Dogfooding proven** / 自举验证 | code-guard audits itself in CI — self-scan must PASS |
| ✅ **46 tests, CI matrix py3.9+3.11** / 完整测试 | Verified on real repos (trauma-driven-agent, code-engineer-ai) |

---

## The Five Gates / 五扇门

| Gate / 门 | What it checks / 判定 | Default / 默认 |
|---|---|---|
| **static** — 静态安全门 | BLOCKER/HIGH dangerous patterns in added lines (secrets, eval/exec, command injection, SQL concat, XSS) | **BLOCK** |
| **tests** — 测试回归门 | Runs the test suite; only **new** failures block (baseline-aware) | **BLOCK** |
| **coverage** — 假PASS拦截门 | Production code changed but zero test files touched | WARN (→BLOCK with `--require-tests`) |
| **llm** — LLM 独立评审门 | Logic/security issues a regex cannot see (condition flips, races, edge cases) | OFF (`--llm-review`) |
| **fix** — 自动修复 | Deterministic safe replacements with apply + re-verify | OFF (`fix` subcommand) |

**Core design / 核心设计：** scan **diff added lines only** (not the whole repo) — zero legacy noise, CI-friendly, cross-language.

---

## Quick Start / 快速开始

```bash
# 1. Install / 安装
pip install https://github.com/bobliang1979/code-guard/releases/download/v0.2.0/code_guard-0.2.0-py3-none-any.whl

# 2. Check your latest commit / 检查最近提交
code-guard check --dir . --base HEAD~1

# 3. Expected output / 预期输出
# code-guard v0.2.0 — verdict: PASS
#   [PASS] static: 无命中
#   [PASS] tests: 全部测试通过
#   [WARN] coverage: ⚠ 生产代码改动 1 文件但测试零改动
# summary: static=PASS; tests=PASS; coverage=WARN
# exit code: 0 = PASS, 1 = BLOCK, 2 = ERROR
```

**Exit codes / 退出码:** `0`=PASS · `1`=BLOCK · `2`=ERROR — wire `exit $?` directly into CI.

---

## Installation / 安装

### From GitHub Release (recommended) / 从 GitHub Release 安装（推荐）

```bash
pip install https://github.com/bobliang1979/code-guard/releases/download/v0.2.0/code_guard-0.2.0-py3-none-any.whl
```

### From source / 从源码

```bash
git clone https://github.com/bobliang1979/code-guard.git
cd code-guard && pip install .
```

### PyPI (pending / 待发布)

The name `code-guard` is reserved on PyPI. Two publish paths are pre-wired in `.github/workflows/publish-pypi.yml`:

- **A. Trusted Publishing (OIDC, no token)** — PyPI → project page → *Publishing* → *Add pending publisher* (owner `bobliang1979` / repo `code-guard` / workflow `publish-pypi.yml`). Configure once, then every `git tag vX.Y.Z && git push` publishes automatically.
- **B. API token** — add `PYPI_TOKEN` to GitHub repo Secrets; tag pushes then auto-publish.

---

## CLI Reference / 命令行参考

### `check` — run all gates / 执行全部门禁

```bash
code-guard check [options]

  --dir DIR              repo root (default: current dir) / 仓库根目录
  --base REF             git baseline, compares REF..HEAD / git 基线
  --diff FILE|-          read diff from file or stdin / 从文件/标准输入读 diff
  --json                 machine-readable JSON report / JSON 报告
  --require-tests        production changes must include tests (fake-PASS → BLOCK) / 强制带测试
  --include-tests        also scan test files (default: skipped) / 同时扫描测试文件
  --llm-review           enable LLM review gate / 启用 LLM 评审门
  --update-baseline      record current failures as baseline / 记录当前失败数为基线
  --timeout SEC          test timeout (default 120) / 测试超时
  --no-ledger            skip ledger recording / 跳过账本记录
```

### `fix` — auto-fix suggestions / 自动修复建议

```bash
code-guard fix --dir . --base HEAD~1          # show suggestions only / 仅显示建议
code-guard fix --dir . --base HEAD~1 --apply  # apply HIGH-confidence fixes / 落地高置信修复
code-guard fix --dir . --apply --check        # apply + re-scan verification / 落地+复扫验证
```

### `stats` — failure ledger / 失败归因统计

```bash
code-guard stats --dir .            # all history / 全部历史
code-guard stats --dir . --days 7   # last 7 days / 最近 7 天
```

### `demo` — built-in self-test / 内嵌自测

```bash
code-guard demo    # scanner self-check, must end PASS / 扫描器自测
```

---

## GitHub Actions Integration / CI 接入

### One-line integration (recommended for teams) / 一行接入（企业推荐）

```yaml
name: code-guard
on: [pull_request]
jobs:
  guard:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: bobliang1979/code-guard@v0.2.0
        with:
          require-tests: 'true'      # strict mode: production changes must ship tests
```

### Action inputs / Action 参数

| Input / 参数 | Default / 默认 | Description / 说明 |
|---|---|---|
| `base` | PR base sha | Baseline ref; on push events falls back to `github.event.before` (auto) / push 事件自动回退 |
| `require-tests` | `false` | Fake-PASS gate → BLOCK / 假PASS 升级为拦截 |
| `timeout` | `120` | Test timeout seconds / 测试超时 |
| `update-baseline` | `false` | Record current failures as baseline (recommended `true` on first adoption) / 首次接入建议 true |
| `include-tests` | `false` | Also scan test files / 同时扫描测试文件 |
| `llm-review` | `false` | Enable LLM review gate (needs API key secret) / 启用 LLM 评审门 |

The action is **self-healing**: it resolves the correct base for both PR and push events, fetches missing refs on shallow clones, and installs from its own source (`$GITHUB_ACTION_PATH`) — zero version drift.

### Baseline (block only NEW regressions) / Baseline（只拦新增回归）

```bash
code-guard check --dir . --update-baseline   # record current failures as baseline
# afterwards: failures <= baseline are pre-existing, do not block
```

---

## LLM Review Gate / LLM 独立评审门

**Why:** regex cannot see logic errors — condition flips, boundary bugs, races, missing error handling. This gate adds an independent LLM reviewer that complements the deterministic gates.

**为什么需要：** 正则看不到逻辑错误——条件反转、边界 bug、竞态、缺失的错误处理。此门增加独立的 LLM 评审者，与确定性门互补。

*Real-world case / 实测案例：* a discount-logic bug (non-VIP branch returning undiscounted price) passed the static gate but was **caught by the LLM gate** → BLOCK.

### Local / 本地

```bash
code-guard check --dir . --base HEAD~1 --llm-review

# Environment / 环境变量:
#   DEEPSEEK_API_KEY 或 OPENAI_API_KEY (任意 OpenAI 兼容 provider)
#   LLM_BASE_URL  (默认 https://api.deepseek.com)
#   LLM_MODEL     (默认 deepseek-chat)
```

### GitHub Actions / CI 接入

```yaml
- uses: bobliang1979/code-guard@v0.2.0
  with:
    llm-review: 'true'
  env:
    DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
```

### Fail semantics / 失败语义

- LLM reports LOGIC/SECURITY issue → **BLOCK**
- API unavailable / timeout / unparseable response → **SKIP** (never blocks CI on external failure)

---

## Auto-Fix / 自动修复

Deterministic, regex-driven safe replacements (no LLM code generation — never invents code):

| Pattern / 模式 | Replacement / 替换 | Confidence / 置信度 |
|---|---|---|
| `eval(x)` (simple arg) | `ast.literal_eval(x)` | HIGH |
| `os.system("literal")` | `subprocess.run(["literal"], shell=False)` | HIGH |
| `subprocess.*(..., shell=True)` | `shell=False` | HIGH |
| Hardcoded secrets | *n/a — manual* | MANUAL |
| Non-literal dangerous calls | *n/a — manual* | MANUAL |

```bash
code-guard fix --dir . --base HEAD~1          # show suggestions / 显示建议
code-guard fix --dir . --apply --check        # apply + re-verify / 落地 + 复扫
```

MANUAL items are never auto-applied — code-guard never generates code it cannot prove safe.

---

## Failure Ledger / 失败归因账本

Every `check` automatically appends a record to `<repo>/.code-guard/ledger.jsonl` (write failures never block). Aggregate statistics reveal **which failure patterns recur across PRs** — the feedback loop for improving your agent's system prompt.

```bash
code-guard stats --dir .              # all history
code-guard stats --dir . --days 7     # last 7 days
# Output: verdict distribution / gate status / top-10 failure patterns
# Example: 3 PRs blocked for eval() → update agent prompt to forbid eval
```

The ledger is gitignored (local data, not committed).

---

## Architecture / 架构设计

```
code_guard/
├── scanner.py      # cross-language danger-pattern regex table + unified-diff parser
│                   #   (added lines only, per-line severity dedup)
├── gates.py        # gate orchestration: static / tests (baseline) / coverage (fake-PASS)
├── llm_review.py   # OpenAI-compatible chat/completions client (stdlib urllib, fail-open)
├── fixer.py        # deterministic safe replacements + apply/verify loop
├── ledger.py       # JSONL failure ledger + aggregation statistics
└── cli.py          # check / fix / stats / demo, exit codes 0/1/2
```

### Design principles / 设计原则

1. **Deterministic by default** — gates must be reproducible and cost-free; LLM review is opt-in.
2. **Fail-closed for security** — a HIGH/BLOCKER match always blocks; false positives are acceptable over misses.
3. **Fail-open for infrastructure** — missing test framework / LLM API → SKIP, never a CI outage.
4. **Diff-scoped** — scan only added lines: zero pre-existing noise, fast, incremental.
5. **Self-auditing** — code-guard scans itself in CI (dogfood); rule-source self-matches are filtered.

---

## False-Positive Prevention / 误报治理

Four real-world false-positive sources were found and fixed (each with regression tests):

| Source / 来源 | Fix / 修复 |
|---|---|
| String literals: `BLOCKED_PATTERNS = ["eval("]` blacklist definitions | `(?<!["'])` lookbehind excludes quoted patterns |
| Rule-source self-match: `r"\beval("` inside scanner.py | `\b` prefix — no boundary between `b` and `e` in source text |
| Test files with intentional danger samples | test files skipped by default (`--include-tests` to enable) |
| Docs/README code examples | `.md/.rst/.txt/.adoc` skipped by the static gate |

---

## Known Limitations / 已知边界

- **Regex-level detection** — the static gate matches patterns, not AST semantics; logic-level issues are the LLM gate's job (opt-in).
- **Test-framework probing** — auto-detects pytest/npm/go/cargo; exotic setups may need `--timeout` tuning or a custom test command.
- **Python-centric auto-fix** — the fixer targets Python patterns; other languages get manual suggestions only.

---

## Roadmap / 路线图

- [x] **v0.1** — Three-gate MVP (static / tests / fake-PASS)
- [x] **v0.2** — Auto-fix suggestions (deterministic replacements + apply/re-verify loop)
- [x] **v0.3** — GitHub Actions composite action, one-line integration
- [x] **v0.4** — LLM review gate (logic/security issues, optional)
- [x] **v0.5** — Failure ledger (cross-PR pattern statistics)
- [ ] **PyPI publish** — Trusted Publishing (OIDC) wiring done; awaits PyPI account configuration
- [ ] **GitHub App form** — PR comments + required status check (needs public hosting)

---

## Development / 开发

```bash
git clone https://github.com/bobliang1979/code-guard.git
cd code-guard
pip install -e .

python -m pytest tests/ -v        # 46 tests
code-guard demo                    # scanner self-check
code-guard check --dir . --base HEAD~1   # dogfood: self-scan must PASS
```

**CI matrix / CI 矩阵:** py3.9 + py3.11 — unit tests, demo self-check, and a bad-PR end-to-end (must BLOCK).

**Real-repo verification / 真实仓库验证:** scanned `trauma-driven-agent` and `code-engineer-ai` histories — all PASS; a live dangerous push to `code-engineer-ai` was correctly BLOCKED.

---

## License / 许可证

[MIT](LICENSE) © 2026 bobliang1979
