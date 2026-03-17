# FMP Stock Market Screener API - 完整筛选参数参考

> **创建日期**：2026-03-06
> **版本**：v1.0
> **数据源**：Financial Modeling Prep (FMP) API v3
> **用途**：策略设计参考文档

---

## 一、API基础信息

### 1.1 端点结构

**基础URL**：
```
https://financialmodelingprep.com/api/v3
```

**主要筛选端点**：

| 端点 | 说明 | 示例 |
|------|------|------|
| `/api/v3/screener` | 通用股票筛选器 | 最常用，支持多条件组合 |
| `/api/v3/screener/sector` | 按行业筛选 | Technology, Healthcare等 |
| `/api/v3/screener/industry` | 按子行业筛选 | 更细粒度的行业分类 |
| `/api/v3/screener/country` | 按国家筛选 | US, CN等 |
| `/api/v3/screener/marketcap-more-than` | 市值大于 | 简化版市值筛选 |
| `/api/v3/screener/marketcap-less-than` | 市值小于 | 简化版市值筛选 |

### 1.2 认证方式

**必需参数**：
```
apikey=你的API_KEY
```

**示例**：
```bash
https://financialmodelingprep.com/api/v3/screener?apikey=YOUR_API_KEY&limit=20
```

### 1.3 通用参数

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `apikey` | string | API密钥（必需） | - |
| `limit` | integer | 返回结果数量（最大100） | 10 |
| `page` | integer | 分页页码 | 0 |
| `isActivelyTrading` | boolean | 是否只返回活跃交易股票 | true |
| `isEtf` | boolean | 是否包含ETF | false |
| `isFund` | boolean | 是否包含基金 | false |

---

## 二、市值筛选参数

### 2.1 市值筛选

| 参数名 | 参数值 | 说明 | 用途 |
|--------|--------|------|------|
| `marketCapMoreThan` | 数字 | 市值大于（美元） | 过滤小市值 |
| `marketCapLessThan` | 数字 | 市值小于（美元） | 过滤大市值 |

**示例用法**：

```python
# 市值 > 10亿美元
marketCapMoreThan=1000000000

# 市值 < 1000亿美元
marketCapLessThan=100000000000

# 10亿 < 市值 < 1000亿
marketCapMoreThan=1000000000&marketCapLessThan=100000000000
```

**策略应用**：
- **大股策略**：`marketCapMoreThan=5000000000` (> 50亿)
- **中股策略**：`marketCapMoreThan=1000000000&marketCapLessThan=5000000000` (10-50亿)
- **小股策略**：`marketCapMoreThan=500000000&marketCapLessThan=1000000000` (5-10亿)

### 2.2 专用市值端点

| 端点 | 说明 |
|------|------|
| `/api/v3/screener/marketcap-more-than/{value}` | 市值大于特定值 |
| `/api/v3/screener/marketcap-less-than/{value}` | 市值小于特定值 |

---

## 三、估值筛选参数

### 3.1 PE（市盈率）筛选

| 参数名 | 参数值 | 说明 |
|--------|--------|------|
| `peLowerThan` | 数字 | PE小于（TTM） |
| `peMoreThan` | 数字 | PE大于（TTM） |

**示例**：
```python
# 低估值：PE < 20
peLowerThan=20

# 避免亏损公司：PE > 0（排除负PE）
peMoreThan=0

# 合理估值：0 < PE < 25
peMoreThan=0&peLowerThan=25
```

**策略应用**：
- **价值策略**：`peLowerThan=15` (深度低估)
- **合理估值**：`peMoreThan=0&peLowerThan=25` (0-25)
- **成长价值**：`peMoreThan=15&peLowerThan=30` (15-30)

### 3.2 PB（市净率）筛选

| 参数名 | 参数值 | 说明 |
|--------|--------|------|
| `pbLowerThan` | 数字 | PB小于 |
| `pbMoreThan` | 数字 | PB大于 |

