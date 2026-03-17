# 美股选股体系技术设计文档

## 1. 文档目的

本文件承接 `docs/PRD-BUSINESS.md`（v3），说明为了实现 PRD 中定义的产品能力，技术上如何设计。

原则：
- 技术设计必须逐项承接 PRD，不能出现"PRD 没规定，但实现自由发挥"的关键环节
- 与旧版技术设计的主要差异：移除了 watch/waiting_for_setup/buy_ready 状态机、移除了复盘审批流程、新增买后管理核心模块

---

## 2. 总体设计原则

### 2.1 SQLite 为唯一事实源
- 所有业务事实优先写入 SQLite
- JSON / Markdown 仅做导出或展示副本
- UI / CLI 都从 DB 读取

### 2.2 配置驱动
- 策略、通知、研究、调度由配置和环境变量控制
- 禁止硬编码 API Key
- Prompt 模板必须版本化管理

### 2.3 可回退、可审计
- 外部依赖失败时必须有降级方案，降级必须可追踪
- 关键状态变化必须有事实记录

### 2.4 技术实现必须支撑业务可见性
- 任何关键功能完成后，用户必须能通过 CLI / UI / 飞书感知结果

---

## 3. 系统架构

### 3.1 数据与配置层

| 组件 | 职责 | 当前文件 |
|------|------|---------|
| SQLite DB | 唯一事实源 | `data/stock_research.db` |
| 策略配置 | 筛选策略定义 | `config/strategies/*.yaml` |
| 应用配置 | 运行参数 | `config/app.yaml` |
| Prompt 模板 | 研究提示词 | `workflow/02-Perplexity研究Prompt.md` |
| 环境变量 | API Key 等敏感信息 | `.env` |

### 3.2 外部服务层

| 服务 | 职责 | 当前文件 |
|------|------|---------|
| FMP API | 全市场筛选、行情数据、财报数据 | `fmp_client.py` |
| Perplexity API | 深度研究 | `perplexity_client.py` |
| 飞书 Webhook | 消息通知 | `feishu_sender.py` |
| 飞书文档 API | 研究报告文档生成 | `feishu_doc.py`（新增） |

### 3.3 业务工作流层

| 模块 | 职责 | 当前文件 | 状态 |
|------|------|---------|------|
| 策略筛选 | 全市场筛选 + 初步判断 | `service.py` `scoring_engine.py` | 已有，需适配 |
| 深度研究 | Perplexity 调用 + 结果解析 | `research_engine.py` | 已有，需扩展两层输出 |
| 研究队列 | 去重 + 限额 + 排队 | `research_queue.py` | 已有，需适配新规则 |
| 飞书交付 | 文档生成 + 消息通知 | `feishu_doc.py`（新）`feishu_sender.py` | 需新增文档生成 |
| 买入管理 | 买入录入 + 成本计算 | `portfolio_workflow.py` | 已有，需扩展成本口径 |
| 持仓监控 | 日常数据刷新 | `tracking_workflow.py` | 已有，需重构 |
| 信号引擎 | 风险预警 + 卖出提醒检测 | `alert_engine.py`（新增） | 需新增 |
| 预警管理 | 生命周期 + 升级 + 合并 | `alert_manager.py`（新增） | 需新增 |
| 通知引擎 | 事件处理 + 治理 + 发送 | `event_notifications.py` | 已有，需重构 |
| 技术分析 | MA/RSI/MACD 计算 | `technical_analysis.py` | 已有 |
| 排名生成 | 候选股排序 | `ranking_workflow.py` | 已有 |
| 定时调度 | 定时任务触发 | `schedule.py` `scheduled_job.py` | 已有 |

**移除/冻结的模块**：
- `pipeline_workflow.py`：旧版 buy_ready 状态机 → 移除（PRD 已移除此逻辑）
- `review_workflow.py`：复盘审批 → 冻结（PRD 降级到后续版本）
- `lifecycle/state_machine.py`：旧版生命周期 → 重构为新状态模型

### 3.4 产品入口层

| 入口 | 职责 | 当前文件 |
|------|------|---------|
| CLI | 命令行操作 | `cli.py` |
| Web UI | 网页看板 | `ui_data.py` + Streamlit/Flask |
| 定时任务 | launchd 自动运行 | `scheduled_job.py` |

---

## 4. PRD → 技术模块映射

| PRD 功能 (章节) | 技术模块 | 主要文件 | 入口 |
|----------------|---------|---------|------|
| 3.1 每日发现与研究 | 筛选 + 研究队列 + 研究引擎 | `service.py` `research_queue.py` `research_engine.py` | `run` / `run-and-notify` |
| 3.2 飞书交付 | 飞书文档 + 通知 | `feishu_doc.py` `feishu_sender.py` | 自动（研究完成后） |
| 3.3 买入管理 | 买入录入 + 成本 | `portfolio_workflow.py` | `buy` |
| 3.4 买后管理 | 监控 + 信号 + 预警 + 重研究 | `tracking_workflow.py` `alert_engine.py` `alert_manager.py` | `track` / `monitor` |
| 3.5 网页看板 | UI 数据 | `ui_data.py` | Web UI |
| 3.6 策略配置 | 配置读写 | `config.py` `config_store.py` | Web UI / CLI |
| 3.7 通知体验 | 通知引擎 | `event_notifications.py` | 自动 |
| 附录 A 研究规格 | 研究引擎 | `research_engine.py` `perplexity_client.py` | `research` |

