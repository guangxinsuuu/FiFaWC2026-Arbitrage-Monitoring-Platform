"""
套利扫描引擎
输入：解析后的赔率数据
输出：套利机会列表 + 最优投注分配
"""

from datetime import datetime, timezone

from config import MAX_TRUSTED_ODDS, SUSPICIOUS_PROFIT_PCT


def calc_market_arb(legs: list[dict], total_stake: float = 1000.0) -> dict | None:
    """
    通用 surebet 计算器。

    legs: [{"label": "...", "odds": 2.1, "bookmaker": "...", ...}]
    """
    valid_legs = [leg for leg in legs if leg.get("odds") and leg["odds"] > 0]
    if len(valid_legs) != len(legs) or len(valid_legs) < 2:
        return None

    margin = sum(1 / leg["odds"] for leg in valid_legs)
    guaranteed = total_stake / margin
    bet_legs = []
    for leg in valid_legs:
        stake = total_stake * (1 / leg["odds"]) / margin
        bet_legs.append({
            **leg,
            "stake": round(stake, 2),
            "payout": round(stake * leg["odds"], 2),
        })

    return {
        "margin": margin,
        "profit_pct": (1 / margin - 1) * 100,
        "total_stake": total_stake,
        "guaranteed_return": round(guaranteed, 2),
        "net_profit": round(guaranteed - total_stake, 2),
        "legs": valid_legs,
        "bets": bet_legs,
    }


def _market_payload(event: dict, market_key: str, market_label: str, line: str | None, legs: list[dict], total_stake: float) -> dict | None:
    result = calc_market_arb(legs, total_stake=total_stake)
    if result is None:
        return None
    risk_flags = _risk_flags(result["profit_pct"], result["bets"], event.get("commence"))
    return {
        "event_id": event["id"],
        "match": f"{event['home_team']} vs {event['away_team']}",
        "home_team": event["home_team"],
        "away_team": event["away_team"],
        "commence": event["commence"],
        "market_key": market_key,
        "market_label": market_label,
        "dimension": market_key,
        "line": line,
        "risk_flags": risk_flags,
        "is_suspicious": any(flag["level"] == "suspicious" for flag in risk_flags),
        **result,
    }


def find_best_odds_h2h(event: dict) -> dict | None:
    """从一场比赛的多家平台赔率中，提取每个结果的最高赔率"""
    home = event["home_team"]
    away = event["away_team"]
    best = {
        "home": {"odds": 0, "bookmaker": ""},
        "draw": {"odds": 0, "bookmaker": ""},
        "away": {"odds": 0, "bookmaker": ""},
    }

    for bm_name, odds in event.get("bookmakers", {}).items():
        if odds.get("home") and odds["home"] > best["home"]["odds"]:
            best["home"] = {"odds": odds["home"], "bookmaker": bm_name}
        if odds.get("draw") and odds["draw"] > best["draw"]["odds"]:
            best["draw"] = {"odds": odds["draw"], "bookmaker": bm_name}
        if odds.get("away") and odds["away"] > best["away"]["odds"]:
            best["away"] = {"odds": odds["away"], "bookmaker": bm_name}

    if not all(v["odds"] > 0 for v in best.values()):
        return None
    return best


def calc_arb(best_odds: dict, total_stake: float = 1000.0) -> dict:
    """
    计算套利参数
    返回: margin, profit_pct, 各方投注额, 保证回报
    """
    h = best_odds["home"]["odds"]
    d = best_odds["draw"]["odds"]
    a = best_odds["away"]["odds"]

    margin = 1 / h + 1 / d + 1 / a
    profit_pct = (1 / margin - 1) * 100

    stake_home = total_stake * (1 / h) / margin
    stake_draw = total_stake * (1 / d) / margin
    stake_away = total_stake * (1 / a) / margin
    guaranteed = total_stake / margin

    return {
        "margin": margin,
        "profit_pct": profit_pct,
        "total_stake": total_stake,
        "guaranteed_return": guaranteed,
        "net_profit": guaranteed - total_stake,
        "bets": {
            "home": {
                "stake": round(stake_home, 2),
                "odds": h,
                "bookmaker": best_odds["home"]["bookmaker"],
                "payout": round(stake_home * h, 2),
            },
            "draw": {
                "stake": round(stake_draw, 2),
                "odds": d,
                "bookmaker": best_odds["draw"]["bookmaker"],
                "payout": round(stake_draw * d, 2),
            },
            "away": {
                "stake": round(stake_away, 2),
                "odds": a,
                "bookmaker": best_odds["away"]["bookmaker"],
                "payout": round(stake_away * a, 2),
            },
        },
    }


