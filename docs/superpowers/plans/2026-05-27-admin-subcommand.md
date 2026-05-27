# crs-usage admin 子命令 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 crs-usage 加上 `admin` 子命令树（TUI + 非交互 print），对接 claude-relay-service 的 `/admin/*` 接口；保持现有 `crs-usage` 裸跑行为不变。

**Architecture:** 单文件 `crs_usage/__main__.py` 内分 section 累加（现有 codex 流不动 → admin config → AdminClient → admin print → admin TUI → argparse subparsers）。Profile 配置存 `~/.config/crs-usage/config.json`（600 权限），token 跟随 profile 持久化，401 自动重登一次。TUI 用 Textual `ContentSwitcher` 切四视图，手动 `r` 刷新。

**Tech Stack:** Python 3.11+，stdlib（argparse / urllib / tomllib / json / concurrent.futures），新增依赖 `textual>=0.86` + `rich>=13.0`。

**测试策略：** 不引入 pytest 目录（沿用 sub2api-usage 的做法）。每个任务用 `python -c` 片段、CLI 自身的 `--help`/`--json` 输出、可选的真实 CRS 调用做验证。Spec §10 的 8 项手动验证清单作为收尾验收。

---

## File Structure

唯一文件 `crs_usage/__main__.py`，按 section 注释分块（追加在现有内容之后，**不重排现有代码**）：

```python
# ===== 现有 codex provider 流（不动） =====   # 已有，第 1–476 行
# ===== Admin: Config & Profile =====          # 新增
# ===== Admin: Client =====                    # 新增
# ===== Admin: Formatters & Print =====        # 新增
# ===== Admin: TUI =====                       # 新增
# ===== CLI subparsers & entry =====           # 改写底部入口
```

其他改动：

- `pyproject.toml`：依赖、版本号
- `README.md`：删「零依赖」、加 admin 段落、加密码明文 + 600 权限警告
- `docs/superpowers/specs/2026-05-27-admin-subcommand-design.md`：已存在

---

## Task 1: 加依赖，抽出 run_codex_flow

**Files:**
- Modify: `pyproject.toml`（version 0.2.1 → 0.3.0，dependencies）
- Modify: `crs_usage/__main__.py:478-608`（把现有 `main()` body 抽成 `run_codex_flow(args)`，`main` 暂时只调用它）

- [ ] **Step 1: 改 `pyproject.toml`**

把 `version = "0.2.1"` 改为 `version = "0.3.0"`；把 `dependencies = []` 改为：

```toml
dependencies = [
    "textual>=0.86",
    "rich>=13.0",
]
```

- [ ] **Step 2: 抽 `run_codex_flow`**

把现在的 `main()`（第 478 行起）改名为 `run_codex_flow(args: argparse.Namespace) -> int`，把第一段 `parser = argparse.ArgumentParser(...)` 到 `args = parser.parse_args(argv)`（即第 478–538 行）剪掉；保留从第 540 行起的处理逻辑作为函数体。

新写一个临时 `main` 在文件末尾：

```python
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="crs-usage",
        description=(
            "通过本地 Codex 配置查询 claude-relay-service 用量、限额与模型细分。"
            "读取 ~/.codex/config.toml，向 {base_origin}/apiStats/api/user-stats "
            "和 user-model-stats 发起请求。"
        ),
    )
    parser.add_argument("--provider", help="只查询指定 provider")
    parser.add_argument("--key", help="API key（跳过 codex 配置解析）")
    parser.add_argument("--base-url", help="覆盖 base URL，仅取 scheme+host")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG,
                        help=f"codex config.toml 路径（默认：{DEFAULT_CONFIG}）")
    parser.add_argument("--auth", type=Path, default=DEFAULT_AUTH,
                        help=f"codex auth.json 路径（默认：{DEFAULT_AUTH}）")
    parser.add_argument("--json", dest="as_json", action="store_true",
                        help="输出原始 JSON（按 provider 一项；多项时输出数组）")
    parser.add_argument("--timeout", type=float, default=15.0,
                        help="HTTP 超时（秒，默认 15）")
    parser.add_argument("--period", choices=("daily", "monthly", "alltime", "all"),
                        default="all",
                        help="模型细分时段：daily / monthly / alltime / all（默认 all）")
    parser.add_argument("--top", type=int, default=5,
                        help="文本输出每个时段展示前 N 个模型（默认 5；0 表示全部）")
    parser.add_argument("--no-models", dest="show_models", action="store_false",
                        help="关闭模型细分查询")
    parser.add_argument("--wide", action="store_true",
                        help="文本输出使用完整数字（默认按 K/M/B 紧凑显示）")
    args = parser.parse_args(argv)
    return run_codex_flow(args)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: 跑 `uv sync` 拉依赖**

```bash
uv sync
```

预期：textual 和 rich 被装进 `.venv`。

- [ ] **Step 4: 验证现有行为不破**

```bash
uv run python -m crs_usage --help
```

预期：输出和之前一致，所有原 flag 还在。

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml crs_usage/__main__.py
git commit -m "refactor: extract run_codex_flow; add textual/rich deps; bump 0.3.0"
```

---

## Task 2: argparse 子命令骨架

**Files:**
- Modify: `crs_usage/__main__.py`（替换 Task 1 临时 `main()`）

- [ ] **Step 1: 写 admin handler stubs**

在文件末尾、`main()` 之前加：

```python
# ===== CLI subparsers & entry =====

def cmd_admin_tui(args: argparse.Namespace) -> int:
    print("admin TUI not implemented yet", file=sys.stderr)
    return 2


def cmd_admin_setup(args: argparse.Namespace) -> int:
    print("admin setup not implemented yet", file=sys.stderr)
    return 2


def cmd_admin_print(args: argparse.Namespace) -> int:
    print(f"admin print --view {args.view} not implemented yet", file=sys.stderr)
    return 2


def cmd_admin_profiles(args: argparse.Namespace) -> int:
    print(f"admin profiles {args.profile_action} not implemented yet", file=sys.stderr)
    return 2
```

- [ ] **Step 2: 重写 `main()` 加 subparsers**

把临时 `main()` 替换为：