---

## 5. 每日发现与研究链路

### 5.1 主流程（对应 PRD 3.1）

```
定时触发 / 手动触发
    │
    ▼
Step 1: FMP 策略筛选 ──→ 候选股名单入库 (strategy_hit)
    │
    ▼
Step 2: 初步判断 ──→ 评分 + 一句话结论入库 (scoring_breakdown)
    │
    ▼
Step 3: 去重判断 ──→ 分流：复用 / 进入研究队列 / 已忽略跳过
    │
    ▼
Step 4: 研究队列 ──→ 按得分排序，取前15只
    │                   串行/限流调用 Perplexity
    ▼
Step 5: 飞书文档生成 ──→ 每只股票一篇飞书文档
    │
    ▼
Step 6: 飞书汇总通知 ──→ 一条合并通知
```

### 5.2 触发方式实现

```python
# scheduled_job.py
def daily_run():
    """定时自动运行 - 走去重"""
    run_full_pipeline(skip_dedup=False)

# cli.py
def cmd_run():
    """手动运行全流程 - 走去重"""
    run_full_pipeline(skip_dedup=False)

def cmd_research(symbol):
    """手动指定单只 - 不走去重"""
    research_single(symbol, skip_dedup=True)
```

### 5.3 去重判断实现

```python
def should_research(symbol: str, skip_dedup: bool = False) -> tuple[bool, str]:
    """
    返回 (should_research, reason)
    """
    if skip_dedup:
        return True, "manual_override"

    # 查最近研究完成时间（美东时区）
    last_research = db.get_latest_research(symbol)
    if last_research is None:
        return True, "never_researched"

    # 10 个自然日，美东时区日历日
    days_since = (today_et() - last_research.completed_date_et).days
    if days_since > 10:
        return True, "expired"

    # 持仓股显著变化例外
    if is_held(symbol) and has_significant_change(symbol):
        return True, "held_significant_change"

    return False, f"reuse:{last_research.completed_date_et}"
```

### 5.4 研究限额实现

```python
MAX_DAILY_RESEARCH = 15

def build_research_queue(candidates: list[dict]) -> list[dict]:
    """
    按初步判断得分排序，取前 MAX_DAILY_RESEARCH 只
    超出部分标记为"待研究"
    """
    # 排除已忽略
    active = [c for c in candidates if c["user_status"] != "ignored"]

    # 去重后筛选需要研究的
    to_research = [c for c in active if should_research(c["symbol"])[0]]

    # 按得分排序
    to_research.sort(key=lambda x: x["initial_score"], reverse=True)

    # 取前 N 只
    queued = to_research[:MAX_DAILY_RESEARCH]
    overflow = to_research[MAX_DAILY_RESEARCH:]

    # 超出部分入库标记"待研究"
    for c in overflow:
        db.update_research_status(c["symbol"], "pending_next_batch")

    return queued
```

### 5.5 已忽略股票处理

```python
def process_hit(symbol: str, user_status: str):
    """处理策略命中"""
    # 无论什么状态都记录命中
    db.record_strategy_hit(symbol, ...)
    db.increment_hit_count(symbol)

    if user_status == "ignored":
        # 不通知、不研究
        return

    if user_status == "关注中" or user_status == "已买入":
        # 正常流程
        proceed_with_research(symbol)
```

### 5.6 Perplexity 并发控制

```python
import time

RESEARCH_INTERVAL_SECONDS = 5  # 请求间隔，避免限流

async def execute_research_batch(queue: list[dict]):
    results = []
    for item in queue:
        result = await research_engine.execute(item["symbol"])
        results.append(result)
        time.sleep(RESEARCH_INTERVAL_SECONDS)
    return results
```

---

## 6. 深度研究模块

### 6.1 研究输入构建（承接 PRD 附录 A.2）

```python
def build_research_context(stock: dict) -> dict:
    """构建研究输入快照"""
    return {
        "symbol": stock["symbol"].upper(),
        "company_name": stock["company_name"],
        "sector": stock.get("sector"),
        "exchange": stock.get("exchange"),
        "price": stock.get("price"),
        "market_cap": stock.get("market_cap"),
        "volume": stock.get("volume"),
        "ratios": stock.get("ratios", {}),  # 保持对象结构
    }
```

技术约束：
- `symbol` 和 `company_name` 缺失则不执行研究
- 其他字段缺失可继续，标注 `data_completeness`
- 输入快照必须 JSON 序列化后随研究记录保存
- `None` 值允许存在，不允许字符串化

### 6.2 Prompt 设计（承接 PRD 附录 A.6）

Prompt 由三部分拼接：
1. 系统提示词（研究方法论 + 硬性约束 + 输出结构要求）
2. 用户消息（股票代码 + 输入快照 JSON）
3. 结构化 schema hint（JSON Schema 约束）

