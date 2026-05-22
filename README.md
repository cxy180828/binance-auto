# 币安 Alpha 市场自动交易机器人

监控币安 Alpha 市场代币，基于 1 分钟 K 线策略自动交易，支持飞书通知。

## 功能特性

- **1 分钟 K 线涨幅 > 5% + 放量自动买入**：实时扫描所有 Alpha 代币，满足条件即触发买入
- **动态止盈（Trailing Stop）**：涨 5% 激活，回落 2% 卖出，锁定利润
- **时间止损**：3 分钟未涨到位自动平仓，避免资金占用
- **成交量过滤**：需大于前 5 根 K 线平均量的 2 倍，排除虚假突破
- **冷却期**：同一币种 5 分钟内不重复买入
- **黑名单**：连续亏损 2 次自动拉黑，30 分钟后解除
- **手动过滤名单**：可自定义屏蔽特定代币
- **急跌监控推送**：分级预警（黄色警告 -5%，红色警告 -10%）
- **飞书实时通知**：买入/卖出/每日总结/急跌预警
- **SQLite 本地记录**：所有交易数据和利润率完整保存
- **支持模拟盘（Testnet）和实盘切换**

## 详细部署步骤

### 方式一：直接部署到服务器（推荐）

#### 1. 服务器要求

- Linux（推荐 Ubuntu 20.04+）
- Python 3.9+
- 稳定的网络连接（需访问币安 API）

#### 2. Clone 代码

```bash
git clone <your-repo-url> binance-auto
cd binance-auto
```

#### 3. 创建虚拟环境

```bash
python3 -m venv venv
source venv/bin/activate
```

#### 4. 安装依赖

```bash
pip install -r requirements.txt
```

#### 5. 复制配置文件并编辑

```bash
cp config.yaml.example config.yaml
vim config.yaml
```

#### 6. 获取币安 Testnet API Key

