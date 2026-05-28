# crs-usage admin 子命令设计

- 创建日期：2026-05-27
- 参考项目：[sub2api-usage](https://github.com/kadaliao/sub2api-usage)
- 目标后端：[claude-relay-service](https://github.com/Wei-Shaw/claude-relay-service)（下称 CRS）

## 1. 背景与目标

crs-usage 现在覆盖的是「单个 API Key 持有者」视角，读 codex 配置去查 `/apiStats/...` 公开端点。

CRS 同时暴露了完整的管理员视图（`/admin/*`），需要 admin 登录后才能看到全局 dashboard、所有 API Keys、上游账号池等。本次改造对齐 sub2api-usage 的 admin 形态，给 crs-usage 加上 `admin` 子命令树，支持 TUI 和非交互输出两种使用方式。

**非目标**：

- 不做 CRS 写操作（创建/删除 key、操作账号），只读。
- 不做趋势历史的本地存储/回放。
- 不做 TOTP / 二次验证（CRS 当前不需要）。
- 不做主题、不做颜色配置开关，沿用 textual 默认。

## 2. 命令行拓扑

```text
crs-usage [flags...]                              # 现有行为，不变

crs-usage admin                                   # 进 admin TUI
crs-usage admin setup [--profile NAME]            # 交互登录，写 profile
crs-usage admin print --view VIEW
                       [--profile NAME]
                       [--type TYPE]
                       [--json]                   # 非交互输出
crs-usage admin profiles list
crs-usage admin profiles use NAME
crs-usage admin profiles remove NAME
```

- `--view`：`dashboard` / `api-keys` / `accounts`
- `--type`：仅 `--view accounts` 用，取值 `claude` / `openai` / `gemini` / `droid`，默认 `claude`
- 未传子命令时回落到现有 `main()` 流程，所有原参数保留

实现：

- 顶层 `ArgumentParser` 保留现有全部 flag（`--provider` / `--key` / `--base-url` / `--period` 等），新增一个 `subparsers(dest='cmd')`，所有 admin 路径挂在 `admin` 这个 subparser 下
- 入口函数读 `args.cmd`：`None` → 调原 `run_codex_flow(args)`（即把现有 `main()` body 抽成函数）；`admin` → 进 admin dispatcher
- argparse 不天然支持「无 subcommand 沿用全局 flag」，所以现有 flag 必须挂在顶层 parser；admin subparser 不复用这些 flag

## 3. 配置与凭据

文件：`~/.config/crs-usage/config.json`（权限 600）

结构（命名对齐 sub2api-usage，方便用户记忆）：

```json
{
  "admin_default": "default",
  "admin_profiles": {
    "default": {
      "base_url": "https://cc.aihezu.dev",
      "username": "admin",
      "password": "***",
      "token": "***",
      "token_expires_at": 1764259200
    }
  }
}
```

- 不与 codex 配置混；codex 流照旧只读 `~/.codex/`
- `--profile NAME` > `admin_default` 指向的 profile > 报错并提示 `crs-usage admin setup`
- token 写回时机：首次 setup、401 重登后；`token_expires_at = login_time + expires_in - 60`
- 安全：密码明文存盘，文件权限 600，README 必须明确写出来

## 4. CRS 后端接口（已确认）

登录：

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/web/auth/login` | `{username, password}` | `{success, token, expiresIn, username}` |

数据接口（全部 `Authorization: Bearer <token>`）：

| Client 方法 | Method | Path | 用途 |
|---|---|---|---|
| `dashboard()` | GET | `/admin/dashboard` | 总览、RPM/TPM、账号状态计数 |
| `model_stats()` | GET | `/admin/model-stats` | 模型维度统计 |
| `api_keys()` | GET | `/admin/api-keys` | API Key 列表 |
| `claude_accounts()` | GET | `/admin/claude-accounts` | Claude 上游账号 |
| `openai_accounts()` | GET | `/admin/openai-accounts` | OpenAI 上游账号 |
| `gemini_accounts()` | GET | `/admin/gemini-accounts` | Gemini 上游账号 |
| `droid_accounts()` | GET | `/admin/droid-accounts` | Droid 上游账号 |
| `accounts_usage_stats()` | GET | `/admin/accounts/usage-stats` | 账号当日用量汇总，给 dashboard 用 |
| `usage_trend()` | GET | `/admin/usage-trend` | 日趋势数据，给 TUI Trend 视图用 |

字段细节落到实现期通过实际抓样本响应确定，spec 不预先冻结。

## 5. AdminClient

单文件里的 section，对外暴露上面方法。公共逻辑：

- `Authorization: Bearer <token>` 自动注入
- 401 自动 `login()` 一次重试，再失败抛错
- 复用现有 `_safe_call` / `_humanize_http_error` / `_post_json` 模式
- 并发：dashboard 视图一次需要 dashboard + model-stats + accounts_usage_stats 三个端点，用 ThreadPoolExecutor 并发拉

## 6. TUI 结构

Textual `App` 单类，`ContentSwitcher` 切换四个视图：

- **Dashboard**：上半屏 Static 文字摘要（RPM/TPM、今日请求/Token/费用、API Key 计数、账号状态计数），下半 DataTable 热门模型 top N
- **API Keys**：DataTable，列 = 名称 / 状态 / 今日请求 / 今日 Tokens / 今日费用 / 限额 / 到期
- **Accounts**：顶部 `Tabs` 切换 claude / openai / gemini / droid，主体 DataTable 各类型独立列集合（claude 含五小时窗口；openai 含组织 quota；其余按响应字段就近展示）
- **Trend**：DataTable + Textual `Sparkline` widget 画请求 / 费用 / Token 日趋势

按键：

| 键 | 动作 |
|---|---|
| `d` / `k` / `a` / `t` | 切到 Dashboard / Keys / Accounts / Trend |
| `1` / `2` / `3` / `4` | accounts 视图下切 claude/openai/gemini/droid |
| `r` | 手动刷新当前视图 |
| `q` | 退出 |

刷新策略：手动。进入视图时拉一次，按 `r` 重拉。

## 7. 输出格式（admin print）

文本输出沿用现有 `_format_count` / `_format_money` / `_pad` 等格式化函数，颜色由 rich 处理。

`--json` 输出原始 API 响应数据（去掉 token 等敏感字段），方便 `jq` 处理。多视图未实现 `--json` 数组形式——一次只查一个视图。

`admin print --view dashboard` 输出示意：

```text
■ default  https://cc.aihezu.dev  admin@example

  📊 实时
    RPM 1.2K    TPM 3.4M    今日请求 89K    今日费用 $123.45

  🔑 API Keys  活跃 23 / 总数 45
  🛠 上游账号  正常 12 / 异常 1 / 限流 0 / 过载 0

  🧠 今日热门模型 (Top 5)
    模型          请求  Tokens   输入/输出  缓存写/读     费用
    ...
```

`admin print --view api-keys` 输出 DataTable 风格的等宽表。

`admin print --view accounts --type claude` 输出 claude 上游账号表。

## 8. 文件结构

仍单文件 `crs_usage/__main__.py`，用 section 注释分块：

```python
# ===== 现有 codex provider 流（不动） =====
# ===== Admin: Config & Profile =====
# ===== Admin: Client =====
# ===== Admin: Formatters =====
# ===== Admin: Print Commands =====
# ===== Admin: TUI =====
# ===== CLI subparsers =====
```

`pyproject.toml` 改动：

```toml
dependencies = [
    "textual>=0.86",
    "rich>=13.0",
]
```

`README.md` 改动：

- 删「零依赖」表述
- 加 `crs-usage admin` 使用说明
- 标注密码明文存盘 + 文件 600 权限
- 给出 admin print / TUI 各自的输出示例

## 9. 错误处理

- 401 → 一次 `login()` 重试 → 仍失败：提示「token 过期且重新登录失败，请 crs-usage admin setup」
- 5xx / 网络错误 → 沿用现有 `_safe_call` 的提示，TUI 在视图区显示 `❌ 错误信息`
- profile 不存在 → 报错并提示 `crs-usage admin setup` 或 `admin profiles list`
- 配置文件解析失败 → 报错并提示具体行号

## 10. 测试与验证

参考 sub2api-usage，不写正式 unit test 目录。手动验证清单（README 里也列出来）：

1. `uvx --from . crs-usage` 现有行为依旧 OK
2. `uvx --from . crs-usage admin setup` 交互登录写 profile
3. `crs-usage admin print --view dashboard` 文本输出 OK
4. `crs-usage admin print --view dashboard --json` JSON 输出 OK
5. `crs-usage admin print --view api-keys` OK
6. `crs-usage admin print --view accounts --type claude` OK
7. `crs-usage admin` 进 TUI，四视图切换正常，`r` 刷新，`q` 退出
8. token 过期场景：手工删除 profile 里的 token 字段，下次调用自动重登

## 11. 向后兼容

- `crs-usage` 裸跑参数和行为完全不变；现有用户无感知
- `pyproject.toml` 版本从 0.2.1 跳到 0.3.0（引入新子命令树 + 新依赖）
- 第一次跑 admin 时如果未 setup，给清晰提示，不自动写空 profile