模板来源：`workflow/02-Perplexity研究Prompt.md`

模板治理：
- 每次研究记录 `prompt_template_id` 和 `prompt_version`
- 模板修改后通过版本号区分历史结果

### 6.3 两层输出设计（承接 PRD 附录 A.7）

Perplexity 返回结果需拆分为两层：

**层 1：飞书文档层**
- 完整 Markdown 报告原文
- 直接用于飞书文档生成
- 保存在 `research_snapshot.raw_response`

**层 2：系统数据层**
- 从报告中提取结构化字段
- 保存在 `research_analysis` 表（需扩展字段）
- 供买后管理信号检测使用

新增提取字段（`research_analysis` 表扩展）：

```sql
-- 核心估值字段
tangible_book_value_per_share REAL,
price_to_tbv REAL,
normalized_eps REAL,
normalized_earnings_yield REAL,
net_debt_to_ebitda REAL,
interest_coverage REAL,
goodwill_pct REAL,
intangible_pct REAL,
tangible_net_asset_positive INTEGER,  -- 0/1/null
safety_margin_source TEXT,            -- assets/cashflow/both/weak

-- 交易参数字段
buy_range_low REAL,
buy_range_high REAL,
max_position_pct REAL,
target_price_conservative REAL,
target_price_base REAL,
target_price_optimistic REAL,
stop_loss_condition TEXT,
add_position_condition TEXT,
reduce_position_condition TEXT,

-- 结论字段
overall_conclusion TEXT,  -- 值得投/不值得投/仅高风险偏好
top_risks_json TEXT,
invalidation_conditions_json TEXT,
three_sentence_summary TEXT,
refinancing_risk TEXT,    -- 低/中/高

-- 元数据
feishu_doc_url TEXT,
```

### 6.4 质量校验（承接 PRD 附录 A.8）

```python
def validate_research_quality(result: dict) -> tuple[str, list[str]]:
    """
    返回 (level, issues)
    level: "pass" / "partial" / "fail"
    """
    issues = []

    # A. 交付门槛（不通过 → 不推送文档）
    if not result.get("summary_table"):
        issues.append("missing_summary_table")
    if not result.get("three_sentence_summary"):
        issues.append("missing_three_sentences")
    if not result.get("bull_thesis") and not result.get("bear_thesis"):
        issues.append("missing_thesis")
    if not result.get("overall_conclusion"):
        issues.append("missing_conclusion")

    gate_fields = ["summary_table", "three_sentence_summary",
                   "bull_thesis", "conclusion", "risks", "valuation"]
    gate_missing = [f for f in gate_fields if not result.get(f)]
    if gate_missing:
        return "fail", issues

    # B. 质量目标（不通过 → 标记"部分内容缺失"）
    quality_fields = ["earnings_bridge", "tangible_nav",
                      "three_scenario_valuation", "trade_plan"]
    quality_missing = [f for f in quality_fields if not result.get(f)]
    if quality_missing:
        issues.extend([f"missing_{f}" for f in quality_missing])
        return "partial", issues

    return "pass", []
```

### 6.5 失败与降级（承接 PRD 附录 A.9）

```
Perplexity 调用
    │
    ├─ 成功 → 校验 → pass → 完整交付
    │                partial → 交付 + 标记"部分内容缺失"
    │                fail → 标记研究失败
    │
    └─ 失败 → 降级研究（fallback）
              │
              ├─ 降级成功 → 校验 → 满足交付门槛 → 降级交付
              │                    不满足 → 标记研究失败
              │
              └─ 降级也失败 → 标记研究失败
```

技术要求：
- `fallback_used` 必须写入结果
- `provider` 必须反映实际提供者
- 原始失败原因保存在 `error_message`
- 降级文档标题加注 `[降级]`

### 6.6 落库设计

每次研究写入两张表：
- `research_snapshot`：输入 + 原始返回 + 元数据 + 状态
- `research_analysis`：结构化提取字段（含新增的估值/交易/结论字段）

---

## 7. 飞书交付模块

### 7.1 飞书文档生成（新增模块）

```python
# feishu_doc.py
class FeishuDocGenerator:
    def create_research_doc(self, symbol: str, report_markdown: str,
                           quality_level: str) -> str:
        """
        创建飞书文档
        返回文档 URL
        """
        title = self._build_title(symbol, quality_level)
        # 调用飞书文档 API
        doc_url = self.feishu_api.create_doc(title, report_markdown)
        return doc_url

    def _build_title(self, symbol: str, quality_level: str) -> str:
        prefix = "[降级] " if quality_level == "fallback" else ""
        return f"{prefix}[{symbol}] {company_name} - 深度研究报告 ({date})"
```

### 7.2 飞书汇总通知