def calc_arb_with_betfair_commission(best_odds: dict, total_stake: float = 1000.0, commission: float = 0.05) -> dict:
    """
    计算在 Betfair 佣金影响下的收益（简化模型：仅当中奖腿来自 Betfair 时按利润收佣）。
    该值用于风控过滤，不替代实盘精算。
    """
    base = calc_arb(best_odds, total_stake)
    gross_payouts = {
        "home": base["bets"]["home"]["payout"],
        "draw": base["bets"]["draw"]["payout"],
        "away": base["bets"]["away"]["payout"],
    }

    net_payouts = {}
    for side in ("home", "draw", "away"):
        bookmaker = base["bets"][side]["bookmaker"]
        stake_side = base["bets"][side]["stake"]
        gross = gross_payouts[side]
        if bookmaker == "Betfair":
            profit_leg = max(gross - stake_side, 0)
            net_payouts[side] = gross - profit_leg * commission
        else:
            net_payouts[side] = gross

    guaranteed_after_commission = min(net_payouts.values())
    net_after_commission = guaranteed_after_commission - total_stake
    margin_after_commission = total_stake / guaranteed_after_commission if guaranteed_after_commission > 0 else 99

    return {
        "guaranteed_after_commission": guaranteed_after_commission,
        "net_after_commission": net_after_commission,
        "profit_pct_after_commission": (net_after_commission / total_stake) * 100,
        "margin_after_commission": margin_after_commission,
    }


