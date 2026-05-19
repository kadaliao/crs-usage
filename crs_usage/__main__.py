from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_CONFIG = Path.home() / ".codex" / "config.toml"
DEFAULT_AUTH = Path.home() / ".codex" / "auth.json"
USER_STATS_PATH = "/apiStats/api/user-stats"


@dataclass
class ProviderTarget:
    name: str
    base_url: str
    env_key: str | None
    key: str | None
    key_source: str | None


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


def call_user_stats(origin: str, api_key: str, timeout: float) -> dict[str, Any]:
    req = urllib.request.Request(
        f"{origin}{USER_STATS_PATH}",
        data=json.dumps({"apiKey": api_key}).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "crs-usage/0.1"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    return json.loads(body)


def _format_money(x: float | int | None) -> str:
    if x is None:
        return "-"
    return f"${float(x):.4f}"


def _format_int(n: int | float | None) -> str:
    if n is None:
        return "-"
    return f"{int(n):,}"


def _format_pct(used: float | int | None, limit: float | int | None) -> str:
    if not limit or float(limit) <= 0:
        return "unlimited"
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


def render_text(provider: ProviderTarget, payload: dict[str, Any]) -> str:
    out: list[str] = []
    origin = origin_of(provider.base_url) if provider.base_url else "?"
    header = f"■ {provider.name}  ({origin})  key from {provider.key_source}"
    out.append(header)

    data = payload.get("data") or {}
    usage_total = (data.get("usage") or {}).get("total") or {}
    limits = data.get("limits") or {}

    name = data.get("name") or "-"
    key_id = data.get("id") or "-"
    active_raw = data.get("isActive")
    active = "true" if active_raw else "false"
    expires = data.get("expiresAt") or "never"
    out.append(f"  Key: {name}  id={key_id}  active={active}  expires={expires}")

    out.append("  Usage (total):")
    out.append(f"    Requests : {_format_int(usage_total.get('requests'))}")
    in_tok = usage_total.get("inputTokens", 0)
    out_tok = usage_total.get("outputTokens", 0)
    cc_tok = usage_total.get("cacheCreateTokens", 0)
    cr_tok = usage_total.get("cacheReadTokens", 0)
    all_tok = usage_total.get("allTokens") or (in_tok + out_tok + cc_tok + cr_tok)
    out.append(
        f"    Tokens   : {_format_int(all_tok)}  "
        f"(in {_format_int(in_tok)} / out {_format_int(out_tok)} / "
        f"cache_create {_format_int(cc_tok)} / cache_read {_format_int(cr_tok)})"
    )
    cost = usage_total.get("cost")
    formatted_cost = usage_total.get("formattedCost")
    out.append(f"    Cost     : {formatted_cost or _format_money(cost)}")

    out.append("  Limits:")
    daily_used = limits.get("currentDailyCost", 0)
    daily_lim = limits.get("dailyCostLimit", 0)
    out.append(f"    Daily Cost : {_format_pct(daily_used, daily_lim)}")

    total_used = limits.get("currentTotalCost", 0)
    total_lim = limits.get("totalCostLimit", 0)
    out.append(f"    Total Cost : {_format_pct(total_used, total_lim)}")

    win_min = limits.get("rateLimitWindow", 0) or 0
    if win_min:
        req_used = limits.get("currentWindowRequests", 0)
        req_lim = limits.get("rateLimitRequests", 0)
        tok_used = limits.get("currentWindowTokens", 0)
        tok_lim = limits.get("tokenLimit", 0)
        cost_used = limits.get("currentWindowCost", 0)
        cost_lim = limits.get("rateLimitCost", 0)
        remaining = _format_seconds(limits.get("windowRemainingSeconds"))
        parts = []
        parts.append(
            f"{_format_int(req_used)}/{_format_int(req_lim) if req_lim else '∞'} req"
        )
        parts.append(
            f"{_format_int(tok_used)}/{_format_int(tok_lim) if tok_lim else '∞'} tok"
        )
        parts.append(
            f"{_format_money(cost_used)}/{_format_money(cost_lim) if cost_lim else '∞'}"
        )
        out.append(
            f"    Rate Window: {', '.join(parts)}  window={win_min}m  剩余 {remaining}"
        )
    else:
        out.append("    Rate Window: unlimited")

    weekly_lim = limits.get("weeklyOpusCostLimit", 0)
    if weekly_lim:
        out.append(
            f"    Weekly Opus: {_format_pct(limits.get('weeklyOpusCost', 0), weekly_lim)}"
        )

    return "\n".join(out)


def render_error(provider: ProviderTarget, message: str) -> str:
    origin = origin_of(provider.base_url) if provider.base_url else "?"
    return f"■ {provider.name}  ({origin})  ERROR: {message}"


def query_one(provider: ProviderTarget, timeout: float) -> tuple[bool, dict[str, Any] | str]:
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
    try:
        payload = call_user_stats(origin, provider.key, timeout)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            j = json.loads(body)
            msg = j.get("message") or j.get("error") or body
        except json.JSONDecodeError:
            msg = body or f"HTTP {e.code}"
        return False, f"HTTP {e.code}: {msg}"
    except urllib.error.URLError as e:
        return False, f"connection error: {e.reason}"
    except TimeoutError as e:
        return False, f"timeout: {e}"
    except json.JSONDecodeError as e:
        return False, f"invalid JSON response: {e}"

    if not payload.get("success"):
        return False, payload.get("message") or payload.get("error") or "unknown error"
    return True, payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="crs-usage",
        description=(
            "Query claude-relay-service usage via your local Codex config. "
            "Reads ~/.codex/config.toml to find providers and POSTs to "
            "{base_origin}/apiStats/api/user-stats."
        ),
    )
    parser.add_argument("--provider", help="only query the given provider name")
    parser.add_argument("--key", help="API key override (skip codex auth resolution)")
    parser.add_argument(
        "--base-url",
        help="override base URL; only the scheme+host is used",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help=f"path to codex config.toml (default: {DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--auth",
        type=Path,
        default=DEFAULT_AUTH,
        help=f"path to codex auth.json (default: {DEFAULT_AUTH})",
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="output raw JSON (one object per provider, suitable for jq)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="HTTP timeout in seconds (default: 15)",
    )

    args = parser.parse_args(argv)

    # Manual override mode requires both --key and --base-url.
    if args.key and not args.base_url:
        # Still allow --key with codex config (will be applied to every provider).
        pass
    if args.base_url and not args.key:
        print(
            "warning: --base-url without --key still falls back to codex auth resolution",
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

    try:
        targets = build_targets(cfg, auth_data, args.provider, args.key, args.base_url)
    except SystemExit:
        raise

    if not targets:
        print("error: no model_providers found in config", file=sys.stderr)
        return 2

    exit_code = 0
    blocks: list[str] = []
    json_out: list[dict[str, Any]] = []

    for t in targets:
        ok, result = query_one(t, args.timeout)
        if args.as_json:
            entry: dict[str, Any] = {
                "provider": t.name,
                "base_url": t.base_url,
                "origin": origin_of(t.base_url) if t.base_url else None,
                "key_source": t.key_source,
                "ok": ok,
            }
            if ok:
                entry["data"] = result  # type: ignore[assignment]
            else:
                entry["error"] = result  # type: ignore[assignment]
            json_out.append(entry)
            if not ok:
                exit_code = 1
        else:
            if ok:
                blocks.append(render_text(t, result))  # type: ignore[arg-type]
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


if __name__ == "__main__":
    raise SystemExit(main())
