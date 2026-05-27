from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_CONFIG = Path.home() / ".codex" / "config.toml"
DEFAULT_AUTH = Path.home() / ".codex" / "auth.json"
USER_STATS_PATH = "/apiStats/api/user-stats"
USER_MODEL_STATS_PATH = "/apiStats/api/user-model-stats"

PERIOD_LABELS = {
    "daily": "今日",
    "monthly": "本月",
    "alltime": "累计",
}
PERIOD_ORDER = ("daily", "monthly", "alltime")


@dataclass
class ProviderTarget:
    name: str
    base_url: str
    env_key: str | None
    key: str | None
    key_source: str | None


@dataclass
class FetchResult:
    stats: dict[str, Any] | None = None
    model_stats: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


def origin_of(base_url: str) -> str:
    u = urlparse(base_url)
    if not u.scheme or not u.netloc:
        raise ValueError(f"invalid base_url: {base_url!r}")
    return f"{u.scheme}://{u.netloc}"


def load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as f:
        return tomllib.load(f)


def load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def resolve_key(
    provider_cfg: dict[str, Any],
    cli_key: str | None,
    env_dict: dict[str, str],
    auth_data: dict[str, Any],
) -> tuple[str | None, str | None]:
    if cli_key:
        return cli_key, "--key"
    env_name = provider_cfg.get("env_key")
    if env_name:
        v = env_dict.get(env_name)
        if v:
            return v, f"env:{env_name}"
    v = auth_data.get("OPENAI_API_KEY")
    if v:
        return v, "auth.json"
    return None, None


def build_targets(
    cfg: dict[str, Any],
    auth_data: dict[str, Any],
    provider_filter: str | None,
    cli_key: str | None,
    cli_base_url: str | None,
) -> list[ProviderTarget]:
    if cli_key and cli_base_url:
        return [
            ProviderTarget(
                name=provider_filter or "(manual)",
                base_url=cli_base_url,
                env_key=None,
                key=cli_key,
                key_source="--key",
            )
        ]

    providers = cfg.get("model_providers", {}) or {}
    if not providers:
        return []

    if provider_filter:
        if provider_filter not in providers:
            raise SystemExit(
                f"provider {provider_filter!r} not found in config; "
                f"available: {', '.join(providers) or '(none)'}"
            )
        names = [provider_filter]
    else:
        names = list(providers)

    env_dict = dict(os.environ)
    targets: list[ProviderTarget] = []
    for name in names:
        p = providers[name] or {}
        base_url = cli_base_url or p.get("base_url")
        if not base_url:
            targets.append(
                ProviderTarget(name=name, base_url="", env_key=p.get("env_key"), key=None, key_source=None)
            )
            continue
        key, src = resolve_key(p, cli_key, env_dict, auth_data)
        targets.append(
            ProviderTarget(
                name=name,
                base_url=base_url,
                env_key=p.get("env_key"),
                key=key,
                key_source=src,
            )
        )
    return targets


