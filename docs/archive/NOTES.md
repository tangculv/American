# Project Notes — 美股选股体系

## [2026-03-14] FMP 请求头兼容问题

User-Agent 含非 ASCII 字符导致 FMP API 拒绝请求。

### 解决
改用纯 ASCII 的 User-Agent 字符串。

### Tags
FMP, API, Python, 请求头

---

## [2026-03-14] 高 PE/PB 标的泄漏到 Top3

筛选逻辑未严格过滤高估值标的。

### 解决
在 Top3 排序前增加 PE/PB 上限硬过滤。

### Tags
策略, 筛选, 估值

---

## [2026-03-12] SQLite 优先读取策略

从文件缓存切换到 SQLite 作为第一数据源（latest-result 已 DB 优先）。

### 原因
SQLite 持久化更可靠，支持查询和审计。

### Tags
SQLite, 架构, 数据源

---

## [2026-03-12] ROE 需杜邦分析推算

部分标的缺少直接 ROE 数据，需要从净利率 x 资产周转率 x 权益乘数推算。

### 解决
scoring_engine 中增加杜邦分析 fallback。

### Tags
评分, ROE, 杜邦分析