```python
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crs-usage",
        description=(
            "通过本地 Codex 配置查询 claude-relay-service 用量、限额与模型细分。"
            "裸跑读取 ~/.codex/config.toml；admin 子命令用账号密码登录查询 /admin/*。"
        ),
    )
    # 现有 flag（裸跑模式用）
    parser.add_argument("--provider", help="只查询指定 provider")
    parser.add_argument("--key", help="API key（跳过 codex 配置解析）")
    parser.add_argument("--base-url", help="覆盖 base URL，仅取 scheme+host")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG,
                        help=f"codex config.toml 路径（默认：{DEFAULT_CONFIG}）")
    parser.add_argument("--auth", type=Path, default=DEFAULT_AUTH,
                        help=f"codex auth.json 路径（默认：{DEFAULT_AUTH}）")
    parser.add_argument("--json", dest="as_json", action="store_true",
                        help="输出原始 JSON")
    parser.add_argument("--timeout", type=float, default=15.0,
                        help="HTTP 超时（秒，默认 15）")
    parser.add_argument("--period", choices=("daily", "monthly", "alltime", "all"),
                        default="all", help="模型细分时段")
    parser.add_argument("--top", type=int, default=5,
                        help="每个时段展示前 N 个模型（0 = 全部）")
    parser.add_argument("--no-models", dest="show_models", action="store_false",
                        help="关闭模型细分查询")
    parser.add_argument("--wide", action="store_true", help="文本输出完整数字")

    subparsers = parser.add_subparsers(dest="cmd")

    admin_p = subparsers.add_parser("admin", help="管理员视图（登录 CRS /admin/*）")
    admin_sub = admin_p.add_subparsers(dest="admin_cmd")
    admin_p.set_defaults(func=cmd_admin_tui)

    setup_p = admin_sub.add_parser("setup", help="交互式登录并写入 profile")
    setup_p.add_argument("--profile", default="default", help="profile 名（默认 default）")
    setup_p.set_defaults(func=cmd_admin_setup)

    print_p = admin_sub.add_parser("print", help="非交互输出")
    print_p.add_argument("--view", required=True,
                         choices=("dashboard", "api-keys", "accounts"))
    print_p.add_argument("--profile", help="profile 名（默认用 admin_default）")
    print_p.add_argument("--type", choices=("claude", "openai", "gemini", "droid"),
                         default="claude",
                         help="账号类型（仅 --view accounts 使用，默认 claude）")
    print_p.add_argument("--json", dest="as_json", action="store_true",
                         help="输出原始 JSON")
    print_p.set_defaults(func=cmd_admin_print)

    profiles_p = admin_sub.add_parser("profiles", help="管理 admin profile")
    profiles_sub = profiles_p.add_subparsers(dest="profile_action", required=True)
    list_p = profiles_sub.add_parser("list", help="列出所有 admin profile")
    list_p.set_defaults(func=cmd_admin_profiles)
    use_p = profiles_sub.add_parser("use", help="切换默认 admin profile")
    use_p.add_argument("name")
    use_p.set_defaults(func=cmd_admin_profiles)
    remove_p = profiles_sub.add_parser("remove", help="删除 admin profile")
    remove_p.add_argument("name")
    remove_p.set_defaults(func=cmd_admin_profiles)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.cmd is None:
        return run_codex_flow(args)
    return args.func(args)
```

- [ ] **Step 3: 验证 help 和默认行为**

```bash
uv run python -m crs_usage --help
uv run python -m crs_usage admin --help
uv run python -m crs_usage admin print --help
uv run python -m crs_usage admin profiles --help
```

预期：四条都能打印帮助，admin 子命令显示 setup/print/profiles 三个子项。

```bash
uv run python -m crs_usage --period daily --no-models --json 2>&1 | head -1 || true
```

预期：和之前行为一致（要么找到 codex 配置正常输出，要么报 `no model_providers found`，但**不是** argparse 错误）。

- [ ] **Step 4: Commit**

```bash
git add crs_usage/__main__.py
git commit -m "feat(admin): add argparse subparsers scaffold with stub handlers"
```

---

## Task 3: Config 文件读写 + Profile 解析

**Files:**
- Modify: `crs_usage/__main__.py`（追加 `# ===== Admin: Config & Profile =====` section）

- [ ] **Step 1: 写 config 模块代码**

在 `# ===== CLI subparsers & entry =====` 之前插入：

```python
# ===== Admin: Config & Profile =====

ADMIN_CONFIG_DIR = Path(
    os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
) / "crs-usage"
ADMIN_CONFIG_PATH = ADMIN_CONFIG_DIR / "config.json"


def load_admin_config() -> dict[str, Any]:
    """读取 admin config；不存在返回空 dict。"""
    if not ADMIN_CONFIG_PATH.exists():
        return {}
    with ADMIN_CONFIG_PATH.open("rb") as f:
        return json.load(f)


def save_admin_config(cfg: dict[str, Any]) -> None:
    """写回 admin config，文件权限 600。"""
    ADMIN_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = ADMIN_CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(ADMIN_CONFIG_PATH)


def resolve_admin_profile(
    cfg: dict[str, Any], name: str | None
) -> tuple[str, dict[str, Any]]:
    """返回 (profile_name, profile_dict)；找不到时抛 SystemExit。"""
    profiles = cfg.get("admin_profiles") or {}
    if not profiles:
        raise SystemExit(
            "error: 未配置任何 admin profile，先运行 `crs-usage admin setup`"
        )
    if name:
        if name not in profiles:
            raise SystemExit(
                f"error: profile {name!r} 不存在；"
                f"已有：{', '.join(profiles) or '(none)'}"
            )
        return name, profiles[name]
    default = cfg.get("admin_default")
    if default and default in profiles:
        return default, profiles[default]
    if len(profiles) == 1:
        only = next(iter(profiles))
        return only, profiles[only]
    raise SystemExit(
        f"error: 未指定 --profile 且无默认；"
        f"用 `crs-usage admin profiles use NAME` 设置默认，"
        f"已有：{', '.join(profiles)}"
    )


def update_admin_profile(
    name: str, patch: dict[str, Any]
) -> None:
    """合并 patch 到指定 profile 并写回。"""
    cfg = load_admin_config()
    profiles = cfg.setdefault("admin_profiles", {})
    profile = profiles.setdefault(name, {})
    profile.update(patch)
    save_admin_config(cfg)
```

- [ ] **Step 2: 验证 round-trip**

```bash
uv run python -c "
import os, tempfile, pathlib
tmp = tempfile.mkdtemp()
os.environ['XDG_CONFIG_HOME'] = tmp
import importlib, crs_usage.__main__ as m
importlib.reload(m)
m.save_admin_config({'admin_default': 'a',
                     'admin_profiles': {'a': {'base_url': 'x', 'username': 'u'}}})
cfg = m.load_admin_config()
print('cfg:', cfg)
name, prof = m.resolve_admin_profile(cfg, None)
print('resolved:', name, prof)
print('perm:', oct(pathlib.Path(m.ADMIN_CONFIG_PATH).stat().st_mode & 0o777))
"
```

预期：`cfg` 完整往返，`resolved: a {'base_url': 'x', 'username': 'u'}`，权限 `0o600`。

- [ ] **Step 3: 验证错误路径**

```bash
uv run python -c "
import os, tempfile
os.environ['XDG_CONFIG_HOME'] = tempfile.mkdtemp()
import importlib, crs_usage.__main__ as m
importlib.reload(m)
try:
    m.resolve_admin_profile({}, None)
except SystemExit as e:
    print('OK empty:', e)
try:
    m.resolve_admin_profile({'admin_profiles': {'a': {}}}, 'b')
except SystemExit as e:
    print('OK missing:', e)
"
```

预期：两次都抛 SystemExit，错误消息包含 `setup` / `不存在`。

- [ ] **Step 4: Commit**

```bash
git add crs_usage/__main__.py
git commit -m "feat(admin): config file load/save and profile resolution"
```

---

## Task 4: admin profiles list/use/remove

**Files:**
- Modify: `crs_usage/__main__.py`（替换 `cmd_admin_profiles` stub）

- [ ] **Step 1: 实现三个动作**

把 stub 函数替换为：

