# FMP Stock Screener API 参数参考文档

**API版本**: Stable / V3
**最后更新**: 2026-03-06
**适用场景**: 美股选股策略筛选

---

## 📋 API端点

### 稳定版（推荐）
```
GET https://site.financialmodelingprep.com/api/v3/stock-screener?apikey=YOUR_API_KEY&marketCapMoreThan=1000000000&limit=20
```

### V3版（Legacy）
```
GET https://site.financialmodelingprep.com/api/v3/stock-screener?apikey=YOUR_API_KEY&marketCapMoreThan=1000000000&limit=20
```

---

## 🔧 完整参数列表

### 0. 财务比率参数 (Valuation Ratios)

| 参数名 | 类型 | 说明 | 示例值 | 备注 |
|--------|------|------|--------|------|
| `peRatioMoreThan` | Number | 市盈率大于 | 15 | PE > 15 |
| `peRatioLowerThan` | Number | 市盈率小于 | 25 | PE < 25 |
| `pbRatioMoreThan` | Number | 市净率大于 | 1.5 | PB > 1.5 |
| `pbRatioLowerThan` | Number | 市净率小于 | 5 | PB < 5 |

**使用场景**：
- 低估值策略：`peRatioLowerThan=15&pbRatioLowerThan=2`
- 合理估值：`peRatioMoreThan=10&peRatioLowerThan=25&pbRatioLowerThan=3.5`
- 高价值股：`peRatioMoreThan=8&peRatioLowerThan=20&pbRatioLowerThan=3`

---

### 1. 市值参数 (Market Cap)

| 参数名 | 类型 | 说明 | 示例值 | 对应美元 |
|--------|------|------|--------|----------|
| `marketCapMoreThan` | Number | 市值大于 | 1000000000 | >10亿美元 |
| `marketCapLowerThan` | Number | 市值小于 | 100000000000 | <1000亿美元 |

**使用场景**：
- 大盘股：`marketCapMoreThan=10000000000`（>100亿）
- 中盘股：`marketCapMoreThan=2000000000&marketCapLowerThan=10000000000`（20-100亿）
- 小盘股：`marketCapMoreThan=500000000&marketCapLowerThan=2000000000`（5-20亿）

---

### 2. 价格参数 (Price)

| 参数名 | 类型 | 说明 | 示例值 | 备注 |
|--------|------|------|--------|------|
| `priceMoreThan` | Number | 价格大于 | 10 | 过滤低价股 |
| `priceLowerThan` | Number | 价格小于 | 1000 | 过滤高价股 |

**使用场景**：
- 避免仙股：`priceMoreThan=5`（价格>5美元）
- 避免超高价：`priceLowerThan=500`（价格<500美元）

---

### 3. 成交量参数 (Volume)

| 参数名 | 类型 | 说明 | 示例值 | 备注 |
|--------|------|------|--------|------|
| `volumeMoreThan` | Number | 成交量大于 | 1000000 | 日均成交量 |
| `volumeLowerThan` | Number | 成交量小于 | 100000000 | 避免异常高量 |

**使用场景**：
- 流动性筛选：`volumeMoreThan=1000000`（日均成交量>100万股）
- 避免异动：`volumeLowerThan=100000000`（成交量<1亿股）

---

### 4. Beta参数 (Risk)

| 参数名 | 类型 | 说明 | 示例值 | 备注 |
|--------|------|------|--------|------|
| `betaMoreThan` | Number | Beta值大于 | 0.5 | 避免防御性股票 |
| `betaLowerThan` | Number | Beta值小于 | 2.0 | 避免过度波动 |

**使用场景**：
- 防御性策略：`betaLowerThan=1.0`（Beta<1）
- 进攻性策略：`betaMoreThan=1.2`（Beta>1.2）
- 平衡策略：`betaMoreThan=0.8&betaLowerThan=1.5`（0.8-1.5）

---

### 5. 股息参数 (Dividend)

| 参数名 | 类型 | 说明 | 示例值 | 备注 |
|--------|------|------|--------|------|
| `dividendMoreThan` | Number | 股息率大于 | 0.01 | >1% |
| `dividendLowerThan` | Number | 股息率小于 | 0.05 | <5% |

