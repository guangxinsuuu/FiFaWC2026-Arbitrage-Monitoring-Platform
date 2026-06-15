# WC2026 套利监控台 - 已实现功能清单

更新时间：2026-06-12

## 1. 数据拉取与标准化

- 已接入 The Odds API（世界杯赛事 key：`soccer_fifa_world_cup`）
- 支持地区独立扫描：
  - Australia（`au`，`A$`）
  - Europe（`eu`，`€`）
  - United Kingdom（`uk`，`£`）
  - United States（`us`，`US$`）
  - United States 2（`us2`，`US$`）
- 各地区完全隔离计算，不做跨地区混合套利
- 已拉取并解析市场：
  - `h2h`（胜平负）
  - `totals`（大小球）
  - `spreads`（让球盘）
- 当前禁用且不请求 API：
  - `btts`（双方进球）
  - `double_chance`（双重机会）
  - `draw_no_bet`（平局退款）
- 轮询更新：每 30 秒
- 输出 API 剩余额度用于监控

## 2. 核心计算引擎

### 2.1 胜平负套利（H2H）

- 跨平台最优赔率提取
- 纸面套利计算：
  - margin
  - 利润率
  - 各腿下注金额
  - 保证回报/净利

### 2.2 真实执行风控维度（已接入）

- Betfair 佣金后收益（简化风控模型）
- 滑点容忍度（slippage tolerance）
- 平台集中风险（是否过度集中在单一平台）
- 开赛剩余时间（小时）

### 2.3 真实过滤器（硬过滤）

- 可配置开关与阈值（在 `config.py`）：
  - `REQUIRE_POSITIVE_AFTER_COMMISSION`
  - `MIN_PROFIT_AFTER_COMMISSION_PCT`
  - `MIN_SLIPPAGE_TOLERANCE_PCT`
  - `MAX_CONCENTRATION_RISK`
- 输出分层结果：
  - `arbitrages_raw`：纸面套利
  - `arbitrages`：通过真实过滤的可执行机会

### 2.4 平台信息差分析

- 计算主/平/客跨平台价差
- 信息差评分（score）
- 下单顺序建议（优先下价差最大的腿）

### 2.5 多维盘口扫描（不是只看赛果）

- 已实现 `totals`、`spreads`、`asian_handicap` 扫描
- `btts`、`double_chance`、`draw_no_bet` 保留代码解析能力，但当前禁用 API 请求
- 已引入通用 `legs/bets` 机会结构，二向/三向市场可共用同一计算器
- 输出：
  - `surebets`（margin < 1）
  - `near`（接近套利）
- 当前在实时数据下可能出现 0 条（由市场当时状态决定）

### 2.6 Middle Betting（第一版）

- 已实现 totals 跨线 middle 扫描
- 示例：
  - `Over 2.0`
  - `Under 2.5`
- 输出：
  - 外侧最差盈亏
  - middle 命中收益
  - 推荐下注金额

## 3. 存储与历史

- SQLite 本地存储：
  - odds 快照
  - 套利机会历史
- 支持历史读取与 CSV 导出

## 4. Dashboard 功能（前端）

- 默认英文界面，支持 English / 中文切换
- 顶部品牌区包含原创 WC2026 风格徽标占位与 slogan：`Not predicting outcomes. Exploiting inefficiencies.`
- 顶部状态栏显示刷新速率，不直接展示 API 剩余额度
- 专业免责声明：
  - 系统仅提供分析建议
  - 不构成下注指令或收益保证
  - 用户自行承担执行、合规、账户资格、限额与最终结果责任
  - 数据通过已配置授权赔率 API 实时获取
- 已新增 About / Support 页面：`/about`
- 社区支持 / Donation：
  - 顶部导航显示 `Support ❤️`
  - 右侧 Dashboard 显示 `Support Development` 卡片
  - Buy Me a Coffee 链接：`https://buymeacoffee.com/neilsuuu`
  - 捐赠完全自愿，不隐藏任何功能，不包含订阅、登录、付费墙或站内支付处理
- 实时连接状态（WebSocket）
- 左侧改为 Strategy Scanner，按“如何赚钱”组织：
  - Surebets
    - 来源：H2H / 1X2
  - Near Arbitrage
    - 来源：H2H、Totals、Spreads、Asian Handicap 的接近套利
  - Middle Betting
    - 当前来源：Totals 跨线 middle
  - Information Gap
    - 来源：跨 bookmaker 价格分歧
  - Multi-Market
    - 来源：Totals、Spreads、Asian Handicap
- 每条机会卡片直接展示 Execution Plan：
  - 推荐下注腿
  - 赔率与平台
  - 按当前地区货币显示的 stake
  - Expected profit
  - 平均保留时间（Avg retained）
  - 中位数保留时间（Median）
  - 当前卡片已持续时间（Live for）
  - 明确提示当前操作窗口仍在，但下一次刷新前赔率可能变化