```python
def cmd_admin_profiles(args: argparse.Namespace) -> int:
    action = args.profile_action
    cfg = load_admin_config()
    profiles = cfg.get("admin_profiles") or {}
    default = cfg.get("admin_default")

    if action == "list":
        if not profiles:
            print("(no profiles; run `crs-usage admin setup`)")
            return 0
        for name, p in profiles.items():
            mark = " *" if name == default else "  "
            base = p.get("base_url", "-")
            user = p.get("username", "-")
            tok = "yes" if p.get("token") else "no"
            print(f"{mark} {name}  base={base}  user={user}  token={tok}")
        return 0

    if action == "use":
        if args.name not in profiles:
            print(f"error: profile {args.name!r} 不存在", file=sys.stderr)
            return 2
        cfg["admin_default"] = args.name
        save_admin_config(cfg)
        print(f"default admin profile set to {args.name!r}")
        return 0

    if action == "remove":
        if args.name not in profiles:
            print(f"error: profile {args.name!r} 不存在", file=sys.stderr)
            return 2
        del profiles[args.name]
        if cfg.get("admin_default") == args.name:
            cfg.pop("admin_default", None)
        save_admin_config(cfg)
        print(f"removed profile {args.name!r}")
        return 0

    print(f"unknown action: {action}", file=sys.stderr)
    return 2
```

- [ ] **Step 2: 验证 list/use/remove**

```bash
uv run python -c "
import os, tempfile, json
tmp = tempfile.mkdtemp()
os.environ['XDG_CONFIG_HOME'] = tmp
import importlib, crs_usage.__main__ as m
importlib.reload(m)
m.save_admin_config({
    'admin_profiles': {
        'work': {'base_url': 'https://a', 'username': 'u1', 'token': 't'},
        'home': {'base_url': 'https://b', 'username': 'u2'},
    }
})
" && \
XDG_CONFIG_HOME=$(python3 -c "import os; print(os.environ.get('XDG_CONFIG_HOME','/tmp'))") \
  uv run python -m crs_usage admin profiles list
```

由于 `XDG_CONFIG_HOME` 跨进程不能这么传，下一步用更直接的方式验证：

```bash
TMPDIR=$(mktemp -d)
XDG_CONFIG_HOME=$TMPDIR uv run python -c "
import crs_usage.__main__ as m
m.save_admin_config({'admin_profiles': {
    'work': {'base_url': 'https://a', 'username': 'u1', 'token': 't'},
    'home': {'base_url': 'https://b', 'username': 'u2'},
}})
"
XDG_CONFIG_HOME=$TMPDIR uv run python -m crs_usage admin profiles list
XDG_CONFIG_HOME=$TMPDIR uv run python -m crs_usage admin profiles use home
XDG_CONFIG_HOME=$TMPDIR uv run python -m crs_usage admin profiles list
XDG_CONFIG_HOME=$TMPDIR uv run python -m crs_usage admin profiles remove work
XDG_CONFIG_HOME=$TMPDIR uv run python -m crs_usage admin profiles list
```

预期：第一次 list 看到 work 和 home 都无 `*`；`use home` 后 home 前有 `*`；remove 后只剩 home。

- [ ] **Step 3: Commit**

```bash
git add crs_usage/__main__.py
git commit -m "feat(admin): profiles list/use/remove"
```

---

## Task 5: AdminClient（login + _get + 401 重试）

**Files:**
- Modify: `crs_usage/__main__.py`（追加 `# ===== Admin: Client =====` section）

- [ ] **Step 1: 写 AdminClient 类**

在 `# ===== CLI subparsers & entry =====` 之前（紧接 Config section 之后）插入：

```python
# ===== Admin: Client =====

import time
from typing import Callable

LOGIN_PATH = "/web/auth/login"


@dataclass
class AdminProfile:
    name: str
    base_url: str
    username: str
    password: str
    token: str | None = None
    token_expires_at: int | None = None


def _request_json(
    method: str,
    url: str,
    *,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float,
) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    hdrs = {"User-Agent": "crs-usage/0.3"}
    if data is not None:
        hdrs["Content-Type"] = "application/json"
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body_text = resp.read().decode("utf-8", errors="replace")
    return json.loads(body_text)


class AdminAuthError(Exception):
    """Login failed or token rejected after retry."""


class AdminClient:
    def __init__(
        self,
        profile: AdminProfile,
        *,
        timeout: float = 15.0,
        on_token_refresh: Callable[[str, int], None] | None = None,
    ):
        self.profile = profile
        self.timeout = timeout
        self.on_token_refresh = on_token_refresh
        self._origin = origin_of(profile.base_url)

    def login(self) -> None:
        url = f"{self._origin}{LOGIN_PATH}"
        try:
            payload = _request_json(
                "POST", url,
                body={"username": self.profile.username,
                      "password": self.profile.password},
                timeout=self.timeout,
            )
        except urllib.error.HTTPError as e:
            raise AdminAuthError(_humanize_http_error(e)) from e
        except urllib.error.URLError as e:
            raise AdminAuthError(f"connection error: {e.reason}") from e
        if not payload.get("success"):
            msg = payload.get("message") or payload.get("error") or "login failed"
            raise AdminAuthError(str(msg))
        token = payload.get("token")
        if not token:
            raise AdminAuthError("login response missing token")
        expires_in = int(payload.get("expiresIn") or 0)
        expires_at = int(time.time()) + max(expires_in - 60, 60) if expires_in else None
        self.profile.token = token
        self.profile.token_expires_at = expires_at
        if self.on_token_refresh:
            self.on_token_refresh(token, expires_at or 0)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.profile.token:
            self.login()
        url = f"{self._origin}{path}"
        if params:
            from urllib.parse import urlencode
            url = f"{url}?{urlencode(params)}"

        def _do() -> dict[str, Any]:
            return _request_json(
                "GET", url,
                headers={"Authorization": f"Bearer {self.profile.token}"},
                timeout=self.timeout,
            )

        try:
            return _do()
        except urllib.error.HTTPError as e:
            if e.code == 401:
                self.login()
                try:
                    return _do()
                except urllib.error.HTTPError as e2:
                    raise AdminAuthError(
                        f"401 after re-login: {_humanize_http_error(e2)}"
                    ) from e2
            raise
```

- [ ] **Step 2: 启动本地 stub server 验证 login + 401 重试**

```bash
uv run python -c "
import threading, http.server, json, time
from urllib.request import Request, urlopen

class Handler(http.server.BaseHTTPRequestHandler):
    state = {'login_count': 0, 'dash_count': 0}
    def do_POST(self):
        if self.path == '/web/auth/login':
            Handler.state['login_count'] += 1
            n = self.rfile.read(int(self.headers['Content-Length']))
            self.send_response(200); self.end_headers()
            self.wfile.write(json.dumps({'success': True,
                'token': f'tok{Handler.state[\"login_count\"]}',
                'expiresIn': 86400, 'username': 'admin'}).encode())
        else:
            self.send_response(404); self.end_headers()
    def do_GET(self):
        if self.path == '/admin/dashboard':
            Handler.state['dash_count'] += 1
            # 第一次模拟 401
            if Handler.state['dash_count'] == 1:
                self.send_response(401); self.end_headers()
                self.wfile.write(b'{\"error\":\"expired\"}')
                return
            self.send_response(200); self.end_headers()
            self.wfile.write(b'{\"success\": true, \"data\": {\"ok\": 1}}')
        else:
            self.send_response(404); self.end_headers()
    def log_message(self, *a, **kw): pass

srv = http.server.HTTPServer(('127.0.0.1', 0), Handler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

import crs_usage.__main__ as m
prof = m.AdminProfile(name='t', base_url=f'http://127.0.0.1:{port}',
                       username='admin', password='pw',
                       token='stale', token_expires_at=None)
saved = []
client = m.AdminClient(prof, on_token_refresh=lambda t,e: saved.append((t,e)))
resp = client._get('/admin/dashboard')
print('resp:', resp)
print('login_count:', Handler.state['login_count'])
print('dash_count:', Handler.state['dash_count'])
print('saved:', saved)
print('token now:', prof.token)
srv.shutdown()
"
```