**使用场景**：
- 高股息策略：`dividendMoreThan=0.04`（>4%）
- 成长股筛选：`dividendLowerThan=0.01`（<1%或不派息）

---

### 6. 行业/交易所参数 (Sector/Exchange)

| 参数名 | 类型 | 说明 | 示例值 | 备注 |
|--------|------|------|--------|------|
| `sector` | String | 行业筛选 | "Technology" | 见下方行业列表 |
| `industry` | String | 子行业筛选 | "Software" | 见下方子行业列表 |
| `exchange` | String | 交易所筛选 | "NASDAQ" | 见下方交易所列表 |
| `country` | String | 国家筛选 | "US" | 国家代码 |

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

---

### 7. 类型过滤参数 (Type Filter)

| 参数名 | 类型 | 说明 | 示例值 | 备注 |
|--------|------|------|--------|------|
| `isEtf` | Boolean | 是否ETF | false | 排除ETF |
| `isFund` | Boolean | 是否基金 | false | 排除基金 |
| `isActivelyTrading` | Boolean | 是否活跃交易 | true | 只选活跃股 |

**使用场景**：
- 只选个股：`isEtf=false&isFund=false`
- 筛选ETF：`isEtf=true`

---

### 8. 分页参数 (Pagination)

| 参数名 | 类型 | 说明 | 示例值 | 备注 |
|--------|------|------|--------|------|
| `limit` | Integer | 返回结果数量 | 20 | 默认20 |
| `offset` | Integer | 偏移量 | 0 | 用于分页 |

**使用场景**：
- 获取前20只：`limit=20`
- 分页获取：`limit=20&offset=20`（获取21-40只）

---

## 🎯 实战示例

### 示例1：基本筛选（市值+行业+交易所）

**目标**：市值>10亿美元、科技股、纳斯达克

```bash
curl "https://site.financialmodelingprep.com/api/v3/stock-screener?\
apikey=YOUR_API_KEY&\
marketCapMoreThan=1000000000&\
sector=Technology&\
exchange=NASDAQ&\
limit=20"
```

---

### 示例1.5：低估值科技股筛选

**目标**：市值>10亿、PE<25、PB<3.5、科技股

```bash
curl "https://site.financialmodelingprep.com/api/v3/stock-screener?\
apikey=YOUR_API_KEY&\
marketCapMoreThan=1000000000&\
peRatioLowerThan=25&\
pbRatioLowerThan=3.5&\
sector=Technology&\
limit=20"
```

---

### 示例2：Fallen Angel策略筛选

**目标**：市值>5亿、PE<25、PB<3.5、流动性>100万

```bash
curl "https://site.financialmodelingprep.com/api/v3/stock-screener?\
apikey=YOUR_API_KEY&\
marketCapMoreThan=500000000&\
peRatioLowerThan=25&\
pbRatioLowerThan=3.5&\
volumeMoreThan=1000000&\
sector=Technology&\
exchange=NASDAQ&\
limit=20"
```

> 注意：FMP API不支持直接筛选"近1年跌幅"，需要先筛选候选股，再单独计算跌幅

**完整流程**：
```bash
# 步骤1：粗筛（市值+PE+PB+流动性）
筛选 → 20-50只候选股

# 步骤2：获取历史价格，计算近1年跌幅
for ticker in candidates:
  curl ".../historical-price-full?symbol={ticker}"
  计算: (当前价格 - 52周前价格) / 52周前价格

# 步骤3：过滤跌幅在-60%到-10%之间的股票

# 步骤4：进一步获取ROE、现金流等数据深度分析
```

---

### 示例3：高股息策略

**目标**：股息率>4%、市值>50亿、防御性行业

```bash
curl "https://site.financialmodelingprep.com/api/v3/stock-screener?\
apikey=YOUR_API_KEY&\
dividendMoreThan=0.04&\
marketCapMoreThan=5000000000&\
isEtf=false&\
isFund=false&\
limit=20"
```

---

### 示例4：成长股策略

**目标**：市值>10亿、高Beta（进攻性）、科技/医疗

```bash
curl "https://site.financialmodelingprep.com/api/v3/stock-screener?\
apikey=YOUR_API_KEY&\
marketCapMoreThan=1000000000&\
betaMoreThan=1.2&\
sector=Technology&\
limit=20"
```

