# code-guard — 编码代理安全护栏

[![CI](https://github.com/bobliang1979/code-guard/actions/workflows/ci.yml/badge.svg)](https://github.com/bobliang1979/code-guard/actions)
[![License](https://img.shields.io/github/license/bobliang1979/code-guard)](LICENSE)

拦截 LLM 编码代理 (Cursor/Claude Code/Codex) 提交的危险代码。CI 一条命令接入，零依赖。

## 为什么存在

LLM 代理生成代码的三大痛点：
1. **危险模式** — 硬编码密钥、`eval`/`exec`、命令注入、SQL 拼接、XSS
2. **测试回归** — 声称"测试通过"实际破坏了存量测试
3. **假 PASS** — 改了生产代码但测试零改动就提交 (LLM 代理典型作弊路径)

## 四扇门

| 门 | 判定 | 默认 |
|---|------|------|
| **static** 静态安全门 | 新增行含 BLOCKER/HIGH 危险模式 | BLOCK |
| **tests** 测试回归门 | 跑测试，与 baseline 对比只拦新增失败 | BLOCK |
| **coverage** 假PASS拦截门 | 生产代码改动但测试零改动 | WARN (可 --require-tests 升级 BLOCK) |
| **llm** LLM独立评审门 (v0.4) | 找静态扫描器漏掉的逻辑/安全问题 | 关闭 (--llm-review 启用) |

核心设计: **只扫 diff 新增行** (非全库) — 零存量噪音，CI 友好，跨语言 (Python/JS/TS/Go/SQL)。

## LLM 独立评审门 (v0.4)

静态正则找不到逻辑错误 (条件反转/边界/竞态) — 这是 LLM 门的独特价值。实测案例: 静态门 PASS 的折扣逻辑 bug 被 LLM 门拦截。

```bash
# 本地
code-guard check --dir . --base HEAD~1 --llm-review
# 环境变量: DEEPSEEK_API_KEY 或 OPENAI_API_KEY (任意 OpenAI 兼容 provider)
# 可选: LLM_BASE_URL (默认 https://api.deepseek.com), LLM_MODEL (默认 deepseek-chat)
```

GitHub Actions (需配置 secret):

```yaml
- uses: bobliang1979/code-guard@v0.2.0
  with:
    llm-review: 'true'
  env:
    DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
```

fail-closed 语义: LLM 报 LOGIC/SECURITY 问题 → BLOCK; API 不可用/超时/解析失败 → SKIP (不阻断 CI)。

## 安装

```bash
pip install -e .
```

## 用法

```bash
# 检查暂存区+工作区 diff (CI 或 pre-commit 用)
code-guard check --dir .

# 检查某次提交的 diff
code-guard check --dir . --base HEAD~1

# 严格模式: 生产代码改动必须带测试
code-guard check --dir . --require-tests

# JSON 输出 (CI 解析)
code-guard check --dir . --json

# 内嵌演示
code-guard demo
```

退出码: `0`=PASS, `1`=BLOCK, `2`=ERROR (CI 直接 `exit $?` 即可门禁)。

## CI 接入 (GitHub Actions — 企业推荐, 一行引用)

```yaml
name: code-guard
on: [pull_request]
jobs:
  guard:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0          # 浅克隆自愈由 action 内部处理, 但全量更稳
      - uses: bobliang1979/code-guard@v0.2.0
        with:
          require-tests: 'true'   # 严格模式: 生产改动必须带测试
```

参数: `base`(默认 PR base sha) / `require-tests` / `timeout` / `update-baseline`(首次接入建议 true) / `include-tests`(默认跳过测试文件)。

## Baseline (只拦新增回归)

```bash
code-guard check --dir . --update-baseline   # 记录当前失败数为基线
# 之后: 失败数 <= baseline 视为存量问题, 不阻断
```

## 设计决策

- **零依赖** — 纯 stdlib，正则+AST，无 LLM 调用 (门禁必须确定、可复现、无成本)
- **fail-closed** — 高危模式必拦，宁误报不放过
- **同行去重** — 同一行多条规则命中只保留最高严重度
- **环境缺依赖 → SKIP** 非 BLOCK (pytest 未装不算代码问题)

## 已知边界

- **测试文件默认跳过**: 静态门跳过 test_*/tests//spec/__tests__ 文件 — 测试常含故意构造的危险样例 (验证检测器/mock), 且不进入生产。需扫描用 `--include-tests`。
- **字符串数据误报已缓解**: 规则排除字符串字面量内模式 (`BLOCKED_PATTERNS=["eval("]` 黑名单定义不误报, 实战 trauma-driven-agent 验证) + `\b` 前缀排除规则源码自命中 (code-guard 可自扫)。

## 自动修复建议 (v0.2)

确定性安全替换 (正则驱动, 非 LLM), 只改可安全变换的:

```bash
code-guard fix --dir . --base HEAD~1          # 只显示建议
code-guard fix --dir . --base HEAD~1 --apply  # 落地 HIGH 置信度修复
code-guard fix --dir . --apply --check        # 落地后自动复扫验证
```

可自动修复: `eval(x)`→`ast.literal_eval(x)` / `os.system("字面量")`→`subprocess.run([...], shell=False)` / 移除 `shell=True`。
需人工 (标记 MANUAL): 硬编码密钥、参数非字面量的危险调用 (无法确定性替换, 绝不生成错误代码)。

## 失败归因账本 (v0.5)

每次 `check` 自动记录到 `<repo>/.code-guard/ledger.jsonl` (写失败不阻断)。聚合统计帮助企业看到跨 PR 的失败模式:

```bash
code-guard stats --dir .              # 全部历史
code-guard stats --dir . --days 7     # 最近 7 天
# 输出: verdict 分布 / 门状态 / 高频失败模式 Top10
# 例: 3 个 PR 都因 eval() 被拦 -> 反哺改进 LLM 代理提示词
```

账本文件已被 .gitignore 排除 (本地数据, 不进仓库)。

## 路线图

- [x] v0.1 三扇门 MVP (静态/测试/假PASS)
- [x] v0.2 自动修复建议 (确定性安全替换 + 落地复扫闭环)
- [x] v0.3 GitHub Actions composite action 一行接入
- [x] v0.4 LLM 独立评审门 (逻辑/安全问题, 可选启用)
- [x] v0.5 失败归因账本 (跨 PR 失败模式统计)

## 测试

```bash
python -m pytest tests/ -v
```