预期：`resp` 是 `{'success': True, 'data': {'ok': 1}}`；`login_count: 1`（因为初始有 stale token，第一次直接走 GET 拿到 401 后重登）；`dash_count: 2`；`saved` 非空；`token now: tok1`。

- [ ] **Step 3: Commit**

```bash
git add crs_usage/__main__.py
git commit -m "feat(admin): AdminClient with login and 401 retry"
```

---

## Task 6: admin setup 交互式登录

**Files:**
- Modify: `crs_usage/__main__.py`（替换 `cmd_admin_setup` stub）

- [ ] **Step 1: 实现交互式 setup**

替换 stub：

```python
def cmd_admin_setup(args: argparse.Namespace) -> int:
    cfg = load_admin_config()
    profiles = cfg.get("admin_profiles") or {}
    name = args.profile
    existing = profiles.get(name) or {}

    default_base = existing.get("base_url") or "https://cc.aihezu.dev"
    default_user = existing.get("username") or ""

    base_url = input(f"CRS base URL [{default_base}]: ").strip() or default_base
    username = input(f"admin username [{default_user}]: ").strip() or default_user
    if not username:
        print("error: username 必填", file=sys.stderr)
        return 2
    import getpass
    password = getpass.getpass("admin password: ")
    if not password:
        print("error: password 必填", file=sys.stderr)
        return 2

    profile = AdminProfile(
        name=name, base_url=base_url,
        username=username, password=password,
    )
    client = AdminClient(profile)
    try:
        client.login()
    except AdminAuthError as e:
        print(f"error: 登录失败：{e}", file=sys.stderr)
        return 1

    entry = {
        "base_url": base_url,
        "username": username,
        "password": password,
        "token": profile.token,
        "token_expires_at": profile.token_expires_at,
    }
    update_admin_profile(name, entry)
    # 第一次 setup 时也把 default 指过来
    cfg = load_admin_config()
    if not cfg.get("admin_default"):
        cfg["admin_default"] = name
        save_admin_config(cfg)
    print(f"✅ profile {name!r} saved to {ADMIN_CONFIG_PATH}")
    print(f"   token expires at: {profile.token_expires_at or 'unknown'}")
    return 0
```

- [ ] **Step 2: 验证（需要真实 CRS）**

```bash
TMPDIR=$(mktemp -d)
XDG_CONFIG_HOME=$TMPDIR uv run python -m crs_usage admin setup
# 按提示输入 base/username/password
XDG_CONFIG_HOME=$TMPDIR uv run python -m crs_usage admin profiles list
cat $TMPDIR/crs-usage/config.json
ls -l $TMPDIR/crs-usage/config.json
```

预期：登录成功后 `profiles list` 显示该 profile 且 `token=yes`；文件权限 600；JSON 内含 `token` 和 `token_expires_at` 字段。

- [ ] **Step 3: Commit**

```bash
git add crs_usage/__main__.py
git commit -m "feat(admin): interactive setup writes profile and tests login"
```

---

## Task 7: AdminClient 数据端点

**Files:**
- Modify: `crs_usage/__main__.py`（在 `AdminClient` 类内追加方法）

- [ ] **Step 1: 加 endpoint 方法**

在 `AdminClient` 类末尾加：

```python
    def dashboard(self) -> dict[str, Any]:
        return self._get("/admin/dashboard")

    def model_stats(self, period: str = "daily") -> dict[str, Any]:
        return self._get("/admin/model-stats", {"period": period})

    def api_keys(self) -> dict[str, Any]:
        return self._get("/admin/api-keys")

    def accounts(self, account_type: str) -> dict[str, Any]:
        type_map = {
            "claude": "/admin/claude-accounts",
            "openai": "/admin/openai-accounts",
            "gemini": "/admin/gemini-accounts",
            "droid": "/admin/droid-accounts",
        }
        path = type_map.get(account_type)
        if not path:
            raise ValueError(f"unknown account type: {account_type}")
        return self._get(path)

    def accounts_usage_stats(self) -> dict[str, Any]:
        return self._get("/admin/accounts/usage-stats")

    def usage_trend(self, days: int = 7) -> dict[str, Any]:
        return self._get("/admin/usage-trend", {"days": str(days)})
```

并加一个辅助构造函数（在 class 内或外）：

```python
def build_admin_client(
    profile_name: str | None,
    timeout: float = 15.0,
) -> tuple[str, AdminClient]:
    """从 config 加载 profile 并构造 client；token 刷新时自动写回 config。"""
    cfg = load_admin_config()
    name, p = resolve_admin_profile(cfg, profile_name)
    profile = AdminProfile(
        name=name,
        base_url=p["base_url"],
        username=p["username"],
        password=p["password"],
        token=p.get("token"),
        token_expires_at=p.get("token_expires_at"),
    )

    def _persist(tok: str, exp: int) -> None:
        update_admin_profile(name, {"token": tok, "token_expires_at": exp})

    return name, AdminClient(profile, timeout=timeout, on_token_refresh=_persist)
```

- [ ] **Step 2: 验证端点拼接**

```bash
uv run python -c "
import crs_usage.__main__ as m
p = m.AdminProfile(name='x', base_url='https://example.com/path/',
                    username='u', password='p', token='t')
c = m.AdminClient(p)
print('origin:', c._origin)
# accounts 类型路由
import urllib.parse
type_map = {'claude':'/admin/claude-accounts','openai':'/admin/openai-accounts',
            'gemini':'/admin/gemini-accounts','droid':'/admin/droid-accounts'}
for t,path in type_map.items():
    print(t, '->', f'{c._origin}{path}')
try:
    c.accounts('bedrock')
except ValueError as e:
    print('reject bedrock:', e)
"
```

预期：origin 是 `https://example.com`（path 被剥掉），四个类型都生成正确 URL，bedrock 抛 ValueError。

- [ ] **Step 3: Commit**

```bash
git add crs_usage/__main__.py
git commit -m "feat(admin): AdminClient data endpoints + build_admin_client helper"
```

---

## Task 8: admin print --view dashboard

**Files:**
- Modify: `crs_usage/__main__.py`（追加 `# ===== Admin: Formatters & Print =====` section；替换 `cmd_admin_print` stub）

- [ ] **Step 1: 加 print_dashboard**

在 `# ===== Admin: Client =====` 之后（`# ===== CLI subparsers & entry =====` 之前）插入：