**示例**：
```python
# 低PB：PB < 2
pbLowerThan=2

# 避免高估值：PB < 3.5
pbLowerThan=3.5

# 资产安全：PB > 0.8&pbLowerThan=3
pbMoreThan=0.8&pbLowerThan=3
```

### 3.3 其他估值参数

| 参数名 | 说明 |
|--------|------|
| `dividendMoreThan` | 股息率大于（百分比，如1表示1%） |
| `dividendLessThan` | 股息率小于 |
| `priceMoreThan` | 股价大于（美元） |
| `priceLessThan` | 股价小于（美元） |
| `isPayingDividend` | 是否支付股息（true/false） |

---

## 四、盈利能力筛选参数

### 4.1 ROE（净资产收益率）

| 参数名 | 参数值 | 说明 |
|--------|--------|------|
| `roeMoreThan` | 数字 | ROE大于（小数，如0.15表示15%） |
| `roeLessThan` | 数字 | ROE小于 |

**示例**：
```python
# 高ROE公司：ROE > 15%
roeMoreThan=0.15

# 合理ROE：10% < ROE < 25%
roeMoreThan=0.1&roeLessThan=0.25

# 避免亏损：ROE > 0
roeMoreThan=0
```

### 4.2 盈利指标

| 参数名 | 说明 |
|--------|------|
| `isEarningPositive` | 是否盈利（true/false） |
| `isRevenuePositive` | 是否有正向营收（true/false） |
| `earningsMoreThan` | 每股收益大于（美元） |
| `earningsLessThan` | 每股收益小于 |

---

## 五、财务质量筛选参数

### 5.1 现金流

| 参数名 | 说明 |
|--------|------|
| `isOperatingCashFlowPositive` | 经营现金流是否为正（true/false） |
| `isFreeCashFlowPositive` | 自由现金流是否为正（true/false） |

**示例**：
```python
# 财务质量筛选
isOperatingCashFlowPositive=true&isFreeCashFlowPositive=true
```

### 5.2 增长率

| 参数名 | 参数值 | 说明 |
|--------|--------|------|
| `revenueGrowthGT` | 小数 | 营收增长率大于（如0.1表示10%） |
| `revenueGrowthLT` | 小数 | 营收增长率小于 |
| `netIncomeGrowthGT` | 小数 | 净利润增长率大于 |
| `netIncomeGrowthLT` | 小数 | 净利润增长率小于 |

**示例**：
```python
# 营收增长 > -10%（允许适度下滑）
revenueGrowthGT=-0.10

# 净利润增长 > -15%
netIncomeGrowthGT=-0.15
```

### 5.3 财务安全

| 参数名 | 说明 |
|--------|------|
| `debtToEquityLowerThan` | 负债权益比小于 |
| `isDebtLow` | 负债是否较低（true/false） |

---

## 六、市场情绪与波动参数

### 6.1 价格动量

| 参数名 | 参数值 | 说明 |
|--------|--------|------|
| `priceChangePercentageLowerThan` | 小数 | 价格涨幅小于（负数表示下跌） |
| `priceChangePercentageMoreThan` | 小数 | 价格涨幅大于 |

**示例**：
```python
# 暴跌股：跌幅 > 20%
priceChangePercentageLowerThan=-0.20

# 暴跌区间：-60% < 涨幅 < -10%
priceChangePercentageLowerThan=-0.60&priceChangePercentageMoreThan=-0.10

# 暴跌至-50%
priceChangePercentageLowerThan=-0.50
```

### 6.2 波动率（Beta）

| 参数名 | 参数值 | 说明 |
|--------|--------|------|
| `betaMoreThan` | 小数 | Beta大于 |
| `betaLessThan` | 小数 | Beta小于 |

**示例**：
```python
# 中等波动：0.8 < Beta < 1.5
betaMoreThan=0.8&betaLessThan=1.5

# 低波动（防御）：Beta < 1.0
betaLessThan=1.0

# 高波动（进攻）：Beta > 1.2
betaMoreThan=1.2
```

