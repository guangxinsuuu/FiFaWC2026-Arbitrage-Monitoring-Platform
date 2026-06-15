import requests
import json
import sqlite3
import os
from datetime import datetime
from config import API_KEY, ODDS_API_BASE, REGION, MARKETS, SOCCER_WC, DB_PATH


def get_sports():
    """获取所有可用赛事列表"""
    url = f"{ODDS_API_BASE}/sports"
    r = requests.get(url, params={"apiKey": API_KEY})
    r.raise_for_status()
    return r.json()


def get_odds(sport_key=SOCCER_WC, markets="h2h"):
    """
    拉取指定赛事、地区的实时赔率
    返回标准化数据列表
    """
    url = f"{ODDS_API_BASE}/sports/{sport_key}/odds"
    params = {
        "apiKey": API_KEY,
        "regions": REGION,
        "markets": markets,
        "oddsFormat": "decimal",
    }
    r = requests.get(url, params=params)

    # 打印剩余配额
    remaining = r.headers.get("x-requests-remaining", "?")
    used = r.headers.get("x-requests-used", "?")
    print(f"  [API] 已用: {used}  剩余: {remaining}")

    r.raise_for_status()
    return r.json()


def parse_h2h(raw_data):
    """
    解析 H2H（胜平负）盘口，返回结构化数据：
    [
      {
        "match": "Argentina vs France",
        "commence": "2026-06-15T10:00:00Z",
        "bookmakers": {
          "Bet365": {"home": 2.10, "draw": 3.40, "away": 3.80},
          ...
        }
      },
      ...
    ]
    """
    results = []
    for event in raw_data:
        match_info = {
            "id": event["id"],
            "match": f"{event['home_team']} vs {event['away_team']}",
            "home_team": event["home_team"],
            "away_team": event["away_team"],
            "commence": event["commence_time"],
            "bookmakers": {},
        }

        for bm in event.get("bookmakers", []):
            bm_name = bm["title"]
            for market in bm.get("markets", []):
                if market["key"] == "h2h":
                    outcomes = {o["name"]: o["price"] for o in market["outcomes"]}
                    home_odds = outcomes.get(event["home_team"], None)
                    away_odds = outcomes.get(event["away_team"], None)
                    draw_odds = outcomes.get("Draw", None)
                    match_info["bookmakers"][bm_name] = {
                        "home": home_odds,
                        "draw": draw_odds,
                        "away": away_odds,
                    }

        if match_info["bookmakers"]:
            results.append(match_info)

    return results


def show_odds_table(parsed):
    """终端打印赔率对比表"""
    for event in parsed:
        print(f"\n{'='*70}")
        print(f"  {event['match']}")
        print(f"  开赛时间: {event['commence']}")
        print(f"{'='*70}")
        print(f"  {'平台':<20} {'主队':>8} {'平局':>8} {'客队':>8}")
        print(f"  {'-'*50}")
        for bm, odds in event["bookmakers"].items():
            h = f"{odds['home']:.2f}" if odds["home"] else "  -  "
            d = f"{odds['draw']:.2f}" if odds["draw"] else "  -  "
            a = f"{odds["away"]:.2f}" if odds["away"] else "  -  "
            print(f"  {bm:<20} {h:>8} {d:>8} {a:>8}")


if __name__ == "__main__":
    print("正在连接 The Odds API...")
    print(f"地区: {REGION.upper()}  赛事: 2026 FIFA World Cup\n")

    # 先检查世界杯是否在可用赛事中
    print(">>> 检查世界杯赛事状态...")
    sports = get_sports()
    wc = next((s for s in sports if s["key"] == SOCCER_WC), None)
    if wc:
        active = "✅ 活跃" if wc.get("active") else "⏳ 未开始/已结束"
        print(f"    {wc['title']} — {active}")
        print(f"    描述: {wc.get('description', '')}")
    else:
        print("    ⚠️  世界杯赛事未找到，列出所有足球赛事：")
        soccer = [s for s in sports if "soccer" in s["key"]]
        for s in soccer[:10]:
            print(f"    - {s['key']} ({s['title']})")

    # 拉取实时赔率
    print("\n>>> 拉取实时赔率...")
    try:
        raw = get_odds(SOCCER_WC, "h2h")
        if not raw:
            print("    当前无进行中的世界杯比赛赔率（可能赛事间歇期）")
            print("    尝试拉取其他足球赛事作为测试...")
            # fallback: 用其他活跃足球赛事测试 API 是否正常
            active_soccer = [s for s in sports if "soccer" in s["key"] and s.get("active")]
            if active_soccer:
                fallback_key = active_soccer[0]["key"]
                print(f"    使用 {fallback_key} 测试...")
                raw = get_odds(fallback_key, "h2h")
                if raw:
                    parsed = parse_h2h(raw)
                    show_odds_table(parsed[:2])  # 只展示2场
        else:
            parsed = parse_h2h(raw)
            print(f"    找到 {len(parsed)} 场比赛\n")
            show_odds_table(parsed)

            # 保存原始数据到 JSON
            os.makedirs("data", exist_ok=True)
            with open("data/latest_odds.json", "w", encoding="utf-8") as f:
                json.dump({"fetched_at": datetime.utcnow().isoformat(), "data": parsed}, f, ensure_ascii=False, indent=2)
            print(f"\n  数据已保存至 data/latest_odds.json")

    except requests.HTTPError as e:
        print(f"    ❌ HTTP错误: {e}")
        print(f"    响应: {e.response.text}")