```python
def build_daily_summary(batch_results: list[dict]) -> str:
    """构建每日汇总通知内容"""
    lines = [f"今日命中 {len(batch_results)} 只股票：\n"]

    for r in batch_results:
        status_icon = {"success": "✅", "fallback": "⚠️",
                       "failed": "❌", "reused": "🔄",
                       "pending": "⏳"}[r["status"]]
        line = f"{status_icon} {r['symbol']}: {r['summary']}"
        if r.get("doc_url"):
            line += f" → [查看报告]({r['doc_url']})"
        elif r["status"] == "reused":
            line += f" (复用 {r['reuse_date']} 研究)"
        elif r["status"] == "pending":
            line += " (待研究，已入候选池)"
        lines.append(line)

    return "\n".join(lines)
```

---

## 8. 买入管理模块

### 8.1 买入录入（承接 PRD 3.3）

```python
def record_buy(symbol: str, price: float, quantity: int,
               buy_date: str, reason: str = None):
    """录入买入"""
    # 检查是否在候选池
    stock = db.get_stock(symbol)
    if stock is None:
        # 允许录入未在候选池的股票
        db.create_stock_master(symbol, source="manual_entry", hit_count=0)

    # 写入交易记录
    db.insert_trade_log(symbol, "buy", buy_date, price, quantity, reason)

    # 更新用户状态为"已买入"
    db.update_user_status(symbol, "held")

    # 更新持仓汇总（加权平均成本）
    update_position_summary(symbol)

    # 飞书确认通知
    notify_buy_confirmation(symbol, price, quantity)
```

### 8.2 成本计算（承接 PRD 3.3 成本口径）

```python
def update_position_summary(symbol: str):
    """更新持仓汇总 - 加权平均成本法"""
    buys = db.get_all_buys(symbol)  # 所有买入记录
    sells = db.get_all_sells(symbol)  # 所有卖出记录

    total_bought_shares = sum(b.quantity for b in buys)
    total_bought_cost = sum(b.price * b.quantity for b in buys)
    total_sold_shares = sum(s.quantity for s in sells)

    remaining_shares = total_bought_shares - total_sold_shares
    if remaining_shares <= 0:
        db.update_position(symbol, status="closed")
        return

    avg_cost = total_bought_cost / total_bought_shares
    first_buy_date = min(b.trade_date for b in buys)

    db.update_position(symbol,
        shares=remaining_shares,
        avg_cost=avg_cost,
        first_buy_date=first_buy_date,
        status="open")
```

---

## 9. 买后管理模块（核心）

这是系统最核心的技术模块，承接 PRD 3.4。

### 9.1 架构概览

```
每日定时触发（交易日）
    │
    ▼
持仓监控 (tracking_workflow.py)
    │  刷新价格、技术面
    │
    ▼
信号检测 (alert_engine.py)
    │  检测风险预警 + 卖出提醒
    │
    ▼
预警管理 (alert_manager.py)
    │  生命周期更新 + 升级 + 合并
    │
    ▼
通知引擎 (event_notifications.py)
    │  合并通知 + 发送飞书
    │
    ▼
落库 (alert_event 表)
```

**异常隔离**：`run_daily_monitoring` 的 per-symbol 循环用 `try/except` 包裹整个处理块。任何环节（价格刷新、snapshot 构建、信号检测、预警管理、重研究判断）抛异常时，记录日志并 `continue`，不影响其他持仓的处理。

### 9.2 信号检测引擎（新增 `alert_engine.py`）