```python
# ===== Admin: Formatters & Print =====

def _safe(d: dict[str, Any] | None, *keys: str, default: Any = None) -> Any:
    cur: Any = d or {}
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def render_admin_dashboard(
    client_name: str,
    base_url: str,
    dash: dict[str, Any],
    models: dict[str, Any],
    accounts_stats: dict[str, Any] | None,
    top: int = 5,
) -> str:
    out: list[str] = []
    origin = origin_of(base_url)
    out.append(f"■ {client_name}  {origin}  admin")

    data = _safe(dash, "data") or dash or {}
    rpm = _safe(data, "realtimeRPM", default=0) or _safe(data, "rpm", default=0)
    tpm = _safe(data, "realtimeTPM", default=0) or _safe(data, "tpm", default=0)
    today_req = _safe(data, "todayRequests", default=0) or _safe(data, "today", "requests", default=0)
    today_tokens = _safe(data, "todayTokens", default=0) or _safe(data, "today", "tokens", default=0)
    today_cost = _safe(data, "todayCost", default=0) or _safe(data, "today", "cost", default=0)

    out.append("")
    out.append("  📊 实时")
    out.append(
        f"    RPM {_format_count(rpm)}    TPM {_format_count(tpm)}    "
        f"今日请求 {_format_count(today_req)}    今日费用 {_format_money(today_cost)}"
    )
    out.append(f"    今日 Tokens {_format_count(today_tokens)}")

    active_keys = _safe(data, "activeApiKeys", default=None)
    total_keys = _safe(data, "totalApiKeys", default=None)
    if active_keys is not None or total_keys is not None:
        out.append("")
        out.append(
            f"  🔑 API Keys  活跃 {_format_count(active_keys)} / "
            f"总数 {_format_count(total_keys)}"
        )

    acc_data = _safe(accounts_stats, "data") if accounts_stats else None
    if isinstance(acc_data, dict):
        normal = acc_data.get("normal", 0)
        abnormal = acc_data.get("abnormal", 0)
        rate_limited = acc_data.get("rateLimited", 0)
        overloaded = acc_data.get("overloaded", 0)
        out.append(
            f"  🛠 上游账号  正常 {normal} / 异常 {abnormal} / "
            f"限流 {rate_limited} / 过载 {overloaded}"
        )

    model_data = _safe(models, "data", default=[]) or []
    if isinstance(model_data, list) and model_data:
        out.append("")
        out.append(f"  🧠 今日热门模型 (Top {top})")
        out.extend(_render_model_table(model_data, top, compact=True))

    return "\n".join(out)
```

- [ ] **Step 2: 替换 cmd_admin_print 走 dashboard 分支**

```python
def cmd_admin_print(args: argparse.Namespace) -> int:
    try:
        name, client = build_admin_client(args.profile)
    except SystemExit:
        raise
    except (KeyError, AdminAuthError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    view = args.view
    try:
        if view == "dashboard":
            with ThreadPoolExecutor(max_workers=3) as ex:
                f_dash = ex.submit(_safe_call, client.dashboard)
                f_models = ex.submit(_safe_call, client.model_stats, "daily")
                f_accs = ex.submit(_safe_call, client.accounts_usage_stats)
                ok_d, dash = f_dash.result()
                ok_m, models = f_models.result()
                ok_a, accs = f_accs.result()
            if not ok_d:
                print(f"error: dashboard 失败：{dash}", file=sys.stderr)
                return 1
            models_payload = models if ok_m else {"data": []}
            accs_payload = accs if ok_a else None
            if args.as_json:
                print(json.dumps({
                    "profile": name,
                    "base_url": client.profile.base_url,
                    "dashboard": dash,
                    "model_stats": models_payload,
                    "accounts_usage_stats": accs_payload,
                }, ensure_ascii=False, indent=2))
            else:
                print(render_admin_dashboard(
                    name, client.profile.base_url, dash, models_payload,
                    accs_payload, top=5,
                ))
            return 0
        # 其他 view 后续 Task 实现
        print(f"view {view!r} not implemented yet", file=sys.stderr)
        return 2
    except AdminAuthError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
```

- [ ] **Step 3: 验证（需要真实 CRS profile）**

```bash
XDG_CONFIG_HOME=$TMPDIR uv run python -m crs_usage admin print --view dashboard
XDG_CONFIG_HOME=$TMPDIR uv run python -m crs_usage admin print --view dashboard --json | head -40
```

预期：文本输出含 `■ default ... admin` + 📊/🔑/🛠/🧠 几段；JSON 输出含 `profile / dashboard / model_stats / accounts_usage_stats` 字段。

- [ ] **Step 4: Commit**

```bash
git add crs_usage/__main__.py
git commit -m "feat(admin): print --view dashboard (text + json)"
```

---

## Task 9: admin print --view api-keys

**Files:**
- Modify: `crs_usage/__main__.py`（在 Formatters section 加 `render_api_keys`；扩展 `cmd_admin_print`）

- [ ] **Step 1: 写表格渲染**

在 Formatters section 加：

```python
def render_api_keys_table(payload: dict[str, Any]) -> str:
    keys = _safe(payload, "data") or payload.get("apiKeys") or []
    if not isinstance(keys, list) or not keys:
        return "(无 API Key)"

    rows: list[tuple[str, str, str, str, str, str, str]] = [
        ("名称", "状态", "今日请求", "今日 Tokens", "今日费用", "限额(日)", "到期"),
    ]
    for k in keys:
        name = str(k.get("name") or k.get("id") or "?")
        active = "启用" if k.get("isActive") else "禁用"
        today = k.get("todayUsage") or k.get("usage") or {}
        req = _format_count(today.get("requests"))
        tokens = _format_count(today.get("allTokens") or today.get("tokens"))
        cost = _format_money_short(today.get("cost"))
        daily_lim = k.get("dailyCostLimit") or 0
        limit_s = _format_money_short(daily_lim) if daily_lim else "∞"
        expires = k.get("expiresAt") or "永不"
        rows.append((name, active, req, tokens, cost, limit_s, expires))

    widths = [0] * 7
    for row in rows:
        for i, c in enumerate(row):
            widths[i] = max(widths[i], _display_width(c))

    aligns = ("left", "left", "right", "right", "right", "right", "left")
    lines: list[str] = []
    for idx, row in enumerate(rows):
        cells = [_pad(c, widths[i], aligns[i]) for i, c in enumerate(row)]
        lines.append("  ".join(cells))
        if idx == 0:
            lines.append("  ".join("─" * widths[i] for i in range(7)))
    return "\n".join(lines)
```

- [ ] **Step 2: 在 cmd_admin_print 加 api-keys 分支**

把 `# 其他 view 后续 Task 实现` 那段替换为：

```python
        if view == "api-keys":
            ok, payload = _safe_call(client.api_keys)
            if not ok:
                print(f"error: api-keys 失败：{payload}", file=sys.stderr)
                return 1
            if args.as_json:
                print(json.dumps({
                    "profile": name,
                    "base_url": client.profile.base_url,
                    "api_keys": payload,
                }, ensure_ascii=False, indent=2))
            else:
                print(f"■ {name}  {origin_of(client.profile.base_url)}  admin / api-keys")
                print()
                print(render_api_keys_table(payload))
            return 0
        # 其他 view 后续 Task 实现
        print(f"view {view!r} not implemented yet", file=sys.stderr)
        return 2
```

- [ ] **Step 3: 验证**