---

## 📊 调用量规划

### 免费版 (Starter Plan)
- **限制**：250次/天
- **月可用**：~7,500次

### 典型用量（每周筛选）

**方案A：使用PE/PB筛选（推荐）**

| 操作 | 单次调用 | 每周 | 每月 |
|------|---------|------|------|
| 筛选候选股（含PE/PB） | 1次 | 1次 | 4次 |
| 获取历史价格计算跌幅 | 20只×1次 | 20次 | 80次 |
| 获取ROE/现金流等深度数据 | Top3×5次 | 15次 | 60次 |
| 实时监控 | 10次/天 | 70次 | 300次 |
| **总计** | - | **~106次** | **~444次** |

**方案B：不使用PE/PB筛选**

| 操作 | 单次调用 | 每周 | 每月 |
|------|---------|------|------|
| 筛选候选股（不含PE/PB） | 1次 | 1次 | 4次 |
| 获取PE/PB/ROE等所有数据 | 50只×3次 | 150次 | 600次 |
| 获取历史价格计算跌幅 | 20只×1次 | 20次 | 80次 |
| 实时监控 | 10次/天 | 70次 | 300次 |
| **总计** | - | **~241次** | **~984次** |

**结论**：
- ✅ **推荐使用PE/PB筛选**：444次/月 << 7,500次/月（免费版）
- ⚠️ 不用PE/PB筛选：984次/月仍远低于7,500次/月

---

## ⚠️ 注意事项

### 1. 支持的财务比率参数

**✅ 支持直接筛选的财务指标**：

| 参数名 | 类型 | 说明 | 示例值 | 备注 |
|--------|------|------|--------|------|
| `peRatioMoreThan` | Number | 市盈率大于 | 15 | PE > 15 |
| `peRatioLowerThan` | Number | 市盈率小于 | 25 | PE < 25 |
| `pbRatioMoreThan` | Number | 市净率大于 | 1.5 | PB > 1.5 |
| `pbRatioLowerThan` | Number | 市净率小于 | 5 | PB < 5 |

**使用场景**：
- 低估值策略：`peRatioLowerThan=15&pbRatioLowerThan=2`
- 合理估值：`peRatioMoreThan=10&peRatioLowerThan=25`

---

### 2. 不支持的指标

以下指标**不能直接通过Screener API筛选**，需要后续单独计算：

- ❌ ROE（净资产收益率）
- ❌ ROA（资产收益率）
- ❌ 净利润增长率
- ❌ 营收增长率
- ❌ EV/EBITDA
- ❌ 资产负债率
- ❌ 自由现金流
- ❌ **近1年涨跌幅** ← Fallen Angel策略的核心指标！

**解决方案**：
1. 先用Screener API获取候选股（市值、PE、行业等）
2. 对候选股调用`/api/v3/ratios-ttm`获取ROE/ROA/负债率
3. 对候选股调用`/api/v3/income-statement`获取净利润/营收
4. 对候选股调用`/api/v3/cash-flow-statement`获取自由现金流
5. 对候选股调用`/api/v3/historical-price-full`计算涨跌幅

---

### 2. 分页处理

FMP API单次最多返回 **100-200只股票**，需要分页获取：

```bash
# 第一页（1-20只）
curl "...&limit=20&offset=0"

# 第二页（21-40只）
curl "...&limit=20&offset=20"

# 第三页（41-60只）
curl "...&limit=20&offset=40"
```

---

### 3. API限流

- 免费版：250次/天
- 建议添加重试逻辑（如：失败后等待1秒重试）

---

## 🔗 相关API端点

### 获取详细财务数据（筛选后使用）

```bash
# 获取PE/PB/ROE
GET /api/v3/ratios-ttm?symbol=AAPL&apikey=YOUR_API_KEY

# 获取净利润
GET /api/v3/income-statement?symbol=AAPL&apikey=YOUR_API_KEY

# 获取现金流
GET /api/v3/cash-flow-statement?symbol=AAPL&apikey=YOUR_API_KEY

# 获取历史价格（计算涨跌幅）
GET /api/v3/historical-price-full?symbol=AAPL&apikey=YOUR_API_KEY
```

---

## 📚 参考资源