def _post_json(url: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "crs-usage/0.2"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body_text = resp.read().decode("utf-8", errors="replace")
    return json.loads(body_text)


def call_user_stats(origin: str, api_key: str, timeout: float) -> dict[str, Any]:
    return _post_json(f"{origin}{USER_STATS_PATH}", {"apiKey": api_key}, timeout)


def call_user_model_stats(
    origin: str, api_key: str, period: str, timeout: float
) -> dict[str, Any]:
    return _post_json(
        f"{origin}{USER_MODEL_STATS_PATH}",
        {"apiKey": api_key, "period": period},
        timeout,
    )


def _humanize_http_error(e: urllib.error.HTTPError) -> str:
    body = e.read().decode("utf-8", errors="replace")
    try:
        j = json.loads(body)
        msg = j.get("message") or j.get("error") or body
    except json.JSONDecodeError:
        msg = body or f"HTTP {e.code}"
    return f"HTTP {e.code}: {msg}"


def _safe_call(fn, *args) -> tuple[bool, Any]:
    try:
        return True, fn(*args)
    except urllib.error.HTTPError as e:
        return False, _humanize_http_error(e)
    except urllib.error.URLError as e:
        return False, f"connection error: {e.reason}"
    except TimeoutError as e:
        return False, f"timeout: {e}"
    except json.JSONDecodeError as e:
        return False, f"invalid JSON response: {e}"


def fetch_all(
    provider: ProviderTarget, periods: tuple[str, ...], timeout: float
) -> tuple[bool, FetchResult | str]:
    if not provider.base_url:
        return False, "no base_url in config"
    if not provider.key:
        return False, (
            f"no key resolved (env_key={provider.env_key!r}, "
            "no OPENAI_API_KEY in auth.json, no --key)"
        )
    try:
        origin = origin_of(provider.base_url)
    except ValueError as e:
        return False, str(e)

    result = FetchResult()

    with ThreadPoolExecutor(max_workers=max(1, 1 + len(periods))) as ex:
        f_stats = ex.submit(_safe_call, call_user_stats, origin, provider.key, timeout)
        f_models = {
            p: ex.submit(_safe_call, call_user_model_stats, origin, provider.key, p, timeout)
            for p in periods
        }

        ok, payload = f_stats.result()
        if not ok:
            return False, str(payload)
        if not payload.get("success"):
            msg = payload.get("message") or payload.get("error") or "unknown error"
            return False, str(msg)
        result.stats = payload

        for p, fut in f_models.items():
            ok, payload = fut.result()
            if not ok:
                result.errors[p] = str(payload)
                result.model_stats[p] = []
                continue
            if not payload.get("success"):
                result.errors[p] = str(payload.get("message") or payload.get("error") or "unknown error")
                result.model_stats[p] = []
                continue
            result.model_stats[p] = payload.get("data") or []

    return True, result


def _format_money(x: float | int | None) -> str:
    if x is None:
        return "-"
    return f"${float(x):,.4f}"


def _format_money_short(x: float | int | None) -> str:
    if x is None:
        return "-"
    v = float(x)
    if abs(v) >= 100:
        return f"${v:,.2f}"
    return f"${v:,.4f}"


def _format_int(n: int | float | None) -> str:
    if n is None:
        return "-"
    return f"{int(n):,}"


def _format_count(n: int | float | None, compact: bool = True) -> str:
    """Token / 请求数格式化。compact=True 时用 K/M/B 单位。"""
    if n is None:
        return "-"
    v = int(n)
    if not compact:
        return f"{v:,}"
    if v < 1000:
        return str(v)
    if v < 1_000_000:
        x = v / 1000
        return f"{x:.1f}K" if x < 100 else f"{int(round(x))}K"
    if v < 1_000_000_000:
        x = v / 1_000_000
        return f"{x:.1f}M" if x < 100 else f"{int(round(x))}M"
    x = v / 1_000_000_000
    return f"{x:.2f}B"


def _format_pct(used: float | int | None, limit: float | int | None) -> str:
    if not limit or float(limit) <= 0:
        return f"{_format_money(used)}（无上限）"
    pct = float(used or 0) / float(limit) * 100
    return f"{_format_money(used)} / {_format_money(limit)}  ({pct:.1f}%)"


def _format_seconds(s: int | None) -> str:
    if s is None or s <= 0:
        return "—"
    h, rem = divmod(int(s), 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m{sec:02d}s"
    if m:
        return f"{m}m{sec:02d}s"
    return f"{sec}s"


def _display_width(s: str) -> int:
    """Approximate terminal width: CJK 字符按 2 计，其他按 1。"""
    width = 0
    for ch in s:
        o = ord(ch)
        if o >= 0x1100 and (
            o <= 0x115F
            or 0x2E80 <= o <= 0x303E
            or 0x3041 <= o <= 0x33FF
            or 0x3400 <= o <= 0x4DBF
            or 0x4E00 <= o <= 0x9FFF
            or 0xA000 <= o <= 0xA4CF
            or 0xAC00 <= o <= 0xD7A3
            or 0xF900 <= o <= 0xFAFF
            or 0xFE30 <= o <= 0xFE4F
            or 0xFF00 <= o <= 0xFF60
            or 0xFFE0 <= o <= 0xFFE6
        ):
            width += 2
        else:
            width += 1
    return width


def _pad(s: str, width: int, align: str = "left") -> str:
    diff = width - _display_width(s)
    if diff <= 0:
        return s
    if align == "right":
        return " " * diff + s
    return s + " " * diff


def _render_model_table(
    models: list[dict[str, Any]], top: int, compact: bool
) -> list[str]:
    rows: list[tuple[str, str, str, str, str, str]] = [
        ("模型", "请求", "Tokens", "输入/输出", "缓存写/读", "费用")
    ]
    shown = models[:top] if top > 0 else models
    for m in shown:
        model_name = str(m.get("model", "?"))
        req = _format_count(m.get("requests"), compact)
        tokens = _format_count(m.get("allTokens"), compact)
        in_tok = _format_count(m.get("inputTokens"), compact)
        out_tok = _format_count(m.get("outputTokens"), compact)
        cc = _format_count(m.get("cacheCreateTokens"), compact)
        cr = _format_count(m.get("cacheReadTokens"), compact)
        cost = m.get("costs", {}).get("total")
        cost_str = _format_money_short(cost) if cost is not None else "-"
        rows.append((
            model_name,
            req,
            tokens,
            f"{in_tok}/{out_tok}",
            f"{cc}/{cr}",
            cost_str,
        ))

    widths = [0] * 6
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], _display_width(cell))

    aligns = ("left", "right", "right", "right", "right", "right")
    lines: list[str] = []
    for idx, row in enumerate(rows):
        cells = [_pad(c, widths[i], aligns[i]) for i, c in enumerate(row)]
        line = "      " + "  ".join(cells)
        lines.append(line)
        if idx == 0:
            sep = "      " + "  ".join("─" * widths[i] for i in range(6))
            lines.append(sep)

    if top > 0 and len(models) > top:
        lines.append(f"      （还有 {len(models) - top} 个模型未列出，--top 0 显示全部）")
    return lines


