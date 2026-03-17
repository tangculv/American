# Perplexity 深度研究模块说明

## 1. 作用定位
Perplexity 是系统中的“深度研究引擎”，负责把候选股/持仓股从基础量化筛选推进到可执行的研究结论层。

## 2. 触发方式
### 自动触发
1. `advance-pipeline --symbol <TICKER>`
   - 生命周期从 `queued_for_research` 推进到 `researched` 时触发。
2. `track --symbol <TICKER>`
   - 持仓跟踪时刷新一次研究，用于风险与催化更新。

### 手动触发
- `python3 -m us_stock_research research --symbol ZM --provider auto --persist`
- 支持参数：
  - `--provider auto|perplexity|derived`
  - `--persist` 是否落库
  - `--show-input` 查看发送给研究引擎的结构化输入
  - `--show-prompt` 查看最终 Prompt

## 3. 哪些股票应该触发
### 必须触发
- 新进入 shortlist 且准备进入深度研究的股票
- 持仓股日常跟踪时需要刷新基本面判断的股票
- 人工重点关注、准备决策的股票

### 优先级建议
- `P0`：人工手动研究、临近交易决策
- `P1`：新入池候选、重大事件后复核
- `P2`：常规回访

### 不建议触发
- 明显不满足基本估值/质量门槛的股票
- 数据缺失严重的股票
- 重复研究窗口过短、且无新增事件的股票

## 4. 提供给 Perplexity 的数据
当前标准输入来自 `build_research_context()`：
- symbol
- company_name
- sector
- exchange
- price
- market_cap
- volume
- ratios（TTM 财务比率）

这些数据源来自：
- FMP `company-screener`
- FMP `ratios-ttm`
- 本地 `stock_master` 作为兜底

## 5. Prompt 标准
Prompt 由两部分组成：
1. 基线研究模板：`workflow/02-Perplexity研究Prompt.md`
2. 系统拼接的结构化约束：
   - 严格 JSON
   - 严格枚举值
   - 风险/催化/多空观点条数限制
   - source_list 数量要求
   - 中文 summary 长度要求

## 6. 返回去向
### 内存返回
`run_deep_research()` 返回 `DerivedResearchAnalysis`

### 数据库存储
- `research_snapshot`
  - 保存 trigger、prompt 版本、raw_response、status
- `research_analysis`
  - 保存结构化 bull/bear/risk/catalyst、recommendation、confidence、source_list 等

### UI 可见
Dashboard Lifecycle 中可看到：
- Prompt Version
- Prompt Template
- Trigger
- Confidence
- Recommendation
- Raw Preview

## 7. 返回标准
要求返回结构必须满足：
- `overall_recommendation ∈ {strong_buy,buy,hold,reduce,sell}`
- `valuation_view ∈ {deep_value,undervalued,attractive,neutral,expensive,overvalued}`
- `impact / severity ∈ {low,medium,high}`
- `timeline ∈ {immediate,near_term,mid_term,long_term}`
- `confidence_score ∈ [0,100]`
- `source_list` 尽量 3-8 条，至少有可落库结果

系统会做归一化；若枚举不规范，则自动映射到标准值。

## 8. 失败与降级
- 若 `research.perplexity.enabled=true` 且配置了 `PERPLEXITY_API_KEY`，优先用 Perplexity
- 若调用失败且 `fallback_to_derived=true`，自动降级为本地 derived research
- 不会阻断主流程

## 9. 现阶段仍需持续增强的点
- 将 provider / raw_response_preview 在 UI 中进一步显式分层展示
- 增加 research freshness / 去重策略
- 增加对 source quality 的评分与告警


## 10. 研究新鲜度与诊断
新增命令：

```bash
python3 -m us_stock_research research-diagnostics
```

输出每个股票最近一次研究的：
- 研究时间
- 触发方式
- 当前状态
- 下次复查时间
- 新鲜度（fresh / aging / stale / missing）
- 是否建议重触发
- 建议原因

默认规则：
- 7 天内：fresh
- 8-14 天：aging
- 超过 14 天：stale
- 已到 next_review_date：建议重触发
- 最新状态不是 completed：建议重触发

## 11. 手动 research 的一致性标准
现在 `research --provider xxx --persist` 会把同一次分析结果直接落库，确保：
- 屏幕输出结果
- 数据库存储结果
- provider / fallback 状态
保持一致。