- **FMP官方文档**：https://site.financialmodelingprep.com/developer/docs
- **API Pricing**：https://site.financialmodelingprep.com/developer/docs/pricing
- **Python SDK**：https://github.com/MehdiZare/fmp-data
- **R包**：https://github.com/kylebarron/financialmodelingprep

---

## 🎯 美股策略应用

### Fallen Angel策略建议参数

```bash
# 步骤1：粗筛（市值+PE+PB+流动性+行业）- 一次调用完成大部分过滤
curl "https://site.financialmodelingprep.com/api/v3/stock-screener?\
apikey=YOUR_API_KEY&\
marketCapMoreThan=500000000&\
peRatioLowerThan=25&\
pbRatioLowerThan=3.5&\
volumeMoreThan=1000000&\
exchange=NASDAQ&\
limit=20"

# 步骤2：获取历史价格计算跌幅（核心指标，无法筛选）
for ticker in candidates:
  curl ".../historical-price-full?symbol={ticker}"
  计算: (当前价格 - 52周前价格) / 52周前价格
  过滤: 跌幅在 -60% 到 -10% 之间

# 步骤3：获取深度财务数据（ROE、现金流等）
for ticker in filtered_candidates:
  curl ".../ratios-ttm?symbol={ticker}"  # ROE, ROA, 负债率
  curl ".../cash-flow-statement?symbol={ticker}"  # 自由现金流
  curl ".../income-statement?symbol={ticker}"  # 净利润
```

---

**文档版本**：v1.1
**维护者**：美股选股体系
**更新日期**：2026-03-06

---

## 📊 FMP Screener筛选能力总结

### ✅ 支持直接筛选的条件（一次调用）

| 类别 | 支持的筛选 | 参数示例 |
|------|-----------|----------|
| **估值** | ✅ PE、PB | `peRatioLowerThan=25&pbRatioLowerThan=3.5` |
| **市值** | ✅ 市值范围 | `marketCapMoreThan=500000000` |
| **流动性** | ✅ 成交量 | `volumeMoreThan=1000000` |
| **价格** | ✅ 价格范围 | `priceMoreThan=5` |
| **风险** | ✅ Beta | `betaMoreThan=0.5&betaLowerThan=2` |
| **股息** | ✅ 股息率 | `dividendMoreThan=0.04` |
| **分类** | ✅ 行业/交易所/国家 | `sector=Technology&exchange=NASDAQ` |
| **类型** | ✅ 排除ETF/基金 | `isEtf=false&isFund=false` |

### ❌ 需要后续单独计算的条件

| 指标 | 需要的API端点 |
|------|--------------|
| **近1年跌幅** | `/api/v3/historical-price-full` |
| **ROE** | `/api/v3/ratios-ttm` |
| **ROA** | `/api/v3/ratios-ttm` |
| **负债率** | `/api/v3/ratios-ttm` |
| **净利润增长率** | `/api/v3/income-statement` |
| **自由现金流** | `/api/v3/cash-flow-statement` |
| **EV/EBITDA** | 需要自己计算 |

---

## 🎯 Fallen Angel策略完整流程

```python
# 步骤1：API筛选（一次性过滤8个条件）
candidates = api.screener(
    marketCapMoreThan=500000000,      # 市值>5亿
    peRatioLowerThan=25,               # PE<25
    pbRatioLowerThan=3.5,              # PB<3.5
    volumeMoreThan=1000000,            # 成交量>100万
    sector="Technology",               # 科技股
    exchange="NASDAQ",                 # 纳斯达克
    isEtf=False,                       # 排除ETF
    isFund=False,                      # 排除基金
    limit=20
)

# 步骤2：计算跌幅（FMP不支持筛选，只能计算）
filtered = []
for stock in candidates:
    price_history = api.get_historical_price(stock.symbol)
    change_1y = calculate_1y_change(price_history)
    if -60 <= change_1y <= -10:  # 跌幅在-60%到-10%之间
        filtered.append(stock)

# 步骤3：深度分析（ROE、现金流等）
for stock in filtered:
    ratios = api.get_ratios_ttm(stock.symbol)
    cash_flow = api.get_cash_flow(stock.symbol)
    # 评分、排序、选Top 3
```