### 6.3 52周区间

| 参数名 | 参数值 | 说明 |
|--------|--------|------|
| `percentageBelow52WeekHighMoreThan` | 小数 | 低于52周高点的百分比大于 |

**示例**：
```python
# 从高点下跌 > 20%
percentageBelow52WeekHighMoreThan=0.20

# 从高点下跌 > 40%（错杀候选）
percentageBelow52WeekHighMoreThan=0.40
```

---

## 七、流动性筛选参数

### 7.1 成交量

| 参数名 | 参数值 | 说明 |
|--------|--------|------|
| `volumeMoreThan` | 数字 | 成交量大于 |
| `volumeLessThan` | 数字 | 成交量小于 |

**示例**：
```python
# 流动性：成交量 > 100万股
volumeMoreThan=1000000

# 高流动性：成交量 > 1000万股
volumeMoreThan=10000000

# 避免流动性陷阱
volumeMoreThan=500000
```

### 7.2 交易活跃度

| 参数名 | 说明 |
|--------|------|
| `isActivelyTrading` | 是否活跃交易（true/false） |

**用途**：排除停牌、流动性差的股票。

---

## 八、行业与市场参数

### 8.1 行业筛选

| 参数名 | 说明 |
|--------|------|
| `sector` | 行业（Technology, Healthcare, Financials等） |
| `industry` | 子行业（更细分） |

**主要行业列表**：
- Technology（科技）
- Healthcare（医疗）
- Financials（金融）
- Consumer Discretionary（可选消费）
- Consumer Staples（必需消费）
- Industrials（工业）
- Energy（能源）
- Utilities（公用事业）
- Real Estate（房地产）
- Materials（材料）
- Communication Services（通信）

**示例**：
```python
# 科技股
sector=Technology

# 科技 + 医疗
sector=Technology&industry=Software

# 排除金融（需通过多个sector组合）
```

### 8.2 市场与国家

| 参数名 | 说明 |
|--------|------|
| `country` | 国家（US, CN等） |
| `exchange` | 交易所（NYSE, NASDAQ等） |

**示例**：
```python
# 美股
country=US

# 仅纳斯达克
exchange=NASDAQ
```

---

## 九、公司类型筛选参数

### 9.1 排除特定类型

| 参数名 | 参数值 | 说明 |
|--------|--------|------|
| `isEtf` | true/false | 是否包含ETF |
| `isFund` | true/false | 是否包含基金 |
| `isActivelyTrading` | true/false | 是否只返回活跃交易股票 |

**示例**：
```python
# 排除ETF和基金
isEtf=false&isFund=false

# 只看活跃交易股票
isActivelyTrading=true
```

---

## 十、完整策略组合示例

### 10.1 Fallen Angel策略（你的策略）

**筛选目标**：基本面健康 + 被错杀暴跌的股票

**参数组合**：
```bash
https://financialmodelingprep.com/api/v3/screener?\
apikey=YOUR_API_KEY&\
marketCapMoreThan=1000000000&\
peMoreThan=0&peLowerThan=25&\
isEarningPositive=true&\
isOperatingCashFlowPositive=true&\
isFreeCashFlowPositive=true&\
priceChangePercentageLowerThan=-0.20&\
priceChangePercentageMoreThan=-0.60&\
volumeMoreThan=5000000&\
percentageBelow52WeekHighMoreThan=0.20&\
betaMoreThan=0.8&\
betaLessThan=1.5&\
isEtf=false&\
isFund=false&\
isActivelyTrading=true&\
limit=20
```

**含义**：
- 市值 > 10亿美元
- 0 < PE < 25（合理估值）
- 盈利公司
- 经营现金流 > 0
- 自由现金流 > 0
- 暴跌区间：-60% ~ -20%
- 日均成交量 > 500万股
- 从52周高点下跌 > 20%
- Beta：0.8-1.5（中等波动）
- 排除ETF和基金
- 只看活跃交易股票
- 返回20只