```python
class AlertEngine:
    """信号检测引擎 - 承接 PRD 3.4.3 和 3.4.4"""

    def detect_signals(self, symbol: str, snapshot: dict,
                       research: dict, position: dict) -> list[Signal]:
        signals = []
        signals.extend(self._check_risk_warnings(symbol, snapshot, research))
        signals.extend(self._check_sell_reminders(symbol, snapshot, research, position))
        return signals

    def _check_risk_warnings(self, symbol, snapshot, research) -> list[Signal]:
        """风险预警信号检测（关注级）"""
        signals = []

        # 急跌预警：单日跌幅 ≥ 5%
        if snapshot["daily_change_pct"] <= -5.0:
            signals.append(Signal(
                type="急跌预警", level="warning",
                action="重点关注",
                value=snapshot["daily_change_pct"],
                threshold=-5.0))

        # 阶段回撤：从阶段高点回撤 ≥ 15%
        drawdown = self._calc_drawdown(symbol, snapshot["price"])
        if drawdown >= 15.0:
            signals.append(Signal(
                type="阶段回撤", level="warning",
                action="重点关注",
                value=drawdown, threshold=15.0))

        # 基本面恶化
        if research:
            roe_drop = research.get("prev_roe", 0) - research.get("roe", 0)
            if roe_drop >= 5.0:
                signals.append(Signal(
                    type="基本面恶化", level="warning",
                    action="重点关注",
                    detail=f"ROE 下降 {roe_drop:.1f} 个百分点"))

        # 杠杆风险升级
        if research:
            nde = research.get("net_debt_to_ebitda")
            if nde and nde >= 4.0:
                signals.append(Signal(
                    type="杠杆风险升级", level="warning",
                    action="重点关注",
                    value=nde, threshold=4.0))

        # 技术面转弱：50日均线下穿200日均线
        if snapshot.get("ma_50") and snapshot.get("ma_200"):
            if (snapshot["ma_50"] < snapshot["ma_200"] and
                snapshot.get("prev_ma_50", 0) >= snapshot.get("prev_ma_200", 0)):
                signals.append(Signal(
                    type="技术面转弱", level="warning",
                    action="重点关注",
                    detail="50日均线下穿200日均线（死叉）"))

        # 财报临近：≤ 3 个自然日
        days_to_earnings = self._days_to_earnings(symbol)
        if days_to_earnings is not None and days_to_earnings <= 3:
            signals.append(Signal(
                type="财报临近", level="warning",
                action="重点关注",
                detail=f"距财报发布 {days_to_earnings} 天"))

        return signals

    def _check_sell_reminders(self, symbol, snapshot, research, position) -> list[Signal]:
        """卖出提醒信号检测（动作级）"""
        signals = []
        price = snapshot["price"]
        avg_cost = position["avg_cost"]
        return_pct = (price - avg_cost) / avg_cost * 100

        # 止损触发：跌破买入价 8% 或研究中的止损条件
        if return_pct <= -8.0:
            signals.append(Signal(
                type="止损触发", level="action",
                action="考虑止损",
                value=return_pct, threshold=-8.0))

        if research and research.get("stop_loss_condition"):
            if self._evaluate_condition(research["stop_loss_condition"], snapshot):
                signals.append(Signal(
                    type="止损触发", level="action",
                    action="考虑止损",
                    detail=f"触发研究报告止损条件"))

        # 目标价达成
        if research:
            for scenario, field in [("保守", "target_price_conservative"),
                                     ("基准", "target_price_base"),
                                     ("乐观", "target_price_optimistic")]:
                target = research.get(field)
                if target and price >= target:
                    signals.append(Signal(
                        type="目标价达成", level="action",
                        action="考虑止盈",
                        detail=f"{scenario}目标价 ${target:.2f} 已达成"))

        # 收益率达标：≥ 20%
        if return_pct >= 20.0:
            signals.append(Signal(
                type="收益率达标", level="action",
                action="考虑止盈",
                value=return_pct, threshold=20.0))

        # 失效条件触发
        if research and research.get("invalidation_conditions"):
            for cond in research["invalidation_conditions"]:
                if self._evaluate_condition(cond, snapshot):
                    signals.append(Signal(
                        type="失效条件触发", level="action",
                        action="考虑清仓",
                        detail=cond))

        # 持有逻辑失效
        if research and research.get("overall_conclusion") == "不值得投":
            signals.append(Signal(
                type="持有逻辑失效", level="action",
                action="考虑清仓",
                detail="最新研究结论变为不值得投"))

        # 技术顶部信号：RSI ≥ 70 且 50日均线向下拐头
        if (snapshot.get("rsi_14", 0) >= 70 and
            snapshot.get("ma_50_slope", 0) < 0):
            signals.append(Signal(
                type="技术顶部信号", level="action",
                action="考虑减仓",
                detail=f"RSI={snapshot['rsi_14']:.0f}, 50日均线向下拐头"))

        # 估值过高：PE 或 PB ≥ 基准目标价估值 × 1.5
        # 实现略（需要基准估值数据）

        return signals
```

### 9.3 预警生命周期管理（新增 `alert_manager.py`）

**关键定义**：

- **活跃状态** = `triggered` / `notified` / `acknowledged`
- **终态** = `resolved` / `expired` / `historical_reached` / `upgraded`

