"""
实时轮询主循环
每隔 POLL_INTERVAL 秒拉取一次赔率，扫描套利，广播给 WebSocket 客户端
"""
import asyncio
import json
import requests
from datetime import datetime, timezone

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import (
    API_KEY,
    ODDS_API_BASE,
    REGION,
    REGIONS,
    POLL_INTERVAL,
    SOCCER_WC,
    MARKETS,
    CORE_MARKETS,
    REQUIRE_POSITIVE_AFTER_COMMISSION,
    MIN_PROFIT_AFTER_COMMISSION_PCT,
    MIN_SLIPPAGE_TOLERANCE_PCT,
    MAX_CONCENTRATION_RISK,
    MAX_TRUSTED_ODDS,
    SUSPICIOUS_PROFIT_PCT,
)
from engine.arbitrage import scan_arbitrage, scan_near_arb, scan_info_gap, scan_market_dimensions, scan_middles
from data.db import init_db, save_odds, save_arb

# WebSocket 广播回调（由 app.py 注入）
_broadcast_fn = None
_signal_first_seen: dict[str, str] = {}
_signal_strategy: dict[str, str] = {}
_signal_closed_seconds: dict[str, list[float]] = {}
MAX_SIGNAL_TIMING_SAMPLES = 200

def set_broadcast(fn):
    global _broadcast_fn
    _broadcast_fn = fn


def _signal_key(kind: str, item: dict) -> str:
    if kind == "h2h_arb":
        return f"h2h-arb-{item['event_id']}"
    if kind == "h2h_near":
        return f"h2h-near-{item['event_id']}"
    if kind == "market_surebet":
        market_key = item.get("market_key") or item.get("dimension") or ""
        return f"{market_key}-surebet-{item['event_id']}-{item.get('line') or 'main'}"
    if kind == "market_near":
        market_key = item.get("market_key") or item.get("dimension") or ""
        return f"{market_key}-near-{item['event_id']}-{item.get('line') or 'main'}"
    if kind == "middle":
        return f"middle-{item['event_id']}-{item['low_line']}-{item['high_line']}"
    if kind == "gap":
        return f"gap-{item['event_id']}"
    return f"{kind}-{item.get('event_id', 'unknown')}"


def _active_signal_meta(region_payloads: dict) -> list[dict]:
    rows = []
    for region_key, payload in region_payloads.items():
        for item in payload.get("arbitrages", []):
            rows.append({"key": f"{region_key}:{_signal_key('h2h_arb', item)}", "strategy": "surebet"})
        for item in payload.get("near_arb", []):
            rows.append({"key": f"{region_key}:{_signal_key('h2h_near', item)}", "strategy": "near"})
        for item in payload.get("market_dimensions", {}).get("surebets", []):
            rows.append({"key": f"{region_key}:{_signal_key('market_surebet', item)}", "strategy": "multi_market"})
        for item in payload.get("market_dimensions", {}).get("near", []):
            rows.append({"key": f"{region_key}:{_signal_key('market_near', item)}", "strategy": "near"})
        for item in payload.get("middles", []):
            rows.append({"key": f"{region_key}:{_signal_key('middle', item)}", "strategy": "middle"})
        for item in payload.get("info_gap", []):
            rows.append({"key": f"{region_key}:{_signal_key('gap', item)}", "strategy": "info_gap"})
    return rows


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    mid = len(sorted_values) // 2
    if len(sorted_values) % 2:
        return sorted_values[mid]
    return (sorted_values[mid - 1] + sorted_values[mid]) / 2