- 机会存活时间由后端轮询器统一维护并写入实时 payload：
  - 不随浏览器刷新、切换客户端或切换地区 tab 重置
  - 启动时会从最新快照恢复当前活跃信号的 first seen 时间与已关闭信号的平均保留时间样本
  - 每个策略仅保留最近 200 个关闭样本，用于计算平均值和中位数，不无限存储全量计时数据
- Dashboard 右栏顺序：
  - 当前策略机会列表
  - Support Development / Donate
  - Historical Stats（非 Today Stats）
  - History
  - All Matches
- 移动端顺序：
  - Strategy Scanner
  - 当前策略机会与支持/历史信息
  - 主详情面板与计算器
- 风险可信度标记：
  - `profit_pct > 10%` 标记 suspicious
  - `odds > 50` 视为极端赔率并从可执行机会过滤
  - 同一 bookmaker 提供 2+ legs 标记 warning
  - 开赛时间未知或已开始标记 warning/suspicious
  - 历史记录中超过 10% 的旧信号显示 suspicious 标记
- 左侧二级展示 Markets Covered，只作为策略来源/数据覆盖说明：
  - H2H / 1X2
  - Totals
  - Spreads
  - Asian Handicap
  - Totals Middle
  - BTTS（disabled / not requested）
  - Double Chance（disabled / not requested）
  - Draw No Bet（disabled / not requested）
- 主页面为策略综合信息面板：
  - Surebets
  - Near Arbitrage
  - Middle
  - Info Gap
  - Multi-Market
  - Market coverage
  - Top signals
- 新增 Product Analytics 产品分析层：
  - 支持 `Today` / `7D` / `All` 一键切换
  - Surebet 按市场拆分：H2H / Totals / AH / Spreads
  - Middle 占比与数量
  - Gap 按 day 归一化展示，例如 `23/day`
  - Module value 排行，用于判断哪些模块真正产生信号
  - `Today` 包含当前 live 信号；`7D` / `All` 基于历史落库记录
- 赔率对比表（最优组合高亮）
- 投注分配计算器（兼容 H2H 与通用 legs 机会）
- 今日统计 + 历史记录

## 5. API/消息结构（前端可用）

实时 payload 已包含：

- `regions`
  - `regions.au`
  - `regions.eu`
  - `regions.uk`
  - `regions.us`
  - `regions.us2`
- `arbitrages`
- `arbitrages_raw`
- `near_arb`
- `info_gap`
- `market_dimensions`
- `middles`
- `filters`
- `all_events`
- `api_remaining`
- `total_events`
- `signal_timing`
  - `first_seen`
  - `active_seconds`
  - `avg_seconds_by_strategy`
  - `median_seconds_by_strategy`
  - `closed_seconds_by_strategy`
  - `sample_limit`
- `/api/config`
  - `donation_url`
- `/api/history?limit=0`
  - 返回全量历史，用于 All 历史统计
- `/api/history/all`
  - 返回全量历史的兼容接口

顶层字段仍保留为 `au` 的兼容输出；新版 Dashboard 使用 `regions` 分桶切换地区。

## 6. 当前已知限制（真实说明）

- The Odds API 的部分扩展玩法是否可用取决于 sport/bookmaker/赛事阶段；当前为节省 API 额度，BTTS / Double Chance / Draw No Bet 不请求
- Betfair 佣金目前使用简化模型做风控，不等同于交易所逐腿精算
- 多维盘口是否出现可套利机会取决于实时市场，不保证每轮都有
- Middle 第一版只覆盖 totals，亚洲盘 middle 还未接入完整半赢/半输/走水结算模型

## 7. 启停命令

- 启动：`python run.py`
- 关闭（端口）：`lsof -ti tcp:8000 | xargs kill`
- 强制关闭残留：`pkill -9 -f '/Users/neilsu/Desktop/Cup/run.py|dashboard.app:app|uvicorn.*dashboard'`

## 8. Docker 发布

- 配置环境变量：`cp .env.example .env`
- 构建并启动：`docker compose up -d --build`
- 查看日志：`docker compose logs -f`
- 停止：`docker compose down`
- 数据持久化：`./data:/app/data`
- 详细说明见：`DEPLOY_DOCKER.md`

## 9. AWS Lightsail 发布

- Lightsail 专用 Compose：`docker-compose.lightsail.yml`
- Caddy 反向代理与自动 HTTPS：`deploy/lightsail/Caddyfile`
- Ubuntu 初始化脚本：`deploy/lightsail/install_server.sh`
- 生产环境变量模板：`deploy/lightsail/.env.lightsail.example`
- 完整发布手册：`DEPLOY_LIGHTSAIL.md`