```python
class AlertManager:
    """预警生命周期管理 - 承接 PRD 3.4.5"""

    # 动作优先级（从高到低）
    ACTION_PRIORITY = {
        "考虑清仓": 6, "考虑止损": 5, "考虑止盈": 4,
        "考虑减仓": 3, "重点关注": 2, "继续持有": 1
    }

    def process_signals(self, symbol: str, new_signals: list[Signal]):
        """处理新检测到的信号"""
        active_alerts = db.get_active_alerts(symbol)

        for signal in new_signals:
            existing = self._find_matching_alert(active_alerts, signal)
            if existing:
                # 重复信号 → 刷新以下字段：
                #   signal_level, action, trigger_value,
                #   trigger_threshold, detail, triggered_at
                self._refresh_alert(existing, signal)
            else:
                self._create_alert(symbol, signal)

        # 检查升级（基于本轮信号结果）
        self._check_upgrades(symbol, new_signals)
        # 检查失效（基于恢复天数）
        self._check_expirations(symbol, new_signals)

    def _create_alert(self, symbol: str, signal: Signal):
        """创建新预警"""
        db.insert_alert_event(
            symbol=symbol,
            signal_type=signal.type,
            signal_level=signal.level,  # warning / action
            action=signal.action,
            status="triggered",
            trigger_value=signal.value,
            trigger_threshold=signal.threshold,
            detail=signal.detail,
            triggered_at=now_et())

    def _check_expirations(self, symbol: str, new_signals: list[Signal]):
        """
        检查预警失效。

        判定口径：本轮 AlertEngine 不再产生同类型信号 → 视为恢复一天。
        MVP 阶段用 (当前日期 - triggered_at) 的自然日差值近似交易日。
        detail 字段保留给业务描述，不用于存储恢复天数。
        """
        # 本轮检测到的信号类型集合
        current_signal_types = {s.type for s in new_signals}

        alerts = db.get_active_alerts(symbol)
        for alert in alerts:
            # 本轮仍被触发 → 不失效（triggered_at 已在 _refresh_alert 中重置）
            if alert.signal_type in current_signal_types:
                continue

            days_since = (now_date() - parse_date(alert.triggered_at)).days

            if alert.signal_level == "warning":
                # 风险预警：恢复正常 3 个交易日自动失效
                if days_since >= EXPIRY_TRADING_DAYS:
                    db.update_alert_status(alert.id, "expired")

            elif alert.signal_level == "action":
                if alert.signal_type in ("目标价达成", "收益率达标", "技术顶部信号"):
                    # 价格类：不满足 3 个交易日降级为"历史触达"
                    if days_since >= EXPIRY_TRADING_DAYS:
                        db.update_alert_status(alert.id, "historical_reached")
                # 条件类（止损/失效/逻辑失效）：不自动失效

    def _check_upgrades(self, symbol: str, new_signals: list[Signal]):
        """
        检查信号升级。

        升级判定：纯粹基于 AlertEngine 本轮信号结果。
        当本轮同时产生"阶段回撤"和"止损触发"信号时，
        将已有的阶段回撤预警标记为 upgraded，
        在新建的止损触发预警中通过 upgrade_from_id 关联。
        AlertManager 不自行读取行情或计算止损线。
        """
        # 本轮是否同时产生了回撤和止损信号
        has_drawdown_signal = any(s.type == "阶段回撤" for s in new_signals)
        has_stop_loss_signal = any(s.type == "止损触发" for s in new_signals)
        if not (has_drawdown_signal and has_stop_loss_signal):
            return

        alerts = db.get_active_alerts(symbol)
        drawdown_alert = self._find_by_type(alerts, "阶段回撤")
        stop_loss_alert = self._find_by_type(alerts, "止损触发")
        if drawdown_alert and stop_loss_alert:
            db.update_alert_status(drawdown_alert.id, "upgraded")
            # 在止损触发预警上记录 upgrade_from_id
            db.update_upgrade_from(stop_loss_alert.id, drawdown_alert.id)

    def merge_for_notification(self, symbol: str) -> dict | None:
        """
        合并同一股票的多个信号为一条通知 - 承接 PRD 3.4.6

        返回结构：
        {
            "symbol": str,
            "top_action": str,
            "signals": [{"type": str, "action": str, "detail": str | None}, ...],
            "signal_count": int
        }
        """
        active = db.get_active_alerts(symbol, status="triggered")
        if not active:
            return None

        # 按动作优先级排序
        active.sort(key=lambda a: self.ACTION_PRIORITY.get(a.action, 0),
                   reverse=True)

        return {
            "symbol": symbol,
            "top_action": active[0].action,  # 最高级别
            "signals": [{"type": a.signal_type, "action": a.action,
                        "detail": a.detail} for a in active],
            "signal_count": len(active)
        }
```

### 9.4 持仓重研究（承接 PRD 3.4.7）

```python
def check_reresearch_trigger(symbol: str, snapshot: dict) -> bool:
    """检查持仓股是否需要重研究"""
    if not is_held(symbol):
        return False

    # 单日价格变动 ≥ 5%
    if abs(snapshot.get("daily_change_pct", 0)) >= 5.0:
        return True

    # 技术面质变
    prev_trend = db.get_prev_trend(symbol)
    curr_trend = snapshot.get("weekly_trend")
    if prev_trend and curr_trend and prev_trend != curr_trend:
        if (prev_trend in ("up",) and curr_trend in ("down",)) or \
           (prev_trend in ("down",) and curr_trend in ("up",)):
            return True

    return False

def execute_reresearch(symbol: str):
    """执行持仓重研究"""
    result = research_engine.execute(symbol, trigger="reresearch")

    if result.quality_level != "fail":
        # 生成新飞书文档（不覆盖旧的）
        doc_url = feishu_doc.create_research_doc(
            symbol, result.markdown, quality_level=result.quality_level,
            title_prefix="重研究")

        # 更新系统数据层（全量覆盖）
        db.update_research_analysis(symbol, result.structured_fields)

        # 检查结论翻转
        prev = db.get_prev_conclusion(symbol)
        if prev == "值得投" and result.conclusion == "不值得投":
            alert_manager.create_alert(symbol, Signal(
                type="持有逻辑失效", level="action",
                action="考虑清仓",
                detail="重研究结论从值得投变为不值得投"))

        # 通知
        notify_reresearch_complete(symbol, doc_url, result)
```

### 9.5 卖出处理（承接 PRD 3.4.9）