def render_text(
    provider: ProviderTarget,
    result: FetchResult,
    periods: tuple[str, ...],
    top: int,
    show_models: bool,
    compact: bool,
) -> str:
    out: list[str] = []
    origin = origin_of(provider.base_url) if provider.base_url else "?"
    out.append(f"■ {provider.name}  {origin}  key 来源 {provider.key_source}")

    payload = result.stats or {}
    data = payload.get("data") or {}
    usage_total = (data.get("usage") or {}).get("total") or {}
    limits = data.get("limits") or {}

    name = data.get("name") or "-"
    key_id = data.get("id") or "-"
    active = "启用" if data.get("isActive") else "禁用"
    expires_raw = data.get("expiresAt")
    expires = expires_raw if expires_raw else "永不过期"
    out.append(f"  Key: {name}  id={key_id}  {active}  {expires}")

    out.append("")
    out.append("  📊 累计用量")
    in_tok = usage_total.get("inputTokens", 0) or 0
    out_tok = usage_total.get("outputTokens", 0) or 0
    cc_tok = usage_total.get("cacheCreateTokens", 0) or 0
    cr_tok = usage_total.get("cacheReadTokens", 0) or 0
    all_tok = usage_total.get("allTokens") or (in_tok + out_tok + cc_tok + cr_tok)
    cost = usage_total.get("cost")
    out.append(
        f"    请求 {_format_count(usage_total.get('requests'), compact)}    "
        f"Tokens {_format_count(all_tok, compact)}    "
        f"费用 {_format_money(cost)}"
    )
    out.append(
        f"    输入 {_format_count(in_tok, compact)} / "
        f"输出 {_format_count(out_tok, compact)} / "
        f"缓存创建 {_format_count(cc_tok, compact)} / "
        f"缓存读取 {_format_count(cr_tok, compact)}"
    )

    out.append("")
    out.append("  💰 限额")
    daily_used = limits.get("currentDailyCost", 0)
    daily_lim = limits.get("dailyCostLimit", 0)
    out.append(f"    今日费用  {_format_pct(daily_used, daily_lim)}")
    total_used = limits.get("currentTotalCost", 0)
    total_lim = limits.get("totalCostLimit", 0)
    out.append(f"    总费用    {_format_pct(total_used, total_lim)}")

    win_min = limits.get("rateLimitWindow", 0) or 0
    if win_min:
        win_h, win_m = divmod(int(win_min), 60)
        win_label = f"{win_h}h{win_m:02d}m" if win_h else f"{win_m}m"
        req_used = limits.get("currentWindowRequests", 0)
        req_lim = limits.get("rateLimitRequests", 0)
        tok_used = limits.get("currentWindowTokens", 0)
        tok_lim = limits.get("tokenLimit", 0)
        cost_used = limits.get("currentWindowCost", 0)
        cost_lim = limits.get("rateLimitCost", 0)
        remaining = _format_seconds(limits.get("windowRemainingSeconds"))
        out.append(f"    速率窗口  窗口 {win_label}，剩余 {remaining}")
        out.append(
            f"              请求 {_format_int(req_used)}/"
            f"{_format_int(req_lim) if req_lim else '∞'}  "
            f"Tokens {_format_int(tok_used)}/"
            f"{_format_int(tok_lim) if tok_lim else '∞'}  "
            f"费用 {_format_money(cost_used)}/"
            f"{_format_money(cost_lim) if cost_lim else '∞'}"
        )
    else:
        out.append("    速率窗口  未配置")

    weekly_lim = limits.get("weeklyOpusCostLimit", 0)
    if weekly_lim:
        out.append(f"    本周 Opus {_format_pct(limits.get('weeklyOpusCost', 0), weekly_lim)}")

    if show_models:
        out.append("")
        out.append("  🧠 模型细分")
        for p in periods:
            label = PERIOD_LABELS.get(p, p)
            err = result.errors.get(p)
            models = result.model_stats.get(p, [])
            if err:
                out.append(f"    [{label}]  查询失败：{err}")
                continue
            count = len(models)
            if count == 0:
                out.append(f"    [{label}]  无数据")
                continue
            out.append(f"    [{label}]  {count} 个模型")
            out.extend(_render_model_table(models, top, compact))

    return "\n".join(out)