### 10.2 低估值价值策略

**参数组合**：
```bash
?apikey=YOUR_API_KEY&\
marketCapMoreThan=2000000000&\
peLowerThan=15&\
pbLowerThan=2&\
roeMoreThan=0.12&\
isPayingDividend=true&\
dividendMoreThan=2&\
isEtf=false&\
limit=20
```

### 10.3 高成长策略

**参数组合**：
```bash
?apikey=YOUR_API_KEY&\
marketCapMoreThan=500000000&\
revenueGrowthGT=0.20&\
netIncomeGrowthGT=0.20&\
roeMoreThan=0.15&\
isEtf=false&\
limit=20
```

---

## 十一、数据字段说明

### 11.1 返回数据示例

```json
{
  "symbol": "AAPL",
  "name": "Apple Inc.",
  "price": 178.50,
  "changesPercentage": -2.50,
  "change": -4.58,
  "dayLow": 177.20,
  "dayHigh": 180.10,
  "yearHigh": 198.23,
  "yearLow": 124.17,
  "marketCap": 2800000000000,
  "priceAvg50": 175.30,
  "priceAvg200": 165.20,
  "volume": 52000000,
  "avgVolume": 48000000,
  "pe": 28.5,
  "peTTM": 27.8,
  "pb": 45.2,
  "roe": 0.156,
  "beta": 1.28,
  "dividendYield": 0.52,
  "isActivelyTrading": true,
  "isEtf": false,
  "isFund": false,
  "sector": "Technology",
  "industry": "Consumer Electronics"
}
```

### 11.2 关键字段

| 字段 | 说明 | 类型 |
|------|------|------|
| `symbol` | 股票代码 | string |
| `name` | 公司名称 | string |
| `price` | 当前价格 | float |
| `changesPercentage` | 涨跌幅（百分比） | float |
| `marketCap` | 市值（美元） | integer |
| `pe` | PE比率 | float |
| `pb` | PB比率 | float |
| `roe` | ROE（小数） | float |
| `beta` | Beta系数 | float |
| `dividendYield` | 股息率（百分比） | float |
| `volume` | 成交量 | integer |
| `avgVolume` | 平均成交量 | integer |
| `yearHigh` | 52周高点 | float |
| `yearLow` | 52周低点 | float |
| `sector` | 行业 | string |
| `industry` | 子行业 | string |

---

## 十二、调用量限制与成本

### 12.1 免费版限制

| 指标 | 免费版 | Plus版 | Premium版 |
|------|--------|---------|-----------|
| 每日调用 | 250次 | 10,000次 | 无限制 |
| 每月调用 | ~7,500次 | ~300,000次 | 无限制 |
| 月费 | $0 | $49.99 | $99.99 |

### 12.2 调用量估算

**Fallen Angel策略（每周）**：
```
Step 1: 筛选调用 = 1次
Step 2: Top 3详细数据 = 3次 × 10次API/只 = 30次
Step 3: 实时监控 = 3只 × 3次/天 × 5天 = 45次

每周总计 = 76次
每月总计 = 304次（远低于7,500次限制）
```

**结论**：免费版完全够用。

---

## 十三、最佳实践

### 13.1 筛选参数优化

**建议**：
1. ✅ 从宽泛筛选开始（减少调用量）
2. ✅ 逐步收紧条件
3. ✅ 使用`limit`控制结果数量（建议10-20）
4. ✅ 优先使用`isActivelyTrading=true`排除垃圾股
5. ✅ 总是排除ETF和基金（`isEtf=false&isFund=false`）

### 13.2 错误处理

**常见错误**：
```python
# 错误：参数格式错误
# 正确：
priceChangePercentageLowerThan=-0.20  # 小数格式

# 错误：市值单位错误
# 正确：
marketCapMoreThan=1000000000  # 美元，不是百万

# 错误：忘记API Key
# 正确：
apikey=YOUR_API_KEY  # 必需参数
```