```bash
XDG_CONFIG_HOME=$TMPDIR uv run python -m crs_usage admin print --view api-keys
XDG_CONFIG_HOME=$TMPDIR uv run python -m crs_usage admin print --view api-keys --json | head -40
```

预期：文本输出表格对齐；JSON 输出 `profile/base_url/api_keys` 三字段。

- [ ] **Step 4: Commit**

```bash
git add crs_usage/__main__.py
git commit -m "feat(admin): print --view api-keys"
```

---

## Task 10: admin print --view accounts --type

**Files:**
- Modify: `crs_usage/__main__.py`（加 `render_accounts_table`；扩展 `cmd_admin_print`）

- [ ] **Step 1: 写账号表格渲染**

在 Formatters section 加：

```python
def render_accounts_table(account_type: str, payload: dict[str, Any]) -> str:
    accs = _safe(payload, "data") or payload.get("accounts") or []
    if not isinstance(accs, list) or not accs:
        return f"(无 {account_type} 账号)"

    # 通用列；不同类型补充字段不一致时取 None
    rows: list[tuple[str, str, str, str, str, str]] = [
        ("名称", "状态", "今日请求", "今日 Tokens", "今日费用", "5h 窗口/限额"),
    ]
    for a in accs:
        name = str(a.get("name") or a.get("email") or a.get("id") or "?")
        status = str(a.get("status") or "-")
        today = a.get("todayUsage") or a.get("usage") or {}
        req = _format_count(today.get("requests"))
        tokens = _format_count(today.get("allTokens") or today.get("tokens"))
        cost = _format_money_short(today.get("cost"))
        win_cost = a.get("currentWindowCost")
        win_lim = a.get("windowCostLimit") or a.get("rateLimitCost")
        if win_cost is not None or win_lim:
            cost_s = _format_money_short(win_cost) if win_cost is not None else "-"
            lim_s = _format_money_short(win_lim) if win_lim else "∞"
            win_cell = f"{cost_s} / {lim_s}"
        else:
            win_cell = "-"
        rows.append((name, status, req, tokens, cost, win_cell))

    widths = [0] * 6
    for row in rows:
        for i, c in enumerate(row):
            widths[i] = max(widths[i], _display_width(c))
    aligns = ("left", "left", "right", "right", "right", "right")
    lines: list[str] = []
    for idx, row in enumerate(rows):
        cells = [_pad(c, widths[i], aligns[i]) for i, c in enumerate(row)]
        lines.append("  ".join(cells))
        if idx == 0:
            lines.append("  ".join("─" * widths[i] for i in range(6)))
    return "\n".join(lines)
```

- [ ] **Step 2: 加 accounts 分支**

替换 `# 其他 view 后续 Task 实现` 整段为：

```python
        if view == "accounts":
            ok, payload = _safe_call(client.accounts, args.type)
            if not ok:
                print(f"error: accounts({args.type}) 失败：{payload}", file=sys.stderr)
                return 1
            if args.as_json:
                print(json.dumps({
                    "profile": name,
                    "base_url": client.profile.base_url,
                    "account_type": args.type,
                    "accounts": payload,
                }, ensure_ascii=False, indent=2))
            else:
                print(f"■ {name}  {origin_of(client.profile.base_url)}  "
                      f"admin / accounts / {args.type}")
                print()
                print(render_accounts_table(args.type, payload))
            return 0
        print(f"view {view!r} not implemented yet", file=sys.stderr)
        return 2
```

- [ ] **Step 3: 验证四种类型**

```bash
for t in claude openai gemini droid; do
  echo "=== $t ==="
  XDG_CONFIG_HOME=$TMPDIR uv run python -m crs_usage admin print --view accounts --type $t
done
XDG_CONFIG_HOME=$TMPDIR uv run python -m crs_usage admin print --view accounts --type claude --json | head -20
```

预期：四类型都能输出（无账号时显示 `(无 xxx 账号)`），JSON 模式含 `account_type` 字段。

- [ ] **Step 4: Commit**

```bash
git add crs_usage/__main__.py
git commit -m "feat(admin): print --view accounts --type"
```

---

## Task 11: TUI 骨架（App + ContentSwitcher + 视图占位）

**Files:**
- Modify: `crs_usage/__main__.py`（追加 `# ===== Admin: TUI =====` section；替换 `cmd_admin_tui` stub）

- [ ] **Step 1: 写 TUI App 骨架**

在 Formatters section 之后插入：

```python
# ===== Admin: TUI =====

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.widgets import Header, Footer, Static, DataTable, ContentSwitcher, Tabs, Tab


class AdminTUI(App):
    CSS = """
    Screen { background: $surface; }
    #status { dock: top; height: 1; background: $panel; padding: 0 1; }
    #view { padding: 1 2; }
    DataTable { height: 1fr; }
    """

    BINDINGS = [
        Binding("d", "set_view('dashboard')", "Dashboard"),
        Binding("k", "set_view('api-keys')", "Keys"),
        Binding("a", "set_view('accounts')", "Accounts"),
        Binding("t", "set_view('trend')", "Trend"),
        Binding("r", "refresh_view", "刷新"),
        Binding("q", "quit", "退出"),
    ]

    def __init__(self, profile_name: str, client: "AdminClient") -> None:
        super().__init__()
        self.profile_name = profile_name
        self.client = client
        self.current_view = "dashboard"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(
            f"profile: {self.profile_name}  base: {self.client.profile.base_url}",
            id="status",
        )
        with ContentSwitcher(initial="dashboard", id="view"):
            yield Static("loading dashboard...", id="dashboard")
            yield Static("loading api-keys...", id="api-keys")
            yield Static("loading accounts...", id="accounts")
            yield Static("loading trend...", id="trend")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_current()

    def action_set_view(self, view: str) -> None:
        self.current_view = view
        self.query_one(ContentSwitcher).current = view
        self.refresh_current()

    def action_refresh_view(self) -> None:
        self.refresh_current()

    def refresh_current(self) -> None:
        # 真实实现见后续 task
        pass


def cmd_admin_tui(args: argparse.Namespace) -> int:
    profile_name = getattr(args, "profile", None)
    try:
        name, client = build_admin_client(profile_name)
    except SystemExit:
        raise
    except (KeyError, AdminAuthError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    AdminTUI(name, client).run()
    return 0
```

并把 admin TUI 子命令加 `--profile`：在 `_build_parser` 里的 `admin_p` 后面（`admin_p.set_defaults(func=cmd_admin_tui)` 之前）加：

```python
    admin_p.add_argument("--profile", help="profile 名（默认用 admin_default）")
```

- [ ] **Step 2: 验证 TUI 启动**

```bash
XDG_CONFIG_HOME=$TMPDIR uv run python -m crs_usage admin
```

预期：进入 textual TUI，顶部显示 profile 和 base，按 `d/k/a/t` 切换看到对应 `loading xxx...`，`q` 退出干净。

- [ ] **Step 3: Commit**

```bash
git add crs_usage/__main__.py
git commit -m "feat(admin): TUI scaffold with ContentSwitcher and bindings"
```

---

## Task 12: TUI Dashboard 视图

**Files:**
- Modify: `crs_usage/__main__.py`（`AdminTUI` 内填充 dashboard 刷新；`compose` 改 dashboard 容器）

- [ ] **Step 1: 把 dashboard widget 换成可填的容器**

