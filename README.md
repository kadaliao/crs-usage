# crs-usage

[![PyPI version](https://img.shields.io/pypi/v/crs-usage.svg)](https://pypi.org/project/crs-usage/)
[![Python](https://img.shields.io/pypi/pyversions/crs-usage.svg)](https://pypi.org/project/crs-usage/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

通过本地 [Codex](https://github.com/openai/codex) 配置查询 [claude-relay-service](https://github.com/Wei-Shaw/claude-relay-service) 用量、限制和剩余额度的 CLI。零依赖，单文件实现。

读 `~/.codex/config.toml` 的 `[model_providers.*]`，按 provider 的 `env_key` 或 `~/.codex/auth.json` 解析 API key，调用 `{base_origin}/apiStats/api/user-stats` 拉取使用量。

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
```

常用参数：

- `--provider <name>` 只查指定 provider
- `--key <key> --base-url <url>` 跳过 codex 解析，直接查任意 CRS 实例
- `--json` 输出原始 JSON（适合 `jq`）
- `--timeout <sec>` HTTP 超时，默认 15

## Key 解析优先级

1. `--key` 命令行参数
2. `[model_providers.<name>].env_key` 指定的环境变量（如 `CRS_OAI_KEY`）
3. `~/.codex/auth.json` 中的 `OPENAI_API_KEY`

## 输出示例

```text
■ aihezu  (https://cc.aihezu.dev)  key from env:CRS_OAI_KEY
  Key: my-key  id=07825a09-...  active=true  expires=never
  Usage (total):
    Requests : 72,642
    Tokens   : 5,548,253,083  (in 436,025,255 / out 29,521,295 / cache_create 64,869,062 / cache_read 5,017,837,471)
    Cost     : $2961.17
  Limits:
    Daily Cost : $19.7727 / $100.0000  (19.8%)
    Total Cost : unlimited
    Rate Window: 13/100 req, 234,567/1,000,000 tok, $0.4500/$10.0000  window=60m  剩余 12m34s
```

## 要求

- Python ≥ 3.11（依赖 stdlib `tomllib`，零第三方依赖）
- 一个本地 `~/.codex/config.toml` 配置（或通过 `--key` `--base-url` 直接指定）

## License

[MIT](LICENSE)