def _hours_to_start(commence_iso: str) -> float | None:
    try:
        dt = datetime.fromisoformat(commence_iso.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return (dt - now).total_seconds() / 3600
    except Exception:
        return None


def _platform_concentration(bets: dict) -> dict:
    books = [bets["home"]["bookmaker"], bets["draw"]["bookmaker"], bets["away"]["bookmaker"]]
    unique_books = set(books)
    max_same = max(books.count(b) for b in unique_books)
    # max_same=3 风险高（全在一家），=1 风险低（三家分散）
    score = (max_same - 1) / 2
    return {
        "bookmakers_used": sorted(unique_books),
        "bookmaker_count": len(unique_books),
        "max_legs_same_bookmaker": max_same,
        "concentration_risk": round(score, 2),
    }


def _slippage_tolerance_pct(margin: float) -> float:
    # 若所有赔率同比例下滑 x，则新 margin = margin/(1-x)。保持套利需 x < 1-margin。
    return max(0.0, (1 - margin) * 100)


def _bet_list(bets) -> list[dict]:
    if isinstance(bets, dict):
        return list(bets.values())
    if isinstance(bets, list):
        return bets
    return []


def _risk_flags(profit_pct: float | None, bets, commence_iso: str | None = None) -> list[dict]:
    flags = []
    bet_rows = _bet_list(bets)

    if profit_pct is not None and profit_pct > SUSPICIOUS_PROFIT_PCT:
        flags.append({
            "level": "suspicious",
            "code": "high_profit",
            "message": f"Profit above {SUSPICIOUS_PROFIT_PCT:.0f}% requires manual verification.",
        })

    high_odds = [b for b in bet_rows if (b.get("odds") or 0) > MAX_TRUSTED_ODDS]
    if high_odds:
        flags.append({
            "level": "suspicious",
            "code": "high_odds",
            "message": f"One or more legs are above odds {MAX_TRUSTED_ODDS:.0f}.",
        })

    books = [b.get("bookmaker") for b in bet_rows if b.get("bookmaker")]
    if books:
        max_same = max(books.count(book) for book in set(books))
        if max_same >= 2:
            flags.append({
                "level": "warning",
                "code": "same_bookmaker_legs",
                "message": "Two or more legs come from the same bookmaker.",
            })

    hrs = _hours_to_start(commence_iso) if commence_iso else None
    if hrs is None:
        flags.append({
            "level": "warning",
            "code": "event_time_unknown",
            "message": "Event start time could not be verified.",
        })
    elif hrs < 0:
        flags.append({
            "level": "suspicious",
            "code": "event_started",
            "message": "Event appears to have already started.",
        })

    return flags


def _has_extreme_odds(bets) -> bool:
    return any((bet.get("odds") or 0) > MAX_TRUSTED_ODDS for bet in _bet_list(bets))


def _safe_gap_pct(max_odds: float, min_odds: float) -> float:
    if max_odds <= 0 or min_odds <= 0:
        return 0.0
    return (max_odds - min_odds) / min_odds * 100


def analyze_info_gap(event: dict) -> dict | None:
    """
    评估平台间信息差（赔率分歧程度）。

    score 越高，代表各平台价格分歧越明显，更可能存在慢半拍平台。
    """
    bookmakers = event.get("bookmakers", {})
    if len(bookmakers) < 2:
        return None

    best = {
        "home": {"odds": 0.0, "bookmaker": ""},
        "draw": {"odds": 0.0, "bookmaker": ""},
        "away": {"odds": 0.0, "bookmaker": ""},
    }
    worst = {
        "home": {"odds": float("inf"), "bookmaker": ""},
        "draw": {"odds": float("inf"), "bookmaker": ""},
        "away": {"odds": float("inf"), "bookmaker": ""},
    }

    valid_rows = 0
    for bm_name, odds in bookmakers.items():
        h, d, a = odds.get("home"), odds.get("draw"), odds.get("away")
        if not (h and d and a):
            continue
        valid_rows += 1

        if h > best["home"]["odds"]:
            best["home"] = {"odds": h, "bookmaker": bm_name}
        if d > best["draw"]["odds"]:
            best["draw"] = {"odds": d, "bookmaker": bm_name}
        if a > best["away"]["odds"]:
            best["away"] = {"odds": a, "bookmaker": bm_name}

        if h < worst["home"]["odds"]:
            worst["home"] = {"odds": h, "bookmaker": bm_name}
        if d < worst["draw"]["odds"]:
            worst["draw"] = {"odds": d, "bookmaker": bm_name}
        if a < worst["away"]["odds"]:
            worst["away"] = {"odds": a, "bookmaker": bm_name}

    if valid_rows < 2:
        return None

    home_gap_pct = _safe_gap_pct(best["home"]["odds"], worst["home"]["odds"])
    draw_gap_pct = _safe_gap_pct(best["draw"]["odds"], worst["draw"]["odds"])
    away_gap_pct = _safe_gap_pct(best["away"]["odds"], worst["away"]["odds"])
    avg_gap_pct = (home_gap_pct + draw_gap_pct + away_gap_pct) / 3

    score = avg_gap_pct
    order_hint = [
        {
            "side": "home",
            "bookmaker": best["home"]["bookmaker"],
            "odds": best["home"]["odds"],
            "gap_pct": round(home_gap_pct, 2),
        },
        {
            "side": "draw",
            "bookmaker": best["draw"]["bookmaker"],
            "odds": best["draw"]["odds"],
            "gap_pct": round(draw_gap_pct, 2),
        },
        {
            "side": "away",
            "bookmaker": best["away"]["bookmaker"],
            "odds": best["away"]["odds"],
            "gap_pct": round(away_gap_pct, 2),
        },
    ]
    order_hint.sort(key=lambda x: x["gap_pct"], reverse=True)

    return {
        "event_id": event["id"],
        "match": f"{event['home_team']} vs {event['away_team']}",
        "home_team": event["home_team"],
        "away_team": event["away_team"],
        "commence": event["commence"],
        "bookmaker_count": valid_rows,
        "score": round(score, 2),
        "avg_gap_pct": round(avg_gap_pct, 2),
        "home_gap_pct": round(home_gap_pct, 2),
        "draw_gap_pct": round(draw_gap_pct, 2),
        "away_gap_pct": round(away_gap_pct, 2),
        "best": best,
        "worst": worst,
        "order_hint": order_hint,
    }


def scan_arbitrage(
    events: list,
    threshold_pct: float = 0.0,
    total_stake: float = 1000.0,
    require_positive_after_commission: bool = False,
    min_profit_after_commission_pct: float = 0.0,
    min_slippage_tolerance_pct: float = 0.0,
    max_concentration_risk: float = 1.0,
) -> list:
    """
    扫描所有比赛，返回套利机会列表（按利润率降序）

    threshold_pct: 最低纸面利润率过滤（0.0 = 只要有套利就返回）
    require_positive_after_commission: 是否要求佣金后收益为正
    min_profit_after_commission_pct: 佣金后最低收益率
    min_slippage_tolerance_pct: 最低滑点容忍百分比
    max_concentration_risk: 最大平台集中风险（0~1）
    """
    opportunities = []

    for event in events:
        best = find_best_odds_h2h(event)
        if best is None:
            continue

        gap = analyze_info_gap(event)

        result = calc_arb(best, total_stake)
        if result["margin"] < 1.0 and result["profit_pct"] >= threshold_pct:
            if _has_extreme_odds(result["bets"]):
                continue
            commission_adj = calc_arb_with_betfair_commission(best, total_stake=total_stake, commission=0.05)
            concentration = _platform_concentration(result["bets"])
            hrs = _hours_to_start(event["commence"])
            risk_flags = _risk_flags(result["profit_pct"], result["bets"], event.get("commence"))
            opportunity = {
                "event_id": event["id"],
                "match": f"{event['home_team']} vs {event['away_team']}",
                "home_team": event["home_team"],
                "away_team": event["away_team"],
                "commence": event["commence"],
                "info_gap": gap,
                "execution": {
                    "hours_to_start": round(hrs, 2) if hrs is not None else None,
                    "slippage_tolerance_pct": round(_slippage_tolerance_pct(result["margin"]), 3),
                    **concentration,
                },
                "commission_adjusted": {
                    "betfair_commission_pct": 5.0,
                    **commission_adj,
                },
                "risk_flags": risk_flags,
                "is_suspicious": any(flag["level"] == "suspicious" for flag in risk_flags),
                **result,
            }

            if require_positive_after_commission and commission_adj["profit_pct_after_commission"] <= 0:
                continue
            if commission_adj["profit_pct_after_commission"] < min_profit_after_commission_pct:
                continue
            if opportunity["execution"]["slippage_tolerance_pct"] < min_slippage_tolerance_pct:
                continue
            if opportunity["execution"]["concentration_risk"] > max_concentration_risk:
                continue

            opportunities.append(opportunity)

    opportunities.sort(key=lambda x: x["profit_pct"], reverse=True)
    return opportunities


def scan_near_arb(events: list, top_n: int = 10) -> list:
    """返回最接近套利的N场（未达到套利阈值，但可监控）"""
    candidates = []

    for event in events:
        best = find_best_odds_h2h(event)
        if best is None:
            continue
        result = calc_arb(best)
        if result["margin"] >= 1.0:
            risk_flags = _risk_flags(result["profit_pct"], result["bets"], event.get("commence"))
            candidates.append({
                "event_id": event["id"],
                "match": f"{event['home_team']} vs {event['away_team']}",
                "home_team": event["home_team"],
                "away_team": event["away_team"],
                "commence": event["commence"],
                "risk_flags": risk_flags,
                "is_suspicious": any(flag["level"] == "suspicious" for flag in risk_flags),
                **result,
            })

    candidates.sort(key=lambda x: x["margin"])
    return candidates[:top_n]


def scan_info_gap(events: list, top_n: int = 10, min_gap_pct: float = 3.0) -> list:
    """返回平台间信息差最大的比赛（按 score 降序）"""
    ranked = []
    for event in events:
        gap = analyze_info_gap(event)
        if gap is None:
            continue
        if gap["avg_gap_pct"] < min_gap_pct:
            continue

        best = find_best_odds_h2h(event)
        margin = None
        profit_pct = None
        if best is not None:
            arb = calc_arb(best)
            margin = arb["margin"]
            profit_pct = arb["profit_pct"]

        ranked.append({
            **gap,
            "best_margin": margin,
            "best_profit_pct": profit_pct,
        })

    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[:top_n]


def _best_two_way(bookmakers_map: dict, side_a: str, side_b: str):
    best_a = {"odds": 0.0, "bookmaker": ""}
    best_b = {"odds": 0.0, "bookmaker": ""}
    for bm_name, odds in bookmakers_map.items():
        a = odds.get(side_a)
        b = odds.get(side_b)
        if a and a > best_a["odds"]:
            best_a = {"odds": a, "bookmaker": bm_name}
        if b and b > best_b["odds"]:
            best_b = {"odds": b, "bookmaker": bm_name}
    return best_a, best_b


def _best_multi_way(bookmakers_map: dict, sides: list[str]) -> dict:
    best = {side: {"odds": 0.0, "bookmaker": ""} for side in sides}
    for bm_name, odds in bookmakers_map.items():
        for side in sides:
            price = odds.get(side)
            if price and price > best[side]["odds"]:
                best[side] = {"odds": price, "bookmaker": bm_name}
    return best


def _quarter_line(line: str) -> bool:
    try:
        value = abs(float(line))
    except (TypeError, ValueError):
        return False
    return value % 0.5 != 0


def scan_market_dimensions(events: list, total_stake: float = 1000.0, near_threshold: float = 1.03, top_n: int = 20) -> dict:
    """
    扫描多维盘口（目前支持 totals/spreads）并返回：
    - surebets: margin<1 的可套利机会
    - near: 接近套利的机会（1 <= margin <= near_threshold）
    """
    surebets = []
    near = []

    for event in events:
        match = f"{event['home_team']} vs {event['away_team']}"

        # totals: 同一总进球线下 over/under 的跨平台套利
        for line, bm_map in event.get("totals", {}).items():
            best_over, best_under = _best_two_way(bm_map, "over", "under")
            if best_over["odds"] <= 0 or best_under["odds"] <= 0:
                continue

            payload = _market_payload(event, "totals", "大小球", line, [
                {"side": "over", "label": f"Over {line}", "odds": best_over["odds"], "bookmaker": best_over["bookmaker"]},
                {"side": "under", "label": f"Under {line}", "odds": best_under["odds"], "bookmaker": best_under["bookmaker"]},
            ], total_stake)
            if payload is None:
                continue
            margin = payload["margin"]
            if margin < 1:
                if not _has_extreme_odds(payload["bets"]):
                    surebets.append(payload)
            elif margin <= near_threshold:
                near.append(payload)

        # spreads: 同一让球线下 home/away 的跨平台套利
        for line, bm_map in event.get("spreads", {}).items():
            best_home, best_away = _best_two_way(bm_map, "home", "away")
            if best_home["odds"] <= 0 or best_away["odds"] <= 0:
                continue

            line_val = float(line)
            market_key = "asian_handicap" if _quarter_line(line) else "spreads"
            market_label = "亚洲盘" if market_key == "asian_handicap" else "让球盘"
            payload = _market_payload(event, market_key, market_label, line, [
                {"side": "home", "label": f"{event['home_team']} {line_val:+g}", "odds": best_home["odds"], "bookmaker": best_home["bookmaker"]},
                {"side": "away", "label": f"{event['away_team']} {-line_val:+g}", "odds": best_away["odds"], "bookmaker": best_away["bookmaker"]},
            ], total_stake)
            if payload is None:
                continue
            margin = payload["margin"]
            if margin < 1:
                if not _has_extreme_odds(payload["bets"]):
                    surebets.append(payload)
            elif margin <= near_threshold:
                near.append(payload)

        # 扩展二向/三向市场：BTTS、Draw No Bet、Double Chance
        prop_markets = [
            ("btts", "双方进球", ["yes", "no"]),
            ("draw_no_bet", "平局退款", ["home", "away"]),
            ("double_chance", "双重机会", ["home_draw", "home_away", "draw_away"]),
        ]
        for market_key, market_label, sides in prop_markets:
            bm_map = event.get(market_key, {})
            if not bm_map:
                continue
            best = _best_multi_way(bm_map, sides)
            if any(best[side]["odds"] <= 0 for side in sides):
                continue
            labels = {
                "yes": "Yes",
                "no": "No",
                "home": event["home_team"],
                "away": event["away_team"],
                "home_draw": f"{event['home_team']} or Draw",
                "home_away": f"{event['home_team']} or {event['away_team']}",
                "draw_away": f"Draw or {event['away_team']}",
            }
            payload = _market_payload(event, market_key, market_label, None, [
                {
                    "side": side,
                    "label": labels[side],
                    "odds": best[side]["odds"],
                    "bookmaker": best[side]["bookmaker"],
                }
                for side in sides
            ], total_stake)
            if payload is None:
                continue
            if payload["margin"] < 1:
                if not _has_extreme_odds(payload["bets"]):
                    surebets.append(payload)
            elif payload["margin"] <= near_threshold:
                near.append(payload)

    surebets.sort(key=lambda x: x["profit_pct"], reverse=True)
    near.sort(key=lambda x: x["margin"])
    return {
        "surebets": surebets[:top_n],
        "near": near[:top_n],
        "summary": {
            "surebet_count": len(surebets),
            "near_count": len(near),
        },
    }


def scan_middles(events: list, total_stake: float = 1000.0, max_outside_loss_pct: float = 2.0, top_n: int = 20) -> list:
    """
    扫描 totals 的跨线 middle。

    示例：Over 2.0 + Under 2.5。外侧结果小亏或保本，中间区间双赢。
    Asian Handicap middle 可复用同一框架，但足球让球盘结算细节更复杂，先从 totals 开始。
    """
    opportunities = []

    for event in events:
        totals = event.get("totals", {})
        lines = []
        for line in totals:
            try:
                lines.append(float(line))
            except (TypeError, ValueError):
                continue
        lines = sorted(set(lines))

        for low in lines:
            for high in lines:
                if high <= low:
                    continue
                low_key = str(float(low))
                high_key = str(float(high))
                best_over, _ = _best_two_way(totals.get(low_key, {}), "over", "under")
                _, best_under = _best_two_way(totals.get(high_key, {}), "over", "under")
                if best_over["odds"] <= 0 or best_under["odds"] <= 0:
                    continue

                margin = 1 / best_over["odds"] + 1 / best_under["odds"]
                stake_over = total_stake * (1 / best_over["odds"]) / margin
                stake_under = total_stake * (1 / best_under["odds"]) / margin
                outside_return = total_stake / margin
                outside_net = outside_return - total_stake
                outside_loss_pct = max(0.0, -outside_net / total_stake * 100)
                if outside_loss_pct > max_outside_loss_pct:
                    continue

                middle_return = stake_over * best_over["odds"] + stake_under * best_under["odds"]
                middle_net = middle_return - total_stake
                legs = [
                    {
                        "side": "over",
                        "label": f"Over {low_key}",
                        "line": low_key,
                        "odds": best_over["odds"],
                        "bookmaker": best_over["bookmaker"],
                        "stake": round(stake_over, 2),
                        "payout": round(stake_over * best_over["odds"], 2),
                    },
                    {
                        "side": "under",
                        "label": f"Under {high_key}",
                        "line": high_key,
                        "odds": best_under["odds"],
                        "bookmaker": best_under["bookmaker"],
                        "stake": round(stake_under, 2),
                        "payout": round(stake_under * best_under["odds"], 2),
                    },
                ]
                risk_flags = _risk_flags(middle_net / total_stake * 100, legs, event.get("commence"))
                opportunities.append({
                    "event_id": event["id"],
                    "match": f"{event['home_team']} vs {event['away_team']}",
                    "home_team": event["home_team"],
                    "away_team": event["away_team"],
                    "commence": event["commence"],
                    "market_key": "totals_middle",
                    "market_label": "大小球 Middle",
                    "low_line": low_key,
                    "high_line": high_key,
                    "middle_width": round(high - low, 2),
                    "margin": margin,
                    "outside_net": round(outside_net, 2),
                    "outside_loss_pct": round(outside_loss_pct, 3),
                    "middle_net": round(middle_net, 2),
                    "middle_profit_pct": round(middle_net / total_stake * 100, 3),
                    "total_stake": total_stake,
                    "legs": legs,
                    "risk_flags": risk_flags,
                    "is_suspicious": any(flag["level"] == "suspicious" for flag in risk_flags),
                })

    opportunities.sort(key=lambda x: (x["outside_loss_pct"], -x["middle_profit_pct"]))
    return opportunities[:top_n]


if __name__ == "__main__":
    import json
    with open("data/latest_odds.json") as f:
        raw = json.load(f)

    # 解析成引擎期望的格式
    events = []
    for ev in raw:
        item = {
            "id": ev["id"],
            "home_team": ev["home_team"],
            "away_team": ev["away_team"],
            "commence": ev["commence_time"],
            "bookmakers": {},
        }
        for bm in ev.get("bookmakers", []):
            for mkt in bm["markets"]:
                if mkt["key"] == "h2h":
                    om = {o["name"]: o["price"] for o in mkt["outcomes"]}
                    item["bookmakers"][bm["title"]] = {
                        "home": om.get(ev["home_team"]),
                        "draw": om.get("Draw"),
                        "away": om.get(ev["away_team"]),
                    }
        events.append(item)

    arbs = scan_arbitrage(events, total_stake=1000)
    print(f"找到 {len(arbs)} 个套利机会:\n")
    for a in arbs:
        print(f"  🎯 {a['match']}")
        print(f"     利润率: {a['profit_pct']:.3f}%  |  保证回报: A${a['guaranteed_return']:.2f}  净利: A${a['net_profit']:.2f}")
        for side, bet in a["bets"].items():
            label = {"home": "主队赢", "draw": "平局", "away": "客队赢"}[side]
            print(f"     {label}: 赔率{bet['odds']} @ {bet['bookmaker']}  下注 A${bet['stake']}")
        print()

    if not arbs:
        near = scan_near_arb(events, 5)
        print("最接近套利的5场:")
        for n in near:
            print(f"  margin={n['margin']:.4f}  {n['match']}")