1. 前往 [币安测试网](https://testnet.binance.vision/)
2. 使用 GitHub 账号登录
3. 点击 "Generate HMAC_SHA256 Key"
4. 将生成的 API Key 和 Secret 填入 `config.yaml` 的 `binance` 部分

```yaml
binance:
  api_key: "你的_testnet_api_key"
  secret: "你的_testnet_secret"
  testnet: true
```

#### 7. 创建飞书机器人

1. 打开飞书，进入目标群聊
2. 点击群设置 -> 群机器人 -> 添加机器人
3. 选择 "自定义机器人"
4. 复制 Webhook 地址
5. 将 Webhook 地址填入 `config.yaml` 的 `feishu.webhook_url` 字段

```yaml
feishu:
  webhook_url: "https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx"
```

#### 8. 测试配置

```bash
python3 main.py --check
```

如果输出显示配置验证通过，说明配置正确。

#### 9. 启动机器人

```bash
python3 main.py
```

#### 10. 使用 systemd 设置开机自启

创建服务文件：

```bash
sudo vim /etc/systemd/system/binance-bot.service
```

写入以下内容：

```ini
[Unit]
Description=Binance Alpha Trading Bot
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/path/to/binance-auto
ExecStart=/path/to/binance-auto/venv/bin/python3 main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

启用并启动服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable binance-bot
sudo systemctl start binance-bot
```

#### 11. 查看日志

```bash
# 查看 systemd 服务日志
sudo journalctl -u binance-bot -f

# 查看应用日志文件
tail -f logs/trading.log
```

### 方式二：Docker 部署

#### Dockerfile 示例

```dockerfile
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python3", "main.py"]
```

#### docker-compose.yaml 示例

```yaml
version: "3.8"

services:
  trading-bot:
    build: .
    container_name: binance-bot
    restart: always
    volumes:
      - ./config.yaml:/app/config.yaml
      - ./data:/app/data
      - ./logs:/app/logs
    environment:
      - TZ=Asia/Shanghai
```

启动命令：

```bash
docker-compose up -d
```

查看日志：

```bash
docker-compose logs -f trading-bot
```

## 配置说明

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `binance.api_key` | - | 币安 API Key |
| `binance.secret` | - | 币安 API Secret |
| `binance.testnet` | `true` | 是否使用测试网 |
| `trading.buy_amount_usdt` | `100` | 每次买入金额（USDT） |
| `trading.price_increase_threshold` | `0.05` | K 线涨幅阈值（5%） |
| `trading.trailing_stop_activation` | `0.05` | 动态止盈激活涨幅（5%） |
| `trading.trailing_stop_drop` | `0.02` | 动态止盈回落卖出阈值（2%） |
| `trading.time_stop_loss_minutes` | `3` | 时间止损（分钟） |
| `trading.volume_multiplier` | `2.0` | 成交量倍数要求 |
| `trading.cooldown_minutes` | `5` | 冷却期（分钟） |
| `blacklist.consecutive_losses` | `2` | 连续亏损次数触发拉黑 |
| `blacklist.duration_minutes` | `30` | 黑名单持续时间（分钟） |
| `limits.max_daily_loss_usdt` | `500` | 每日最大亏损（USDT） |
| `limits.max_daily_trades` | `50` | 每日最大交易次数 |
| `limits.max_open_positions` | `10` | 最大同时持仓数 |
| `feishu.webhook_url` | `""` | 飞书机器人 Webhook 地址 |
| `filter_list` | `[]` | 手动过滤代币列表 |
| `scan_symbols` | `[]` | 指定监控代币（空则监控全部） |
| `logging.level` | `INFO` | 日志级别 |
| `logging.file` | `logs/trading.log` | 日志文件路径 |
| `daily_summary_time` | `"20:00"` | 每日总结推送时间 |
| `drop_alert.enabled` | `true` | 是否启用急跌监控 |
| `drop_alert.level1_threshold` | `-0.05` | 黄色警告阈值（-5%） |
| `drop_alert.level2_threshold` | `-0.10` | 红色警告阈值（-10%） |
| `drop_alert.feishu_webhook_url` | `""` | 急跌预警单独的飞书 Webhook |

## 使用命令

### 验证配置

```bash
python3 main.py --check
```

### 启动机器人

```bash
python3 main.py
```

### 查看日志

```bash
# 实时查看
tail -f logs/trading.log

# 查看最近100行
tail -n 100 logs/trading.log
```

### 查看交易记录

交易数据保存在 SQLite 数据库中，位于 `data/trades.db`：

```bash
# 使用 sqlite3 命令行工具查看
sqlite3 data/trades.db

# 查看所有交易记录
SELECT * FROM trades ORDER BY timestamp DESC LIMIT 20;

# 查看盈亏汇总
SELECT symbol, COUNT(*) as trades, SUM(pnl) as total_pnl FROM trades GROUP BY symbol;

# 退出
.quit
```

## 常见问题

### Testnet 和实盘的区别

- **Testnet（测试网）**：使用虚拟资金，API 地址为 `testnet.binance.vision`，适合调试策略
- **实盘**：使用真实资金，API 地址为 `api.binance.com`，需要真实的 API Key

Testnet 的行情数据可能与实盘有差异，建议先在测试网验证策略逻辑，再切换到实盘。

### 如何切换到实盘

1. 在 `config.yaml` 中将 `binance.testnet` 设置为 `false`
2. 替换 API Key 和 Secret 为实盘的真实密钥（在 [币安官网](https://www.binance.com/cn/my/settings/api-management) 创建）
3. 确保 API Key 开启了现货交易权限

```yaml
binance:
  api_key: "真实的_api_key"
  secret: "真实的_secret"
  testnet: false
```

> **注意**：切换实盘前请充分测试，建议从小金额开始。

### 飞书没收到通知怎么排查

1. 确认 `config.yaml` 中的 `feishu.webhook_url` 填写正确
2. 确认机器人未被移出群聊
3. 检查日志中是否有飞书推送相关的报错信息
4. 手动测试 Webhook：

```bash
curl -X POST -H "Content-Type: application/json" \
  -d '{"msg_type":"text","content":{"text":"测试消息"}}' \
  "你的webhook地址"
```

5. 如果配置为空字符串，程序会跳过通知（不会报错），请检查是否遗漏配置

### 如何只监控特定代币

在 `config.yaml` 中设置 `scan_symbols` 列表：

```yaml
scan_symbols:
  - "BTCUSDT"
  - "ETHUSDT"
  - "SOLUSDT"
```

留空则监控所有 Alpha 市场代币。

## 免责声明

本项目仅供学习交流使用，不构成任何投资建议。加密货币交易存在极高风险，可能导致全部本金损失。使用本程序进行实盘交易所产生的一切后果由使用者自行承担，开发者不承担任何责任。请在充分了解风险的前提下谨慎操作。