def render_error(provider: ProviderTarget, message: str) -> str:
    origin = origin_of(provider.base_url) if provider.base_url else "?"
    return f"■ {provider.name}  {origin}  错误：{message}"


def run_codex_flow(args: argparse.Namespace) -> int:
    if args.base_url and not args.key:
        print(
            "warning: --base-url 未配 --key 时仍会回退到 codex 配置解析",
            file=sys.stderr,
        )

    if args.key and args.base_url:
        cfg: dict[str, Any] = {}
        auth_data: dict[str, Any] = {}
    else:
        try:
            cfg = load_toml(args.config)
        except FileNotFoundError:
            print(f"error: codex config not found: {args.config}", file=sys.stderr)
            return 2
        auth_data = load_json(args.auth)

    targets = build_targets(cfg, auth_data, args.provider, args.key, args.base_url)

    if not targets:
        print("error: no model_providers found in config", file=sys.stderr)
        return 2

    if args.period == "all":
        periods: tuple[str, ...] = PERIOD_ORDER
    else:
        periods = (args.period,)
    if not args.show_models:
        periods = ()

    exit_code = 0
    blocks: list[str] = []
    json_out: list[dict[str, Any]] = []

    for t in targets:
        ok, result = fetch_all(t, periods, args.timeout)
        if args.as_json:
            entry: dict[str, Any] = {
                "provider": t.name,
                "base_url": t.base_url,
                "origin": origin_of(t.base_url) if t.base_url else None,
                "key_source": t.key_source,
                "ok": ok,
            }
            if ok and isinstance(result, FetchResult):
                entry["data"] = result.stats
                entry["model_stats"] = result.model_stats
                if result.errors:
                    entry["model_stats_errors"] = result.errors
            else:
                entry["error"] = result if isinstance(result, str) else "unknown"
                exit_code = 1
            json_out.append(entry)
        else:
            if ok and isinstance(result, FetchResult):
                blocks.append(render_text(t, result, periods, args.top, args.show_models, not args.wide))
            else:
                blocks.append(render_error(t, str(result)))
                exit_code = 1

    if args.as_json:
        if len(json_out) == 1:
            print(json.dumps(json_out[0], ensure_ascii=False, indent=2))
        else:
            print(json.dumps(json_out, ensure_ascii=False, indent=2))
    else:
        print("\n\n".join(blocks))

    return exit_code


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


