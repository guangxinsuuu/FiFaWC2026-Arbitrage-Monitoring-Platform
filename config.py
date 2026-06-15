import os


API_KEY = os.getenv("ODDS_API_KEY", "")

# Optional community support link. No payment processing is handled by this app.
DONATION_URL = os.getenv("DONATION_URL", "https://buymeacoffee.com/neilsuuu")

# 目标地区
REGION = "au"
REGIONS = [
    {"key": "au", "label": "Australia", "group": "Core", "currency": "A$"},
    {"key": "eu", "label": "Europe", "group": "Europe", "currency": "€"},
    {"key": "uk", "label": "United Kingdom", "group": "Europe", "currency": "£"},
    {"key": "us", "label": "United States", "group": "US", "currency": "US$"},
    {"key": "us2", "label": "United States 2", "group": "US", "currency": "US$"},
]

# 轮询间隔（秒）
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "30"))

# 套利触发阈值（利润率超过此值才报警）
ARB_THRESHOLD = 0.003  # 0.3%

# 真实执行过滤参数
# 仅保留：佣金后仍为正收益、且具备最小滑点缓冲、且不过度集中于单平台
REQUIRE_POSITIVE_AFTER_COMMISSION = True
MIN_PROFIT_AFTER_COMMISSION_PCT = 0.0
MIN_SLIPPAGE_TOLERANCE_PCT = 0.2
MAX_CONCENTRATION_RISK = 0.5
SUSPICIOUS_PROFIT_PCT = 10.0
MAX_TRUSTED_ODDS = 50.0

# 数据库路径
DB_PATH = "data/odds.db"

# The Odds API 端点
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

# 关注的盘口类型
# 当前只请求基础稳定市场，避免世界杯端点不支持扩展市场时产生额外 API 请求。
CORE_MARKETS = ["h2h", "totals", "spreads"]
OPTIONAL_MARKETS = []
DISABLED_MARKETS = ["btts", "double_chance", "draw_no_bet"]
MARKETS = CORE_MARKETS + OPTIONAL_MARKETS

# 世界杯赛事 key
SOCCER_WC = "soccer_fifa_world_cup"