def update_signal_timing(region_payloads: dict, now: str) -> dict:
    now_dt = _parse_iso(now) or datetime.now(timezone.utc)
    active = _active_signal_meta(region_payloads)
    active_keys = {item["key"] for item in active}

    for item in active:
        _signal_first_seen.setdefault(item["key"], now)
        _signal_strategy[item["key"]] = item["strategy"]

    for key, first_seen in list(_signal_first_seen.items()):
        if key in active_keys:
            continue
        strategy = _signal_strategy.get(key, "unknown")
        first_seen_dt = _parse_iso(first_seen) or now_dt
        duration = max(0.0, (now_dt - first_seen_dt).total_seconds())
        _signal_closed_seconds[strategy] = [
            *(_signal_closed_seconds.get(strategy, [])),
            duration,
        ][-MAX_SIGNAL_TIMING_SAMPLES:]
        _signal_first_seen.pop(key, None)
        _signal_strategy.pop(key, None)

    active_seconds = {}
    for key, first_seen in _signal_first_seen.items():
        first_seen_dt = _parse_iso(first_seen) or now_dt
        active_seconds[key] = max(0.0, (now_dt - first_seen_dt).total_seconds())

    avg_seconds = {}
    median_seconds = {}
    strategies = set(_signal_closed_seconds) | set(_signal_strategy.values())
    for strategy in strategies:
        closed = _signal_closed_seconds.get(strategy, [])
        active_values = [
            seconds for key, seconds in active_seconds.items()
            if _signal_strategy.get(key) == strategy
        ]
        values = [*closed, *active_values]
        avg_seconds[strategy] = sum(values) / len(values) if values else 0.0
        median_seconds[strategy] = _median(values)

    return {
        "first_seen": _signal_first_seen,
        "active_seconds": active_seconds,
        "avg_seconds_by_strategy": avg_seconds,
        "median_seconds_by_strategy": median_seconds,
        "closed_seconds_by_strategy": _signal_closed_seconds,
        "sample_limit": MAX_SIGNAL_TIMING_SAMPLES,
    }


def restore_signal_timing_from_snapshot(path: str = "data/latest_snapshot.json"):
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as f:
            snapshot = json.load(f)
        timing = snapshot.get("signal_timing") or {}
        first_seen = timing.get("first_seen") or {}
        if isinstance(first_seen, dict):
            _signal_first_seen.update(first_seen)
        closed = timing.get("closed_seconds_by_strategy") or {}
        if isinstance(closed, dict):
            for strategy, values in closed.items():
                if isinstance(values, list):
                    _signal_closed_seconds[strategy] = [
                        float(value) for value in values
                        if isinstance(value, (int, float))
                    ][-MAX_SIGNAL_TIMING_SAMPLES:]
    except Exception:
        return


def fetch_and_parse(region: str = REGION):
    """拉取并解析世界杯赔率，返回标准化事件列表"""
    if not API_KEY or API_KEY.startswith("replace_"):
        raise RuntimeError("ODDS_API_KEY is missing or still using the placeholder value")

    url = f"{ODDS_API_BASE}/sports/{SOCCER_WC}/odds"

    def request_odds(markets: list[str]):
        params = {
            "apiKey": API_KEY,
            "regions": region,
            "markets": ",".join(markets),
            "oddsFormat": "decimal",
        }
        return requests.get(url, params=params, timeout=15)

    r = request_odds(MARKETS)
    if r.status_code in {400, 422} and MARKETS != CORE_MARKETS:
        print(f"  [API:{region.upper()}] 扩展盘口不可用，回退到基础盘口")
        r = request_odds(CORE_MARKETS)
    try:
        r.raise_for_status()
    except requests.HTTPError as exc:
        body = r.text[:300]
        raise RuntimeError(f"The Odds API HTTP {r.status_code}: {body}") from exc
    raw = r.json()
    remaining = r.headers.get("x-requests-remaining", "?")

    events = []
    for ev in raw:
        item = {
            "id": ev["id"],
            "home_team": ev["home_team"],
            "away_team": ev["away_team"],
            "commence": ev["commence_time"],
            "bookmakers": {},
            "totals": {},
            "spreads": {},
            "btts": {},
            "draw_no_bet": {},
            "double_chance": {},
        }
        for bm in ev.get("bookmakers", []):
            bm_name = bm["title"]
            for mkt in bm["markets"]:
                if mkt["key"] == "h2h":
                    om = {o["name"]: o["price"] for o in mkt["outcomes"]}
                    item["bookmakers"][bm["title"]] = {
                        "home": om.get(ev["home_team"]),
                        "draw": om.get("Draw"),
                        "away": om.get(ev["away_team"]),
                    }
                elif mkt["key"] == "totals":
                    for outcome in mkt.get("outcomes", []):
                        point = outcome.get("point")
                        if point is None:
                            continue
                        line_key = str(float(point))
                        item["totals"].setdefault(line_key, {})
                        item["totals"][line_key].setdefault(bm_name, {"over": None, "under": None})
                        if outcome.get("name") == "Over":
                            item["totals"][line_key][bm_name]["over"] = outcome.get("price")
                        elif outcome.get("name") == "Under":
                            item["totals"][line_key][bm_name]["under"] = outcome.get("price")
                elif mkt["key"] == "spreads":
                    home_lines = {}
                    away_lines = {}
                    for outcome in mkt.get("outcomes", []):
                        point = outcome.get("point")
                        if point is None:
                            continue
                        name = outcome.get("name")
                        price = outcome.get("price")
                        point_f = float(point)
                        if name == ev["home_team"]:
                            home_lines[point_f] = price
                        elif name == ev["away_team"]:
                            away_lines[point_f] = price

                    # 仅保留镜像让球线: home +x 与 away -x
                    for home_point, home_price in home_lines.items():
                        away_point = -home_point
                        if away_point not in away_lines:
                            continue
                        line_key = str(home_point)
                        item["spreads"].setdefault(line_key, {})
                        item["spreads"][line_key][bm_name] = {
                            "home": home_price,
                            "away": away_lines[away_point],
                        }
                elif mkt["key"] == "btts":
                    values = {}
                    for outcome in mkt.get("outcomes", []):
                        name = (outcome.get("name") or "").strip().lower()
                        if name in {"yes", "y"}:
                            values["yes"] = outcome.get("price")
                        elif name in {"no", "n"}:
                            values["no"] = outcome.get("price")
                    if values:
                        item["btts"][bm_name] = values
                elif mkt["key"] == "draw_no_bet":
                    values = {}
                    for outcome in mkt.get("outcomes", []):
                        name = outcome.get("name")
                        if name == ev["home_team"]:
                            values["home"] = outcome.get("price")
                        elif name == ev["away_team"]:
                            values["away"] = outcome.get("price")
                    if values:
                        item["draw_no_bet"][bm_name] = values
                elif mkt["key"] == "double_chance":
                    values = {}
                    for outcome in mkt.get("outcomes", []):
                        name = (outcome.get("name") or "").lower()
                        price = outcome.get("price")
                        has_home = ev["home_team"].lower() in name
                        has_away = ev["away_team"].lower() in name
                        has_draw = "draw" in name
                        if has_home and has_draw:
                            values["home_draw"] = price
                        elif has_home and has_away:
                            values["home_away"] = price
                        elif has_draw and has_away:
                            values["draw_away"] = price
                    if values:
                        item["double_chance"][bm_name] = values
        events.append(item)

    return events, remaining