def render_accounts_table(account_type: str, payload: dict[str, Any]) -> str:
    accs = _safe(payload, "data") or payload.get("accounts") or []
    if not isinstance(accs, list) or not accs:
        return f"(无 {account_type} 账号)"

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


# ===== Admin: TUI =====

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.widgets import Header, Footer, Static, DataTable, ContentSwitcher, Tabs, Tab, Sparkline


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
        self.current_account_type = "claude"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(
            f"profile: {self.profile_name}  base: {self.client.profile.base_url}",
            id="status",
        )
        with ContentSwitcher(initial="dashboard", id="view"):
            with Vertical(id="dashboard"):
                yield Static("loading...", id="dash-summary")
                yield DataTable(id="dash-models")
            with Vertical(id="api-keys"):
                yield Static("loading...", id="keys-status")
                yield DataTable(id="keys-table")
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
            with Vertical(id="trend"):
                yield Static("loading...", id="trend-status")
                yield Static("请求", id="trend-req-label")
                yield Sparkline([], id="trend-req")
                yield Static("Tokens", id="trend-tok-label")
                yield Sparkline([], id="trend-tok")
                yield Static("费用", id="trend-cost-label")
                yield Sparkline([], id="trend-cost")
                yield DataTable(id="trend-table")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_current()

    def action_set_view(self, view: str) -> None:
        self.current_view = view
        self.query_one(ContentSwitcher).current = view
        self.refresh_current()

    def action_refresh_view(self) -> None:
        self.refresh_current()

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

    def refresh_current(self) -> None:
        v = self.current_view
        if v == "dashboard":
            self._refresh_dashboard()
        elif v == "api-keys":
            self._refresh_api_keys()
        elif v == "accounts":
            self._refresh_accounts()
        elif v == "trend":
            self._refresh_trend()



# ===== CLI subparsers & entry =====

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
    except AdminAuthError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


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
                        default="all", help="模型细分时段：daily / monthly / alltime / all（默认 all，三段都拉）")
    parser.add_argument("--top", type=int, default=5,
                        help="每个时段展示前 N 个模型（0 = 全部）")
    parser.add_argument("--no-models", dest="show_models", action="store_false",
                        help="关闭模型细分查询")
    parser.add_argument("--wide", action="store_true", help="文本输出完整数字")

    subparsers = parser.add_subparsers(dest="cmd")

    admin_p = subparsers.add_parser("admin", help="管理员视图（登录 CRS /admin/*）")
    admin_sub = admin_p.add_subparsers(dest="admin_cmd")
    admin_p.add_argument("--profile", help="profile 名（默认用 admin_default）")
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


if __name__ == "__main__":
    raise SystemExit(main())
