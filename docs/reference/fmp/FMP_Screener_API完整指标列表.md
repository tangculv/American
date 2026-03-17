# FMP Stock Screener API 完整指标列表

**文档版本**: v1.0
**最后更新**: 2026-03-06
**适用场景**: 美股选股策略设计参考

---

## 📋 文档说明

本文档基于 Financial Modeling Prep (FMP) Stock Screener API 整理了**所有支持的筛选指标**，按类别分类，方便后续策略设计时参考。

**官方文档参考**：
- [FMP Financial Ratios API](https://site.financialmodelingprep.com/developer/docs/financial-ratios-api/)
- [FMP Stock Screener API](https://site.financialmodelingprep.com/developer/docs/stable/search-company-screener)

---

## 🔧 参数命名规则

### 基本规则

```
指标名 + MoreThan   = 大于
指标名 + LowerThan  = 小于
```

**示例**：
- `peRatioMoreThan=15`   → PE > 15
- `peRatioLowerThan=25`   → PE < 25
- `roeRatioMoreThan=0.15` → ROE > 15%

---

## 📊 完整指标分类列表

### 1. 估值指标 (Valuation Ratios)

| 参数名 | 中文名 | 说明 | 推荐范围 | 筛选示例 |
|--------|--------|------|----------|----------|
| `peRatioMoreThan` | 市盈率大于 | 价格/每股收益 | > 8 (避免过度低估) | `peRatioMoreThan=8` |
| `peRatioLowerThan` | 市盈率小于 | 价格/每股收益 | < 30 (避免高估值) | `peRatioLowerThan=25` |
| `pbRatioMoreThan` | 市净率大于 | 价格/每股净资产 | > 1 (避免严重破净) | `pbRatioMoreThan=1.2` |
| `pbRatioLowerThan` | 市净率小于 | 价格/每股净资产 | < 5 (避免高价) | `pbRatioLowerThan=3.5` |
| `priceToSalesRatioMoreThan` | 市销率大于 | 价格/每股营收 | > 0.5 | `priceToSalesRatioMoreThan=0.5` |
| `priceToSalesRatioLowerThan` | 市销率小于 | 价格/每股营收 | < 10 | `priceToSalesRatioLowerThan=8` |
| `pegRatioMoreThan` | PEG比率大于 | PE/增长率 | > 0 | `pegRatioMoreThan=0.5` |
| `pegRatioLowerThan` | PEG比率小于 | PE/增长率 | < 3 | `pegRatioLowerThan=2` |

**使用场景**：
- **低估值策略**：`peRatioLowerThan=15&pbRatioLowerThan=2`
- **合理估值**：`peRatioMoreThan=10&peRatioLowerThan=25&pbRatioLowerThan=3.5`
- **高价值股**：`peRatioMoreThan=15&peRatioLowerThan=30&pbRatioLowerThan=5`

---

### 2. 盈利能力指标 (Profitability Ratios)

| 参数名 | 中文名 | 说明 | 推荐范围 | 筛选示例 |
|--------|--------|------|----------|----------|
| `roeRatioMoreThan` | 净资产收益率大于 | 净利润/净资产 | > 10% | `roeRatioMoreThan=0.10` |
| `roeRatioLowerThan` | 净资产收益率小于 | 净利润/净资产 | < 40% | `roeRatioLowerThan=0.40` |
| `roaRatioMoreThan` | 总资产收益率大于 | 净利润/总资产 | > 5% | `roaRatioMoreThan=0.05` |
| `roaRatioLowerThan` | 总资产收益率小于 | 净利润/总资产 | < 20% | `roaRatioLowerThan=0.20` |
| `grossProfitMarginMoreThan` | 毛利率大于 | 毛利润/营收 | > 30% | `grossProfitMarginMoreThan=0.30` |
| `grossProfitMarginLowerThan` | 毛利率小于 | 毛利润/营收 | < 90% | `grossProfitMarginLowerThan=0.90` |
| `operatingMarginMoreThan` | 营业利润率大于 | 营业利润/营收 | > 10% | `operatingMarginMoreThan=0.10` |
| `operatingMarginLowerThan` | 营业利润率小于 | 营业利润/营收 | < 40% | `operatingMarginLowerThan=0.40` |
| `netProfitMarginMoreThan` | 净利率大于 | 净利润/营收 | > 5% | `netProfitMarginMoreThan=0.05` |
| `netProfitMarginLowerThan` | 净利率小于 | 净利润/营收 | < 30% | `netProfitMarginLowerThan=0.30` |
| `returnOnInvestedCapitalMoreThan` | 投入资本回报率大于 | NOPAT/投入资本 | > 10% | `returnOnInvestedCapitalMoreThan=0.10` |
| `returnOnInvestedCapitalLowerThan` | 投入资本回报率小于 | NOPAT/投入资本 | < 30% | `returnOnInvestedCapitalLowerThan=0.30` |

**使用场景**：
- **高ROE策略**：`roeRatioMoreThan=0.15&roeRatioLowerThan=0.30`
- **高毛利率策略**：`grossProfitMarginMoreThan=0.50`
- **优质盈利**：`netProfitMarginMoreThan=0.15&operatingMarginMoreThan=0.20`

---

### 3. 偿债能力指标 (Solvency & Leverage Ratios)

| 参数名 | 中文名 | 说明 | 推荐范围 | 筛选示例 |
|--------|--------|------|----------|----------|
| `debtToEquityRatioMoreThan` | 资产负债率大于 | 总负债/净资产 | > 0 | `debtToEquityRatioMoreThan=0.5` |
| `debtToEquityRatioLowerThan` | 资产负债率小于 | 总负债/净资产 | < 2 | `debtToEquityRatioLowerThan=1.5` |
| `currentRatioMoreThan` | 流动比率大于 | 流动资产/流动负债 | > 1 | `currentRatioMoreThan=1.2` |
| `currentRatioLowerThan` | 流动比率小于 | 流动资产/流动负债 | < 5 | `currentRatioLowerThan=4` |
| `quickRatioMoreThan` | 速动比率大于 | (流动资产-存货)/流动负债 | > 0.8 | `quickRatioMoreThan=0.8` |
| `quickRatioLowerThan` | 速动比率小于 | (流动资产-存货)/流动负债 | < 3 | `quickRatioLowerThan=3` |
| `interestCoverageRatioMoreThan` | 利息保障倍数大于 | EBIT/利息支出 | > 3 | `interestCoverageRatioMoreThan=3` |
| `interestCoverageRatioLowerThan` | 利息保障倍数小于 | EBIT/利息支出 | < 20 | `interestCoverageRatioLowerThan=20` |

**使用场景**：
- **低负债策略**：`debtToEquityRatioLowerThan=1`
- **稳健财务**：`debtToEquityRatioLowerThan=1.5&currentRatioMoreThan=1.5`
- **安全边际**：`interestCoverageRatioMoreThan=5&quickRatioMoreThan=1`

---

### 4. 成长性指标 (Growth Ratios)

| 参数名 | 中文名 | 说明 | 推荐范围 | 筛选示例 |
|--------|--------|------|----------|----------|
| `revenueGrowthRateMoreThan` | 营收增长率大于 | 同比营收增长 | > 0% | `revenueGrowthRateMoreThan=0.10` |
| `revenueGrowthRateLowerThan` | 营收增长率小于 | 同比营收增长 | < 100% | `revenueGrowthRateLowerThan=0.50` |
| `netIncomeGrowthRateMoreThan` | 净利润增长率大于 | 同比净利润增长 | > 0% | `netIncomeGrowthRateMoreThan=0.15` |
| `netIncomeGrowthRateLowerThan` | 净利润增长率小于 | 同比净利润增长 | < 100% | `netIncomeGrowthRateLowerThan=0.80` |
| `operatingIncomeGrowthRateMoreThan` | 营业利润增长率大于 | 同比营业利润增长 | > 5% | `operatingIncomeGrowthRateMoreThan=0.10` |
| `operatingIncomeGrowthRateLowerThan` | 营业利润增长率小于 | 同比营业利润增长 | < 100% | `operatingIncomeGrowthRateLowerThan=0.80` |
| `earningsPerShareGrowthRateMoreThan` | 每股收益增长率大于 | 同比EPS增长 | > 5% | `earningsPerShareGrowthRateMoreThan=0.10` |
| `earningsPerShareGrowthRateLowerThan` | 每股收益增长率小于 | 同比EPS增长 | < 100% | `earningsPerShareGrowthRateLowerThan=0.80` |

**使用场景**：
- **高成长策略**：`revenueGrowthRateMoreThan=0.20&netIncomeGrowthRateMoreThan=0.25`
- **稳健成长**：`revenueGrowthRateMoreThan=0.10&netIncomeGrowthRateMoreThan=0.15`
- **超高速增长**：`revenueGrowthRateMoreThan=0.50&earningsPerShareGrowthRateMoreThan=0.50`

---

### 5. 运营效率指标 (Efficiency Ratios)

| 参数名 | 中文名 | 说明 | 推荐范围 | 筛选示例 |
|--------|--------|------|----------|----------|
| `assetTurnoverRatioMoreThan` | 资产周转率大于 | 营收/总资产 | > 0.5 | `assetTurnoverRatioMoreThan=0.8` |
| `assetTurnoverRatioLowerThan` | 资产周转率小于 | 营收/总资产 | < 3 | `assetTurnoverRatioLowerThan=2.5` |
| `inventoryTurnoverRatioMoreThan` | 存货周转率大于 | 销售成本/存货 | > 2 | `inventoryTurnoverRatioMoreThan=5` |
| `inventoryTurnoverRatioLowerThan` | 存货周转率小于 | 销售成本/存货 | < 20 | `inventoryTurnoverRatioLowerThan=15` |
| `receivablesTurnoverRatioMoreThan` | 应收账款周转率大于 | 营收/应收账款 | > 2 | `receivablesTurnoverRatioMoreThan=5` |
| `receivablesTurnoverRatioLowerThan` | 应收账款周转率小于 | 营收/应收账款 | < 20 | `receivablesTurnoverRatioLowerThan=15` |

**使用场景**：
- **高周转策略**：`assetTurnoverRatioMoreThan=1&inventoryTurnoverRatioMoreThan=8`
- **低库存策略**：`inventoryTurnoverRatioMoreThan=10`

---

### 6. 现金流指标 (Cash Flow Ratios)

| 参数名 | 中文名 | 说明 | 推荐范围 | 筛选示例 |
|--------|--------|------|----------|----------|
| `freeCashFlowYieldMoreThan` | 自由现金流收益率大于 | FCF/市值 | > 2% | `freeCashFlowYieldMoreThan=0.02` |
| `freeCashFlowYieldLowerThan` | 自由现金流收益率小于 | FCF/市值 | < 15% | `freeCashFlowYieldLowerThan=0.10` |
| `operatingCashFlowYieldMoreThan` | 经营现金流收益率大于 | OCF/市值 | > 3% | `operatingCashFlowYieldMoreThan=0.03` |
| `operatingCashFlowYieldLowerThan` | 经营现金流收益率小于 | OCF/市值 | < 20% | `operatingCashFlowYieldLowerThan=0.15` |
| `dividendPayoutRatioMoreThan` | 股息支付率大于 | 股息/净利润 | > 0 | `dividendPayoutRatioMoreThan=0.3` |
| `dividendPayoutRatioLowerThan` | 股息支付率小于 | 股息/净利润 | < 1 | `dividendPayoutRatioLowerThan=0.7` |

**使用场景**：
- **高现金流策略**：`freeCashFlowYieldMoreThan=0.05&operatingCashFlowYieldMoreThan=0.08`
- **稳健分红**：`dividendPayoutRatioLowerThan=0.6&dividendYieldMoreThan=0.03`

---

### 7. 市场指标 (Market Metrics)

| 参数名 | 中文名 | 说明 | 推荐范围 | 筛选示例 |
|--------|--------|------|----------|----------|
| `marketCapMoreThan` | 市值大于 | 总市值 | > 5亿美元 | `marketCapMoreThan=500000000` |
| `marketCapLowerThan` | 市值小于 | 总市值 | < 1000亿美元 | `marketCapLowerThan=100000000000` |
| `priceMoreThan` | 价格大于 | 当前股价 | > 5美元 | `priceMoreThan=5` |
| `priceLowerThan` | 价格小于 | 当前股价 | < 500美元 | `priceLowerThan=200` |
| `volumeMoreThan` | 成交量大于 | 日均成交量 | > 100万 | `volumeMoreThan=1000000` |
| `volumeLowerThan` | 成交量小于 | 日均成交量 | < 1亿 | `volumeLowerThan=50000000` |
| `betaMoreThan` | Beta值大于 | 相对市场波动 | > 0.5 | `betaMoreThan=0.5` |
| `betaLowerThan` | Beta值小于 | 相对市场波动 | < 2.5 | `betaLowerThan=2` |
| `dividendYieldMoreThan` | 股息率大于 | 年化股息/股价 | > 1% | `dividendYieldMoreThan=0.01` |
| `dividendYieldLowerThan` | 股息率小于 | 年化股息/股价 | < 10% | `dividendYieldLowerThan=0.08` |

**使用场景**：
- **大盘股**：`marketCapMoreThan=10000000000`（>100亿）
- **中盘股**：`marketCapMoreThan=2000000000&marketCapLowerThan=10000000000`（20-100亿）
- **小盘股**：`marketCapMoreThan=500000000&marketCapLowerThan=2000000000`（5-20亿）
- **高流动性**：`volumeMoreThan=5000000&betaLowerThan=1.5`

---

### 8. 分类过滤参数 (Classification Filters)

| 参数名 | 类型 | 说明 | 示例值 |
|--------|------|------|--------|
| `sector` | String | 行业分类 | "Technology" |
| `industry` | String | 子行业分类 | "Software" |
| `exchange` | String | 交易所 | "NASDAQ" |
| `country` | String | 国家代码 | "US" |
| `isEtf` | Boolean | 是否ETF | false |
| `isFund` | Boolean | 是否基金 | false |
| `isActivelyTrading` | Boolean | 是否活跃交易 | true |
| `limit` | Integer | 返回数量 | 20 |
| `offset` | Integer | 分页偏移 | 0 |

#### 支持的行业 (Sector)

| 行业英文名 | 中文名 |
|-----------|--------|
| Technology | 科技 |
| Financial Services | 金融服务 |
| Healthcare | 医疗保健 |
| Consumer Cyclical | 非必需消费品 |
| Communication Services | 通信服务 |
| Industrials | 工业 |
| Consumer Defensive | 必需消费品 |
| Energy | 能源 |
| Utilities | 公用事业 |
| Real Estate | 房地产 |
| Basic Materials | 基础材料 |

#### 支持的交易所 (Exchange)

| 交易所代码 | 中文名 |
|-----------|--------|
| NASDAQ | 纳斯达克 |
| NYSE | 纽约证券交易所 |
| AMEX | 美国证券交易所 |
| TSX | 多伦多证券交易所 |
| EURONEXT | 泛欧交易所 |
| LSE | 伦敦证券交易所 |

---

## 🎯 实战策略模板

### 策略1：优质成长股

```bash
curl "https://site.financialmodelingprep.com/api/v3/stock-screener?\
apikey=YOUR_API_KEY&\
revenueGrowthRateMoreThan=0.20&\
netIncomeGrowthRateMoreThan=0.25&\
roeRatioMoreThan=0.15&\
debtToEquityRatioLowerThan=1.5&\
marketCapMoreThan=500000000&\
limit=20"
```

**特点**：高成长、高ROE、低负债

---

### 策略2：价值股

```bash
curl "https://site.financialmodelingprep.com/api/v3/stock-screener?\
apikey=YOUR_API_KEY&\
peRatioLowerThan=15&\
pbRatioLowerThan=2&\
roeRatioMoreThan=0.10&\
dividendYieldMoreThan=0.03&\
marketCapMoreThan=2000000000&\
limit=20"
```

**特点**：低估值、稳定盈利、分红

---

### 策略3：高现金流

```bash
curl "https://site.financialmodelingprep.com/api/v3/stock-screener?\
apikey=YOUR_API_KEY&\
freeCashFlowYieldMoreThan=0.05&\
operatingCashFlowYieldMoreThan=0.08&\
debtToEquityRatioLowerThan=1&\
roeRatioMoreThan=0.12&\
limit=20"
```

**特点**：高现金流、低负债、稳健盈利

---

### 策略4：高股息

```bash
curl "https://site.financialmodelingprep.com/api/v3/stock-screener?\
apikey=YOUR_API_KEY&\
dividendYieldMoreThan=0.04&\
dividendPayoutRatioLowerThan=0.6&\
debtToEquityRatioLowerThan=1.5&\
currentRatioMoreThan=1.5&\
marketCapMoreThan=5000000000&\
limit=20"
```

**特点**：高股息、稳健财务、大盘股

---

### 策略5：高ROE

```bash
curl "https://site.financialmodelingprep.com/api/v3/stock-screener?\
apikey=YOUR_API_KEY&\
roeRatioMoreThan=0.20&\
roeRatioLowerThan=0.35&\
netProfitMarginMoreThan=0.10&\
debtToEquityRatioLowerThan=1.2&\
limit=20"
```

**特点**：超ROE、高利润率、低负债

---

## 📊 指标组合建议

### 成长股组合
```
revenueGrowthRateMoreThan=0.15
netIncomeGrowthRateMoreThan=0.20
roeRatioMoreThan=0.12
debtToEquityRatioLowerThan=1.5
```

### 价值股组合
```
peRatioLowerThan=15
pbRatioLowerThan=2
roeRatioMoreThan=0.10
dividendYieldMoreThan=0.02
```

### 质量股组合
```
roeRatioMoreThan=0.15
netProfitMarginMoreThan=0.10
debtToEquityRatioLowerThan=1
currentRatioMoreThan=1.5
```

### 高股息组合
```
dividendYieldMoreThan=0.04
dividendPayoutRatioLowerThan=0.7
debtToEquityRatioLowerThan=1.5
currentRatioMoreThan=1.2
```

### 现金流组合
```
freeCashFlowYieldMoreThan=0.04
operatingCashFlowYieldMoreThan=0.06
roeRatioMoreThan=0.10
debtToEquityRatioLowerThan=1.2
```

---

## ⚠️ 使用注意事项

### 1. 参数组合限制
- ❌ 不能同时设置 `xxxMoreThan` 和 `xxxLowerThan` 为相反值（如 `peRatioMoreThan=30&peRatioLowerThan=25`）
- ✅ 应该设置合理的范围（如 `peRatioMoreThan=10&peRatioLowerThan=25`）

### 2. 数据有效性
- ❌ 新上市公司可能缺少历史数据
- ❌ 某些行业的比率可能异常（如金融业的PE估值逻辑不同）
- ✅ 建议结合多个指标综合判断

### 3. 调用量管理
- 免费版：250次/天
- 筛选一次：1次调用
- 获取详细数据：每只股票1-3次调用
- 建议使用PE/PB等筛选减少后续调用量

### 4. 不支持的关键指标

以下指标**需要后续单独计算**：

- ❌ 近1年/近3年涨幅（需要获取历史价格）
- ❌ 52周高低点（需要获取历史价格）
- ❌ EV/EBITDA（需要自己计算）
- ❌ 技术指标（MA、RSI、MACD等）

---

## 🔗 相关API端点

### 筛选后获取详细数据

```bash
# 获取完整财务比率
GET /api/v3/ratios-ttm?symbol=AAPL&apikey=YOUR_API_KEY

# 获取历史价格（计算涨跌幅）
GET /api/v3/historical-price-full?symbol=AAPL&apikey=YOUR_API_KEY

# 获取财报数据
GET /api/v3/income-statement?symbol=AAPL&apikey=YOUR_API_KEY
GET /api/v3/balance-sheet-statement?symbol=AAPL&apikey=YOUR_API_KEY
GET /api/v3/cash-flow-statement?symbol=AAPL&apikey=YOUR_API_KEY

# 获取实时价格
GET /api/v3/quote/AAPL?apikey=YOUR_API_KEY
```

---

## 📚 参考资源

- **FMP官方文档**：https://site.financialmodelingprep.com/developer/docs
- **Financial Ratios API**：https://site.financialmodelingprep.com/developer/docs/financial-ratios-api/
- **Stock Screener API**：https://site.financialmodelingprep.com/developer/docs/stable/search-company-screener
- **定价信息**：https://site.financialmodelingprep.com/developer/docs/pricing

---

**文档版本**：v1.0
**维护者**：美股选股体系
**更新日期**：2026-03-06
**下次审核**：2026-06-06
