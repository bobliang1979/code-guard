# code-guard — 编码代理安全护栏

[![CI](https://github.com/bobliang1979/code-guard/actions/workflows/ci.yml/badge.svg)](https://github.com/bobliang1979/code-guard/actions)
[![License](https://img.shields.io/github/license/bobliang1979/code-guard)](LICENSE)

拦截 LLM 编码代理 (Cursor/Claude Code/Codex) 提交的危险代码。CI 一条命令接入，零依赖。

## 为什么存在

LLM 代理生成代码的三大痛点：
1. **危险模式** — 硬编码密钥、`eval`/`exec`、命令注入、SQL 拼接、XSS
2. **测试回归** — 声称"测试通过"实际破坏了存量测试
3. **假 PASS** — 改了生产代码但测试零改动就提交 (LLM 代理典型作弊路径)

## 三扇门

| 门 | 判定 | 默认 |
|---|------|------|
| **static** 静态安全门 | 新增行含 BLOCKER/HIGH 危险模式 | BLOCK |
| **tests** 测试回归门 | 跑测试，与 baseline 对比只拦新增失败 | BLOCK |
| **coverage** 假PASS拦截门 | 生产代码改动但测试零改动 | WARN (可 --require-tests 升级 BLOCK) |

核心设计: **只扫 diff 新增行** (非全库) — 零存量噪音，CI 友好，跨语言 (Python/JS/TS/Go/SQL)。

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
      - uses: bobliang1979/code-guard@v0.1
        with:
          require-tests: 'true'   # 严格模式: 生产改动必须带测试
```

参数: `base`(默认 PR base sha) / `require-tests` / `timeout` / `update-baseline`(首次接入建议 true)。

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

- **安全规则库源码自命中**: 用 code-guard 扫描安全工具自身 (含危险模式正则定义表) 会命中规则字符串本身。这是预期行为 — 规则定义行包含 `eval(` 等字面量。真实用户 diff 不受影响。
- **字符串数据误报**: 代码里含 `"eval("` 字符串字面量 (如测试断言) 会命中。v0.2 计划引入 AST 上下文判断 (仅匹配可执行位置)。

## 路线图

- [ ] v0.2: 自动修复建议 (安全替换: eval→literal_eval, os.system→subprocess)
- [ ] v0.3: GitHub App 形态 (PR 评论 + required check)
- [ ] v0.4: LLM 独立评审门 (多模型交叉评审 diff, 可选启用)
- [ ] v0.5: 失败归因账本 (跨 PR 统计代理失败模式)

## 测试

```bash
python -m pytest tests/ -v
```