def build_region_payload(region: dict, events: list, remaining: str, now: str) -> dict:
    arbs_raw = scan_arbitrage(events, threshold_pct=0.0, total_stake=1000)
    arbs = scan_arbitrage(
        events,
        threshold_pct=0.0,
        total_stake=1000,
        require_positive_after_commission=REQUIRE_POSITIVE_AFTER_COMMISSION,
        min_profit_after_commission_pct=MIN_PROFIT_AFTER_COMMISSION_PCT,
        min_slippage_tolerance_pct=MIN_SLIPPAGE_TOLERANCE_PCT,
        max_concentration_risk=MAX_CONCENTRATION_RISK,
    )
    near = scan_near_arb(events, top_n=10)
    info_gap = scan_info_gap(events, top_n=12, min_gap_pct=3.0)
    market_dims = scan_market_dimensions(events, total_stake=1000, near_threshold=1.03, top_n=20)
    middles = scan_middles(events, total_stake=1000, max_outside_loss_pct=2.0, top_n=20)

    return {
        "key": region["key"],
        "label": region["label"],
        "group": region["group"],
        "currency": region.get("currency", "$"),
        "timestamp": now,
        "api_remaining": remaining,
        "total_events": len(events),
        "arbitrages": arbs,
        "arbitrages_raw": arbs_raw,
        "near_arb": near,
        "info_gap": info_gap,
        "market_dimensions": market_dims,
        "middles": middles,
        "filters": {
            "require_positive_after_commission": REQUIRE_POSITIVE_AFTER_COMMISSION,
            "min_profit_after_commission_pct": MIN_PROFIT_AFTER_COMMISSION_PCT,
            "min_slippage_tolerance_pct": MIN_SLIPPAGE_TOLERANCE_PCT,
            "max_concentration_risk": MAX_CONCENTRATION_RISK,
            "suspicious_profit_pct": SUSPICIOUS_PROFIT_PCT,
            "max_trusted_odds": MAX_TRUSTED_ODDS,
        },
        "all_events": events,
    }