把 `compose()` 里这行：

```python
            yield Static("loading dashboard...", id="dashboard")
```

替换为：

```python
            with Vertical(id="dashboard"):
                yield Static("loading...", id="dash-summary")
                yield DataTable(id="dash-models")
```

- [ ] **Step 2: 加 `_refresh_dashboard` 方法**

在 `AdminTUI` 类内加：

```python
    def _refresh_dashboard(self) -> None:
        summary = self.query_one("#dash-summary", Static)
        table = self.query_one("#dash-models", DataTable)
        summary.update("loading...")
        try:
            with ThreadPoolExecutor(max_workers=3) as ex:
                f_dash = ex.submit(_safe_call, self.client.dashboard)
                f_models = ex.submit(_safe_call, self.client.model_stats, "daily")
                f_accs = ex.submit(_safe_call, self.client.accounts_usage_stats)
                ok_d, dash = f_dash.result()
                ok_m, models = f_models.result()
                ok_a, accs = f_accs.result()
        except Exception as e:
            summary.update(f"❌ {e}")
            return
        if not ok_d:
            summary.update(f"❌ dashboard 失败：{dash}")
            return
        models_payload = models if ok_m else {"data": []}
        accs_payload = accs if ok_a else None

        # 复用 print 用的渲染函数，去掉首行 ■ 标头（已在顶部 status 显示）
        # 以及 🧠 模型表（下方 DataTable 单独画）
        text = render_admin_dashboard(
            self.profile_name, self.client.profile.base_url,
            dash, models_payload, accs_payload, top=5,
        )
        body = "\n".join(text.splitlines()[1:]).rstrip()
        idx = body.find("🧠")
        if idx != -1:
            body = body[:idx].rstrip()
        summary.update(body)

        table.clear(columns=True)
        table.add_columns("模型", "请求", "Tokens", "输入/输出", "缓存写/读", "费用")
        model_data = _safe(models_payload, "data", default=[]) or []
        for m in model_data[:10]:
            table.add_row(
                str(m.get("model", "?")),
                _format_count(m.get("requests")),
                _format_count(m.get("allTokens")),
                f"{_format_count(m.get('inputTokens'))}/{_format_count(m.get('outputTokens'))}",
                f"{_format_count(m.get('cacheCreateTokens'))}/{_format_count(m.get('cacheReadTokens'))}",
                _format_money_short(_safe(m, "costs", "total")),
            )
```

修改 `refresh_current` 让它分派：

```python
    def refresh_current(self) -> None:
        v = self.current_view
        if v == "dashboard":
            self._refresh_dashboard()
```

- [ ] **Step 3: 验证**

```bash
XDG_CONFIG_HOME=$TMPDIR uv run python -m crs_usage admin
```

预期：进入后 dashboard 自动加载，能看到 📊 实时 / 🔑 / 🛠 段 + 下方 DataTable 模型列表；按 `r` 重新拉数据；其他视图仍是 placeholder。

- [ ] **Step 4: Commit**

```bash
git add crs_usage/__main__.py
git commit -m "feat(admin): TUI dashboard view (summary + model table)"
```

---

## Task 13: TUI API Keys 视图

**Files:**
- Modify: `crs_usage/__main__.py`

- [ ] **Step 1: 把 api-keys placeholder 换成 DataTable**

`compose()` 里把：

```python
            yield Static("loading api-keys...", id="api-keys")
```

替换为：

```python
            with Vertical(id="api-keys"):
                yield Static("loading...", id="keys-status")
                yield DataTable(id="keys-table")
```

- [ ] **Step 2: 加 `_refresh_api_keys`**

```python
    def _refresh_api_keys(self) -> None:
        status = self.query_one("#keys-status", Static)
        table = self.query_one("#keys-table", DataTable)
        status.update("loading...")
        ok, payload = _safe_call(self.client.api_keys)
        if not ok:
            status.update(f"❌ {payload}")
            return
        keys = _safe(payload, "data") or payload.get("apiKeys") or []
        status.update(f"共 {len(keys)} 个 API Key")
        table.clear(columns=True)
        table.add_columns(
            "名称", "状态", "今日请求", "今日 Tokens", "今日费用", "限额(日)", "到期",
        )
        for k in keys:
            today = k.get("todayUsage") or k.get("usage") or {}
            daily_lim = k.get("dailyCostLimit") or 0
            table.add_row(
                str(k.get("name") or k.get("id") or "?"),
                "启用" if k.get("isActive") else "禁用",
                _format_count(today.get("requests")),
                _format_count(today.get("allTokens") or today.get("tokens")),
                _format_money_short(today.get("cost")),
                _format_money_short(daily_lim) if daily_lim else "∞",
                str(k.get("expiresAt") or "永不"),
            )
```

把 `refresh_current` 改为：

```python
    def refresh_current(self) -> None:
        v = self.current_view
        if v == "dashboard":
            self._refresh_dashboard()
        elif v == "api-keys":
            self._refresh_api_keys()
```

- [ ] **Step 3: 验证**

```bash
XDG_CONFIG_HOME=$TMPDIR uv run python -m crs_usage admin
# 按 k 切到 API Keys，看到表格
```

预期：表格列对齐，能看到所有 key。

- [ ] **Step 4: Commit**

```bash
git add crs_usage/__main__.py
git commit -m "feat(admin): TUI api-keys view"
```

---

## Task 14: TUI Accounts 视图（带 Tabs 切类型）

**Files:**
- Modify: `crs_usage/__main__.py`

- [ ] **Step 1: 替换 accounts placeholder**

`compose()` 里把：

```python
            yield Static("loading accounts...", id="accounts")
```

替换为：

```python
            with Vertical(id="accounts"):
                yield Tabs(
                    Tab("Claude", id="tab-claude"),
                    Tab("OpenAI", id="tab-openai"),
                    Tab("Gemini", id="tab-gemini"),
                    Tab("Droid", id="tab-droid"),
                    id="acc-tabs",
                )
                yield Static("loading...", id="acc-status")
                yield DataTable(id="acc-table")
```

- [ ] **Step 2: 加状态字段和监听**

在 `__init__` 里加：

```python
        self.current_account_type = "claude"
```

在 `AdminTUI` 类内加：

```python
    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        if event.tab is None:
            return
        mapping = {"tab-claude": "claude", "tab-openai": "openai",
                   "tab-gemini": "gemini", "tab-droid": "droid"}
        new_type = mapping.get(event.tab.id or "")
        if new_type and new_type != self.current_account_type:
            self.current_account_type = new_type
            if self.current_view == "accounts":
                self._refresh_accounts()

    def _refresh_accounts(self) -> None:
        status = self.query_one("#acc-status", Static)
        table = self.query_one("#acc-table", DataTable)
        status.update(f"loading {self.current_account_type}...")
        ok, payload = _safe_call(self.client.accounts, self.current_account_type)
        if not ok:
            status.update(f"❌ {payload}")
            return
        accs = _safe(payload, "data") or payload.get("accounts") or []
        status.update(f"{self.current_account_type}: 共 {len(accs)} 个账号")
        table.clear(columns=True)
        table.add_columns(
            "名称", "状态", "今日请求", "今日 Tokens", "今日费用", "5h 窗口/限额",
        )
        for a in accs:
            today = a.get("todayUsage") or a.get("usage") or {}
            win_cost = a.get("currentWindowCost")
            win_lim = a.get("windowCostLimit") or a.get("rateLimitCost")
            if win_cost is not None or win_lim:
                cost_s = _format_money_short(win_cost) if win_cost is not None else "-"
                lim_s = _format_money_short(win_lim) if win_lim else "∞"
                win_cell = f"{cost_s} / {lim_s}"
            else:
                win_cell = "-"
            table.add_row(
                str(a.get("name") or a.get("email") or a.get("id") or "?"),
                str(a.get("status") or "-"),
                _format_count(today.get("requests")),
                _format_count(today.get("allTokens") or today.get("tokens")),
                _format_money_short(today.get("cost")),
                win_cell,
            )
```