### 13.3 性能优化

**建议**：
1. ✅ 缓存筛选结果（每周1次）
2. ✅ 分页查询避免超时
3. ✅ 批量获取详细数据（减少调用次数）
4. ✅ 监控调用量（接近限制时预警）

---

## 十四、Python集成示例

### 14.1 基础筛选

```python
import requests

API_KEY = "YOUR_API_KEY"
BASE_URL = "https://financialmodelingprep.com/api/v3"

def fallen_angel_screener(limit=20):
    params = {
        "apikey": API_KEY,
        "marketCapMoreThan": 1000000000,  # > 10亿
        "peMoreThan": 0,
        "peLowerThan": 25,
        "isEarningPositive": "true",
        "priceChangePercentageLowerThan": -0.20,
        "priceChangePercentageMoreThan": -0.60,
        "volumeMoreThan": 5000000,
        "isEtf": "false",
        "isFund": "false",
        "isActivelyTrading": "true",
        "limit": limit
    }

    response = requests.get(f"{BASE_URL}/screener", params=params)
    data = response.json()

    return data

# 使用
candidates = fallen_angel_screener(limit=20)
print(f"找到 {len(candidates)} 只候选股")
```

### 14.2 获取详细数据

```python
def get_stock_details(ticker):
    params = {"apikey": API_KEY}

    # 获取基本数据
    profile = requests.get(f"{BASE_URL}/profile/{ticker}", params=params).json()

    # 获取财务数据
    financials = requests.get(f"{BASE_URL}/income-statement/{ticker}", params=params).json()

    # 获取估值数据
    metrics = requests.get(f"{BASE_URL}/key-metrics-ttm/{ticker}", params=params).json()

    return {
        "profile": profile[0] if profile else None,
        "financials": financials[0] if financials else None,
        "metrics": metrics[0] if metrics else None
    }

# 使用
for ticker in candidates[:3]:  # Top 3
    details = get_stock_details(ticker["symbol"])
    print(f"{ticker['symbol']}: {details['profile']['companyName']}")
```

---

## 十五、总结与快速参考

### 15.1 快速筛选参数表

| 筛选维度 | 参数名 | 推荐值（Fallen Angel） |
|---------|--------|----------------------|
| 市值 | `marketCapMoreThan` | 1000000000 (10亿) |
| PE | `peMoreThan`&`peLowerThan` | 0-25 |
| 盈利 | `isEarningPositive` | true |
| 现金流 | `isOperatingCashFlowPositive` | true |
| 现金流 | `isFreeCashFlowPositive` | true |
| ROE | `roeMoreThan` | 0.12 (12%) |
| 暴跌 | `priceChangePercentageLowerThan` | -0.20 (-20%) |
| 暴跌 | `priceChangePercentageMoreThan` | -0.60 (-60%) |
| 流动性 | `volumeMoreThan` | 5000000 |
| 排除ETF | `isEtf` | false |
| 排除基金 | `isFund` | false |
| 活跃交易 | `isActivelyTrading` | true |
| 结果数量 | `limit` | 20 |

### 15.2 API调用模板

```bash
# 基础模板
https://financialmodelingprep.com/api/v3/screener?apikey=YOUR_API_KEY&limit=20

# Fallen Angel策略（复制即用）
https://financialmodelingprep.com/api/v3/screener?apikey=YOUR_API_KEY&marketCapMoreThan=1000000000&peMoreThan=0&peLowerThan=25&isEarningPositive=true&priceChangePercentageLowerThan=-0.20&priceChangePercentageMoreThan=-0.60&volumeMoreThan=5000000&isEtf=false&isFund=false&isActivelyTrading=true&limit=20
```

---

**文档版本**：v1.0
**最后更新**：2026-03-06
**维护者**：Claude Code Agent
**数据来源**：[Financial Modeling Prep 官方文档](https://site.financialmodelingprep.com/developer/docs)
