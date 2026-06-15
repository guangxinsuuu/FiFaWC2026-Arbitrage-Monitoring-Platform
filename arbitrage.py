"""
套利投注计算器 (Arbitrage Betting Calculator)
支持：双向赔率 / 三向赔率（胜/平/负）
"""

from itertools import product


def calculate_arbitrage(outcomes: list[dict], total_stake: float = 1000.0):
    """
    计算套利机会

    outcomes: 每个结果的最高赔率，格式如：
        [
            {"label": "主队赢", "odds": 2.10, "bookmaker": "Bet365"},
            {"label": "平局",   "odds": 3.50, "bookmaker": "William Hill"},
            {"label": "客队赢", "odds": 4.20, "bookmaker": "Pinnacle"},
        ]
    total_stake: 总投注金额（默认1000元）
    """
    implied_probs = [1 / o["odds"] for o in outcomes]
    margin = sum(implied_probs)

    print("=" * 55)
    print("  套利投注分析报告")
    print("=" * 55)
    print(f"\n{'结果':<10} {'赔率':>8} {'平台':<15} {'隐含概率':>10}")
    print("-" * 55)
    for o, ip in zip(outcomes, implied_probs):
        print(f"{o['label']:<10} {o['odds']:>8.2f} {o['bookmaker']:<15} {ip:>10.2%}")

    print("-" * 55)
    print(f"{'总隐含概率 (margin):':<35} {margin:>10.4f}")

    if margin < 1.0:
        profit_rate = (1 - margin) / margin
        print(f"\n✅ 存在套利机会！预期利润率: {profit_rate:.2%}")
        print(f"\n总投注金额: {total_stake:.2f} 元")
        print(f"\n{'结果':<10} {'投注金额':>12} {'若赢得':>12}")
        print("-" * 40)
        stakes = []
        for o, ip in zip(outcomes, implied_probs):
            stake = total_stake * (ip / margin)
            payout = stake * o["odds"]
            stakes.append(stake)
            print(f"{o['label']:<10} {stake:>12.2f} {payout:>12.2f}")

        guaranteed = total_stake / margin
        print("-" * 40)
        print(f"{'保证回报:':<10} {guaranteed:>12.2f}")
        print(f"{'净利润:':<10} {guaranteed - total_stake:>12.2f}")
    else:
        overround = (margin - 1) * 100
        print(f"\n❌ 无套利机会，庄家优势 (overround): {overround:.2f}%")
        print("   建议：寻找赔率更高的平台或等待赔率变动")

    print("=" * 55)


def find_best_odds(bookmaker_data: dict, total_stake: float = 1000.0):
    """
    从多家平台数据中自动选出每个结果的最高赔率并分析套利

    bookmaker_data 格式:
    {
        "Bet365":      {"主队赢": 2.10, "平局": 3.20, "客队赢": 3.80},
        "William Hill":{"主队赢": 2.05, "平局": 3.50, "客队赢": 3.90},
        "Pinnacle":    {"主队赢": 2.15, "平局": 3.30, "客队赢": 4.20},
    }
    """
    # 获取所有结果标签
    all_labels = list(next(iter(bookmaker_data.values())).keys())

    print("\n各平台赔率对比:")
    print(f"{'平台':<15}", end="")
    for label in all_labels:
        print(f"  {label:>8}", end="")
    print()
    print("-" * (15 + len(all_labels) * 10))

    for bm, odds_dict in bookmaker_data.items():
        print(f"{bm:<15}", end="")
        for label in all_labels:
            print(f"  {odds_dict.get(label, 0):>8.2f}", end="")
        print()

    # 选最高赔率
    print("\n最优赔率组合:")
    best_outcomes = []
    for label in all_labels:
        best_bm = max(bookmaker_data, key=lambda bm: bookmaker_data[bm].get(label, 0))
        best_odds = bookmaker_data[best_bm][label]
        best_outcomes.append({"label": label, "odds": best_odds, "bookmaker": best_bm})

    calculate_arbitrage(best_outcomes, total_stake)


# ─────────────────────────────────────────
# 示例：2026 世界杯某场比赛的多平台赔率
# ─────────────────────────────────────────
if __name__ == "__main__":

    # 示例1：手动输入最优赔率（三向）
    print("\n【示例1：手动赔率输入】")
    outcomes_example = [
        {"label": "主队赢", "odds": 2.20, "bookmaker": "Bet365"},
        {"label": "平局",   "odds": 3.60, "bookmaker": "William Hill"},
        {"label": "客队赢", "odds": 4.50, "bookmaker": "Pinnacle"},
    ]
    calculate_arbitrage(outcomes_example, total_stake=1000)

    # 示例2：从多平台数据自动找最优赔率
    print("\n\n【示例2：多平台自动比较】")
    bookmakers = {
        "Bet365":       {"主队赢": 2.10, "平局": 3.20, "客队赢": 3.80},
        "William Hill": {"主队赢": 2.05, "平局": 3.50, "客队赢": 3.90},
        "Pinnacle":     {"主队赢": 2.15, "平局": 3.30, "客队赢": 4.20},
        "1xBet":        {"主队赢": 2.20, "平局": 3.60, "客队赢": 3.70},
    }
    find_best_odds(bookmakers, total_stake=1000)

    # 示例3：交互式输入
    print("\n\n【示例3：自定义输入】")
    try:
        n = int(input("请输入结果数量（双向=2，三向=3）: "))
        stake = float(input("请输入总投注金额: "))
        outcomes_custom = []
        for i in range(n):
            label = input(f"  结果{i+1}名称（如'主队赢'）: ")
            odds  = float(input(f"  结果{i+1}最高赔率: "))
            bm    = input(f"  来自哪家平台: ")
            outcomes_custom.append({"label": label, "odds": odds, "bookmaker": bm})
        calculate_arbitrage(outcomes_custom, total_stake=stake)
    except (ValueError, KeyboardInterrupt):
        print("跳过交互输入")