把 `refresh_current` 扩展：

```python
    def refresh_current(self) -> None:
        v = self.current_view
        if v == "dashboard":
            self._refresh_dashboard()
        elif v == "api-keys":
            self._refresh_api_keys()
        elif v == "accounts":
            self._refresh_accounts()
```

- [ ] **Step 3: 验证 Tab 切换**

```bash
XDG_CONFIG_HOME=$TMPDIR uv run python -m crs_usage admin
# 按 a 切到 Accounts；点击或方向键切换 Claude/OpenAI/Gemini/Droid Tabs
```

预期：每次切 Tab 自动刷新表格；状态行显示 `<type>: 共 N 个账号`。

- [ ] **Step 4: Commit**

```bash
git add crs_usage/__main__.py
git commit -m "feat(admin): TUI accounts view with Tabs for type switching"
```

---

## Task 15: TUI Trend 视图

**Files:**
- Modify: `crs_usage/__main__.py`

- [ ] **Step 1: 导入 Sparkline**

在 textual 导入处补：

```python
from textual.widgets import Header, Footer, Static, DataTable, ContentSwitcher, Tabs, Tab, Sparkline
```

- [ ] **Step 2: 替换 trend placeholder**

`compose()` 里把：

```python
            yield Static("loading trend...", id="trend")
```

替换为：

```python
            with Vertical(id="trend"):
                yield Static("loading...", id="trend-status")
                yield Static("请求", id="trend-req-label")
                yield Sparkline([], id="trend-req")
                yield Static("Tokens", id="trend-tok-label")
                yield Sparkline([], id="trend-tok")
                yield Static("费用", id="trend-cost-label")
                yield Sparkline([], id="trend-cost")
                yield DataTable(id="trend-table")
```

- [ ] **Step 3: 加 `_refresh_trend`**

```python
    def _refresh_trend(self) -> None:
        status = self.query_one("#trend-status", Static)
        status.update("loading...")
        ok, payload = _safe_call(self.client.usage_trend, 7)
        if not ok:
            status.update(f"❌ {payload}")
            return
        rows = _safe(payload, "data") or payload.get("trend") or []
        if not isinstance(rows, list):
            rows = []
        status.update(f"过去 {len(rows)} 天")

        reqs = [float(r.get("requests") or 0) for r in rows]
        toks = [float(r.get("tokens") or r.get("allTokens") or 0) for r in rows]
        costs = [float(r.get("cost") or 0) for r in rows]
        self.query_one("#trend-req", Sparkline).data = reqs
        self.query_one("#trend-tok", Sparkline).data = toks
        self.query_one("#trend-cost", Sparkline).data = costs

        table = self.query_one("#trend-table", DataTable)
        table.clear(columns=True)
        table.add_columns("日期", "请求", "Tokens", "费用")
        for r in rows:
            table.add_row(
                str(r.get("date") or r.get("day") or "?"),
                _format_count(r.get("requests")),
                _format_count(r.get("tokens") or r.get("allTokens")),
                _format_money_short(r.get("cost")),
            )
```

把 `refresh_current` 扩展：

```python
        elif v == "trend":
            self._refresh_trend()
```

- [ ] **Step 4: 验证**

```bash
XDG_CONFIG_HOME=$TMPDIR uv run python -m crs_usage admin
# 按 t 切到 Trend
```

预期：三条 Sparkline 显示请求 / Tokens / 费用 7 天走势，下方表格列出每天数值。

- [ ] **Step 5: Commit**

```bash
git add crs_usage/__main__.py
git commit -m "feat(admin): TUI trend view with sparklines"
```

---

## Task 16: README 更新 + 收尾验收

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 更新 README**

把第一段「零依赖，单文件实现。」改为「单文件实现，admin 模式依赖 textual / rich。」

在「用法」后、「Key 解析优先级」前插入新段落：

````markdown
## Admin 模式

`crs-usage admin` 系列子命令对接 CRS 的 `/admin/*` 接口，需要用 admin 用户名 / 密码登录。

```bash
crs-usage admin setup                       # 交互式填 base_url / username / password
crs-usage admin                             # 进 TUI（d/k/a/t 切视图，r 刷新，q 退出）
crs-usage admin print --view dashboard
crs-usage admin print --view api-keys --json
crs-usage admin print --view accounts --type claude
crs-usage admin profiles list
crs-usage admin profiles use NAME
crs-usage admin profiles remove NAME
```

凭据存在 `~/.config/crs-usage/config.json`（自动设为 600 权限）。

**安全提示：密码以明文形式保存，依赖文件系统权限保护，请勿在共享主机上使用。**

支持多 profile：`crs-usage admin setup --profile work` 写到 `work` profile，`admin profiles use work` 切换默认。

token 自动持久化；过期时自动重新登录一次。
````

把「要求」段改为：

```markdown
## 要求

- Python ≥ 3.11
- 裸跑模式：一个本地 `~/.codex/config.toml` 配置（或通过 `--key` `--base-url` 直接指定）
- admin 模式：通过 `crs-usage admin setup` 初始化 profile
```

- [ ] **Step 2: 跑完 Spec §10 的 8 项手动验收**

```bash
# 1. 现有行为
uv run python -m crs_usage --help
uv run python -m crs_usage   # 应仍走 codex 流

# 2. admin setup
uv run python -m crs_usage admin setup

# 3. admin print dashboard
uv run python -m crs_usage admin print --view dashboard

# 4. dashboard --json
uv run python -m crs_usage admin print --view dashboard --json | jq .profile

# 5. api-keys
uv run python -m crs_usage admin print --view api-keys

# 6. accounts claude
uv run python -m crs_usage admin print --view accounts --type claude

# 7. TUI 四视图 + r/q
uv run python -m crs_usage admin

# 8. token 过期重登
python3 -c "
import json, pathlib, os
p = pathlib.Path(os.environ.get('XDG_CONFIG_HOME', str(pathlib.Path.home()/'.config'))) / 'crs-usage/config.json'
d = json.loads(p.read_text())
for prof in d.get('admin_profiles', {}).values():
    prof.pop('token', None)
    prof.pop('token_expires_at', None)
p.write_text(json.dumps(d, indent=2, ensure_ascii=False))
"
uv run python -m crs_usage admin print --view dashboard
# 应自动重登成功，输出正常 dashboard
```

每一项 OK 才算完。

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README for admin subcommand"
```

- [ ] **Step 4: 检查 git log**

```bash
git log --oneline -20
```

预期：16 个 commit 整齐排列，主线清晰。
