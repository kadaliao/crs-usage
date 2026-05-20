# crs-usage

[![PyPI version](https://img.shields.io/pypi/v/crs-usage.svg)](https://pypi.org/project/crs-usage/)
[![Python](https://img.shields.io/pypi/pyversions/crs-usage.svg)](https://pypi.org/project/crs-usage/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

通过本地 [Codex](https://github.com/openai/codex) 配置查询 [claude-relay-service](https://github.com/Wei-Shaw/claude-relay-service) 用量、限额、速率窗口与模型细分的 CLI。零依赖，单文件实现。

读 `~/.codex/config.toml` 的 `[model_providers.*]`，按 provider 的 `env_key` 或 `~/.codex/auth.json` 解析 API key，并发调用：

- `{base_origin}/apiStats/api/user-stats` — 累计用量、限额、速率窗口
- `{base_origin}/apiStats/api/user-model-stats` — 按 daily / monthly / alltime 拆分的模型细分

## 快速开始

最简单的方式（无需安装）：

```bash
uvx crs-usage
```

或直接从 GitHub 跑：

```bash
uvx --from git+https://github.com/kadaliao/crs-usage crs-usage
```

也可以装到本地工具集：

```bash
uv tool install crs-usage
crs-usage
```

## 用法

```text
crs-usage [--provider NAME] [--key KEY] [--base-url URL]
          [--config PATH] [--auth PATH] [--json] [--timeout SEC]
          [--period {daily,monthly,alltime,all}] [--top N] [--no-models]
```

常用参数：

- `--provider <name>` 只查指定 provider
- `--key <key> --base-url <url>` 跳过 codex 解析，直接查任意 CRS 实例
- `--period <p>` 模型细分时段，默认 `all`（同时拉 daily / monthly / alltime）
- `--top N` 文本输出每个时段展示前 N 个模型，默认 5；`0` 表示全部
- `--no-models` 关闭模型细分查询（只看用量/限额）
- `--json` 输出原始 JSON（含模型细分，适合 `jq`）
- `--timeout <sec>` HTTP 超时，默认 15

## Key 解析优先级

1. `--key` 命令行参数
2. `[model_providers.<name>].env_key` 指定的环境变量（如 `CRS_OAI_KEY`）
3. `~/.codex/auth.json` 中的 `OPENAI_API_KEY`

## 输出示例

```text
■ aihezu  https://cc.aihezu.dev  key 来源 env:CRS_OAI_KEY
  Key: Kada  id=07825a09-37f3-46f7-b65f-847795eeb2f2  启用  永不过期

  📊 累计用量
    请求      72,859
    Tokens    5,562,101,234
              输入 438,379,205 / 输出 29,638,344
              缓存创建 64,869,062 / 读取 5,029,214,623
    费用      $2,977.1663

  💰 限额
    今日费用  $9.1212 / $100.0000  (9.1%)
    总费用    $2,977.1663（无上限）
    速率窗口  未配置

  🧠 模型细分
    [今日]  3 个模型
      模型          请求     Tokens         输入/输出       缓存读写     费用
      ────────────  ────  ─────────  ────────────────  ─────────────  ───────
      gpt-5.5         89  5,656,244  552,906 / 42,346  0 / 5,060,992  $6.5654
      gpt-5.4         57  2,443,984  497,096 / 35,592  0 / 1,911,296  $2.2545
      gpt-5.4-mini     6    388,201   384,265 / 2,912      0 / 1,024  $0.3014
    [本月]  4 个模型
      ...
    [累计]  23 个模型
      ...
      （还有 18 个模型未列出，可用 --top 查看更多）
```

> key 配置了 rate limit 窗口时，「速率窗口」会显示窗口长度（自动按 `Hh/m` 换算）、剩余时间，以及当前窗口内的请求数 / Tokens / 费用与对应限额。

## 要求

- Python ≥ 3.11（依赖 stdlib `tomllib`，零第三方依赖）
- 一个本地 `~/.codex/config.toml` 配置（或通过 `--key` `--base-url` 直接指定）

## License

[MIT](LICENSE)