async def poll_loop():
    """异步轮询主循环"""
    init_db()
    restore_signal_timing_from_snapshot()
    print(f"[调度器] 启动，轮询间隔: {POLL_INTERVAL}s")

    while True:
        now = datetime.now(timezone.utc).isoformat()
        try:
            print(f"[{now}] 拉取赔率...")
            region_payloads = {}
            api_remaining_by_region = {}

            for region in REGIONS:
                region_key = region["key"]
                try:
                    events, remaining = fetch_and_parse(region_key)
                    if region_key == REGION:
                        save_odds(now, events)

                    region_payload = build_region_payload(region, events, remaining, now)
                    region_payloads[region_key] = region_payload
                    api_remaining_by_region[region_key] = remaining

                    if region_key == REGION:
                        # 历史表只保留默认地区的策略信号，避免跨地区混入执行记录。
                        for a in region_payload["arbitrages"]:
                            save_arb(
                                detected_at=now,
                                event_id=a["event_id"],
                                match=a["match"],
                                commence=a["commence"],
                                margin=a["margin"],
                                profit_pct=a["profit_pct"],
                                detail={**a, "region": region_key},
                            )
                        for a in region_payload["market_dimensions"].get("surebets", []):
                            save_arb(
                                detected_at=now,
                                event_id=a["event_id"],
                                match=a["match"],
                                commence=a["commence"],
                                margin=a["margin"],
                                profit_pct=a["profit_pct"],
                                detail={**a, "region": region_key, "strategy": "multi_market"},
                            )
                        for m in region_payload["middles"]:
                            save_arb(
                                detected_at=now,
                                event_id=m["event_id"],
                                match=m["match"],
                                commence=m["commence"],
                                margin=m["margin"],
                                profit_pct=m["middle_profit_pct"],
                                detail={**m, "region": region_key, "strategy": "middle"},
                            )
                        for g in region_payload["info_gap"]:
                            save_arb(
                                detected_at=now,
                                event_id=g["event_id"],
                                match=g["match"],
                                commence=g["commence"],
                                margin=g.get("best_margin") or 0,
                                profit_pct=g["score"],
                                detail={**g, "region": region_key, "market_key": "info_gap", "strategy": "info_gap"},
                            )

                    print(
                        f"  {region_key.upper()} 比赛数: {region_payload['total_events']}"
                        f"  纸面套利: {len(region_payload['arbitrages_raw'])}"
                        f"  真实可执行: {len(region_payload['arbitrages'])}"
                        f"  多维可执行: {region_payload['market_dimensions']['summary']['surebet_count']}"
                        f"  Middle: {len(region_payload['middles'])}"
                        f"  剩余配额: {remaining}"
                    )
                except Exception as region_error:
                    error_message = str(region_error)
                    print(f"  [错误:{region_key.upper()}] {error_message}")
                    region_payloads[region_key] = {
                        "key": region_key,
                        "label": region["label"],
                        "group": region["group"],
                        "currency": region.get("currency", "$"),
                        "timestamp": now,
                        "error": error_message,
                        "api_remaining": "?",
                        "total_events": 0,
                        "arbitrages": [],
                        "arbitrages_raw": [],
                        "near_arb": [],
                        "info_gap": [],
                        "market_dimensions": {"surebets": [], "near": [], "summary": {"surebet_count": 0, "near_count": 0}},
                        "middles": [],
                        "filters": {},
                        "all_events": [],
                    }

            default_region = region_payloads.get(REGION) or next(iter(region_payloads.values()))
            signal_timing = update_signal_timing(region_payloads, now)
            payload = {
                "type": "update",
                "timestamp": now,
                "active_region": REGION,
                "regions": region_payloads,
                "signal_timing": signal_timing,
                "api_remaining_by_region": api_remaining_by_region,
                # Backward-compatible AU fields.
                "api_remaining": default_region["api_remaining"],
                "total_events": default_region["total_events"],
                "arbitrages": default_region["arbitrages"],
                "arbitrages_raw": default_region["arbitrages_raw"],
                "near_arb": default_region["near_arb"],
                "info_gap": default_region["info_gap"],
                "market_dimensions": default_region["market_dimensions"],
                "middles": default_region["middles"],
                "filters": default_region["filters"],
                "all_events": default_region["all_events"],
            }

            # 广播给所有 WebSocket 客户端
            if _broadcast_fn:
                await _broadcast_fn(json.dumps(payload, ensure_ascii=False))

            # 写入最新快照文件供 dashboard 初始加载
            with open("data/latest_snapshot.json", "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)

        except Exception as e:
            print(f"[错误] {e}")

        await asyncio.sleep(POLL_INTERVAL)