```python
def record_sell(symbol: str, price: float, quantity: int,
                sell_date: str, reason: str = None):
    """录入卖出"""
    position = db.get_position(symbol)
    avg_cost = position["avg_cost"]

    # 计算已实现盈亏（加权平均成本法）
    realized_pnl = (price - avg_cost) * quantity

    db.insert_trade_log(symbol, "sell", sell_date, price, quantity, reason)

    remaining = position["shares"] - quantity
    if remaining <= 0:
        # 全部卖出 → 关闭持仓 + 关闭活跃预警
        db.update_position(symbol, status="closed")
        db.close_all_active_alerts(symbol)
        db.update_user_status(symbol, "closed")
    else:
        # 部分卖出 → 更新持仓，预警保留
        db.update_position(symbol, shares=remaining)
```

---

## 10. 通知模块

### 10.1 事件类型（承接 PRD 3.7）

| 事件类型 | 触发时机 | 紧急度 | 合并规则 |
|---------|---------|--------|---------|
| `daily_screening` | 每日筛选完成 | 常规 | 合并为一条 |
| `research_completed` | 研究完成 | 常规 | 逐只 |
| `buy_confirmation` | 买入录入 | 常规 | 逐只 |
| `risk_warning` | 风险预警触发 | 紧急 | 同股同日合并 |
| `sell_reminder` | 卖出提醒触发 | 紧急 | 同股同日合并 |
| `reresearch_completed` | 重研究完成 | 紧急 | 逐只 |
| `system_failure` | 系统运行失败 | 最紧急 | 按失败范围 |

### 10.2 通知治理实现

```python
COOLDOWN_HOURS = 6

def should_send(event: NotificationEvent) -> bool:
    """通知治理判断"""
    # 紧急通知不受限流
    if event.urgency == "urgent":
        # 但同股同类 6 小时冷却仍生效（除非升级）
        last = db.get_last_notification(event.symbol, event.event_type)
        if last and (now() - last.sent_at).hours < COOLDOWN_HOURS:
            if not event.is_upgrade:
                return False
    return True
```

### 10.3 失败通知粒度（承接 PRD 3.7）

```python
def handle_batch_failures(batch_results: list[dict]):
    """处理批次失败通知"""
    total_failure = all(r["status"] == "failed" for r in batch_results)

    if not batch_results:
        # 整个定时任务未启动
        send_system_failure("定时任务未启动")
    elif total_failure:
        # 全批次失败
        send_notification(f"今日命中{len(batch_results)}只，全部研究失败",
                         urgency="critical")
    else:
        # 部分成功 → 合并到汇总通知中标注
        summary = build_daily_summary(batch_results)
        send_notification(summary, urgency="normal")
```

---

## 11. 网页看板

### 11.1 持仓视图数据（承接 PRD 3.5.2）

```python
def get_portfolio_view() -> dict:
    """构建持仓视图数据"""
    positions = db.get_all_open_positions()

    # 分三段
    need_action = []  # 有活跃卖出提醒
    need_attention = []  # 有活跃风险预警
    normal = []

    for pos in positions:
        alerts = db.get_active_alerts(pos.symbol)
        action_alerts = [a for a in alerts if a.signal_level == "action"]
        warning_alerts = [a for a in alerts if a.signal_level == "warning"]

        pos_data = build_position_data(pos, alerts)
        if action_alerts:
            need_action.append(pos_data)
        elif warning_alerts:
            need_attention.append(pos_data)
        else:
            normal.append(pos_data)

    return {
        "summary": {
            "need_action": len(need_action),
            "need_attention": len(need_attention),
            "normal": len(normal),
        },
        "sections": [
            {"label": "需操作", "items": need_action},
            {"label": "需关注", "items": need_attention},
            {"label": "正常", "items": normal},
        ]
    }
```

---

## 12. 数据设计

### 12.1 表结构变更

**保留并扩展的表**：
- `stock_master`：新增 `user_status` 字段（关注中/已忽略/已买入）、`hit_count`、`source`（strategy/manual_entry）
- `strategy_hit`：保持现有结构
- `research_snapshot`：保持现有结构
- `research_analysis`：大幅扩展（见 6.3 节新增字段）
- `technical_snapshot`：保持现有结构
- `scoring_breakdown`：保持现有结构
- `trade_log`：新增 `reason` 字段
- `notification_event`：适配新事件类型

**新增的表**：

```sql
-- 预警事件表（核心新增）
CREATE TABLE IF NOT EXISTS alert_event (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    signal_type TEXT NOT NULL,      -- 急跌预警/阶段回撤/止损触发/...
    signal_level TEXT NOT NULL,     -- warning / action
    action TEXT NOT NULL,           -- 继续持有/重点关注/考虑减仓/...
    status TEXT NOT NULL DEFAULT 'triggered',
        -- triggered / notified / acknowledged / resolved / expired / historical_reached / upgraded
    trigger_value REAL,
    trigger_threshold REAL,
    detail TEXT,
    triggered_at TEXT NOT NULL,
    notified_at TEXT,
    acknowledged_at TEXT,
    resolved_at TEXT,
    expired_at TEXT,
    upgrade_from_id INTEGER,       -- 如果由其他预警升级而来
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 持仓汇总表（核心新增）
CREATE TABLE IF NOT EXISTS position_summary (
    symbol TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'open',  -- open / closed
    total_shares INTEGER NOT NULL DEFAULT 0,
    avg_cost REAL NOT NULL DEFAULT 0,
    first_buy_date TEXT NOT NULL,
    total_invested REAL NOT NULL DEFAULT 0,
    realized_pnl REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 每日持仓快照（承接 PRD 3.4.1）
CREATE TABLE IF NOT EXISTS daily_position_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    snapshot_date TEXT NOT NULL,
    price REAL NOT NULL,
    daily_change_pct REAL,
    unrealized_pnl REAL,
    unrealized_pnl_pct REAL,
    holding_days INTEGER,
    volume INTEGER,
    volume_ratio REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, snapshot_date)
);
```

**冻结的表**（保留但不再写入）：
- `review_log`：复盘审批冻结
- `suggested_change`：复盘建议冻结
- `ranking_snapshot`：暂不在核心流程中使用

### 12.2 用户状态字段

`stock_master.user_status` 取值：

| 值 | 含义 | 转入条件 |
|---|------|---------|
| `watching` | 关注中（默认） | 策略命中时自动创建 |
| `ignored` | 已忽略 | 用户手动标记 |
| `held` | 已买入 | 用户录入买入 |
| `closed` | 已清仓 | 全部卖出后 |

---

## 13. 代码变更计划

### 13.1 新增文件

| 文件 | 职责 | 优先级 |
|------|------|--------|
| `alert_engine.py` | 信号检测引擎 | P0 |
| `alert_manager.py` | 预警生命周期管理 | P0 |
| `feishu_doc.py` | 飞书文档生成 | P1 |
| `position_manager.py` | 持仓管理（成本计算、卖出处理） | P0 |

### 13.2 需重构的文件

| 文件 | 变更内容 | 优先级 |
|------|---------|--------|
| `tracking_workflow.py` | 集成信号检测引擎 | P0 |
| `event_notifications.py` | 适配新事件类型 + 合并规则 | P0 |
| `research_engine.py` | 两层输出 + 质量校验分层 | P1 |
| `research_queue.py` | 15只限额 + 新去重规则 | P1 |
| `portfolio_workflow.py` | 加权平均成本法 + 买入管理 | P1 |
| `models/schema.py` | 新增表 + 扩展字段 | P0 |
| `ui_data.py` | 持仓三段视图 + 个股详情 | P2 |
| `service.py` | 已忽略股票处理 + 流程适配 | P1 |
| `cli.py` | 新增 monitor 命令 + 适配新流程 | P1 |

### 13.3 移除/冻结的文件

| 文件 | 处理方式 | 原因 |
|------|---------|------|
| `pipeline_workflow.py` | 移除 | 旧 buy_ready 状态机，PRD 已移除 |
| `review_workflow.py` | 冻结 | 复盘审批降级到后续版本 |
| `lifecycle/state_machine.py` | 重构 | 用 user_status 字段替代 |

---

## 14. 验证设计

### 14.1 单元测试覆盖

| 模块 | 测试重点 |
|------|---------|
| `alert_engine.py` | 每种信号的触发/不触发边界 |
| `alert_manager.py` | 生命周期流转、升级、失效、合并 |
| `position_manager.py` | 加权平均成本、部分卖出、全部卖出 |
| `research_queue.py` | 去重规则（10天自然日）、15只限额、已忽略跳过 |
| `research_engine.py` | 交付门槛 vs 质量目标、降级流程 |

### 14.2 集成测试

| 场景 | 验证内容 |
|------|---------|
| 每日全链路 | 筛选 → 去重 → 研究（限额）→ 文档 → 通知 |
| 买入 → 监控 → 预警 | 买入录入 → 日常监控 → 信号触发 → 通知 |
| 预警生命周期 | 触发 → 通知 → 确认 → 失效/升级 |
| 持仓重研究 | 显著变化 → 重研究 → 数据更新 → 结论翻转通知 |
| 多信号合并 | 同股多信号 → 合并为一条通知 → 最高动作级别 |

### 14.3 关键业务验收

- [ ] 筛选可运行，结果入库，已忽略股票不触发研究
- [ ] 研究限额 15 只生效，超出标记"待研究"
- [ ] 10 天去重正确（自然日、美东时区），持仓股显著变化可打破
- [ ] 飞书文档可生成，链接可打开
- [ ] 飞书汇总通知包含所有股票状态（成功/降级/失败/复用/待研究）
- [ ] 买入录入后持仓跟踪自动启动，成本按加权平均计算
- [ ] 未在候选池的股票可直接录入买入
- [ ] 风险预警信号按默认阈值触发
- [ ] 卖出提醒信号按默认阈值触发
- [ ] 预警生命周期完整（触发→通知→确认→失效/升级）
- [ ] 价格类信号 3 个交易日降级为"历史触达"
- [ ] 条件类信号不自动失效
- [ ] 多信号合并为一条通知，取最高动作级别
- [ ] 持仓重研究后系统数据全量更新
- [ ] 结论翻转自动触发"持有逻辑失效"
- [ ] 全部卖出后预警自动关闭
- [ ] 持仓首页三段展示（需操作/需关注/正常）
