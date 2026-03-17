# PRD 章节进度对照台账

> 基线：`PRD-开发基线版.md`  
> 目的：把 PRD 的一级章节，逐条映射到 **当前实现 / 已核验证据 / 当前缺口 / 下一步动作**，让你随时能判断“整体做到哪了”。

---

## 1. 使用说明

这份台账不是重复 PRD，而是站在交付视角回答 4 个问题：

1. **这章 PRD 要求什么？**
2. **现在项目里已经实现了什么？**
3. **有什么证据证明它不是口头完成？**
4. **还差什么、下一步怎么补？**

建议与以下文件配合看：

- `docs/PROJECT-MASTER-BOARD.md`：看总盘与模块进度
- `docs/PRD-SECTION-PROGRESS-BOARD.md`：看 PRD 逐章对照
- `docs/PRD-BASELINE-VERIFICATION.md`：看核验结论
- `docs/PRD-DELIVERY-CHECKLIST.md`：看执行型交付清单

---

## 2. PRD 一级章节对照总表

| PRD 章节 | 目标摘要 | 当前实现 | 当前判断 | 关键证据 | 当前缺口 | 下一步 |
|---|---|---|---|---|---|---|
| §1 系统目标与边界 | 定义边界、事实源、能力范围 | 已有 SQLite + YAML + env + doctor + 本地单用户产品形态 | 已完成主干 | doctor / README / config / schema | 健康探针可更细 | 增强运行时健康诊断 |
| §2 端到端主流程 | 从筛选到复盘反哺形成闭环 | 主干流程已跑通，研究/交易/复盘具备独立命令推进 | 已完成主干 | run / research / advance-pipeline / buy/sell/track / archive-review | 自动反哺仍未完全封口 | 继续补审批后自动回写 |
| §3 生命周期状态机 | 唯一状态机与合法迁移 | 主状态流转、UI 展示、CLI 操作已具备 | 可用 | advance-pipeline / 生命周期页 / state machine tests | 失败态与再激活展示仍可增强 | 补失败态说明与再激活视图 |
| §4 唯一主评分模型 | 可解释评分体系 | 评分主干与 ranking 已可用 | 可用 | Score 输出 / ranking_workflow / tests | 向 PRD 完整 7 维权重继续收口 | 增强评分拆解与 partial_score 解释 |
| §5 技术面模型 | technical_signal / trade_gate | 日线指标 + gate 联动已可用 | 可用 | tracking / pipeline / gate events / tests | 参数与解释性仍可增强 | 增加技术面解释看板 |
| §6 统一数据模型 | 统一事实源与表结构 | 核心表已落地并持续扩 schema | 可用 | schema.py / SQLite / UI / CLI | 个别 PRD 字段仍是简化实现 | 继续补完整字段契约 |
| §7 排序与研究队列 | ranking_snapshot + research queue 治理 | 排名与研究队列主干已可用 | 可用但待增强 | rank / research-queue-claim / recover / tests | 预算、并发、重试、全量 batch 规则未完全封口 | 继续 PRD 化队列治理 |
| §8 通知契约总表 | 统一事件通知系统 | 事件事实表和主干事件已接入 | 可用但待增强 | notification_event / event_notifications / UI 通知页 | 冷却/合并/重试/完整 payload 契约继续增强 | 补通知治理层 |
| §9 复盘与变更审批 | review -> suggested_change -> approval | 复盘归档、待审批变更、审批决策主干已可用 | 可用但待增强 | archive-review / review-queue / review-decision / tests | 审批后自动写回配置未封口 | 实现安全回写 |
| §10 调度系统与异常降级 | 定时、自检、降级、异常留痕 | doctor / schedule / system_error / digest 已具备 | 可用 | scheduled_job / doctor / tests | 更细的异常治理与看板仍待增强 | 增强调度观测 |
| §11 开发分期与验收标准 | 产品级交付和回归 | 已有 README / DELIVERY / CHECKLIST / VERIFICATION / tests | 可用 | 82 tests / compileall / docs | 需进一步把进展感知产品化 | 持续维护总盘与逐章台账 |

---

## 3. 逐章详细台账

### §1 系统目标与边界

- **PRD 要求**
  - 明确系统做什么、不做什么
  - 明确 SQLite 是唯一事实源
  - 配置和 Prompt 有固定事实源
  - API 密钥必须走环境变量

- **当前实现**
  - 已有 `data/stock_research.db` 作为 SQLite 事实源
  - 已有 `config/strategies/*.yaml`、`config/app*.yaml`、`config/prompts/*.md`
  - `.env` / `.env.example` 已存在
  - `doctor` 可检查关键运行依赖

- **证据**
  - `python3 -m us_stock_research doctor` 可直接运行
  - `src/us_stock_research/models/schema.py`
  - `README.md` 的启动说明

- **当前缺口**
  - 外部 API 限流、额度和网络抖动的健康探针还可以更细

- **下一步**
  - 补细粒度健康状态和失败分层提示

---

### §2 端到端主流程

- **PRD 要求**
  - 从策略筛选到复盘反哺形成完整闭环

- **当前实现**
  - 筛选：`run / smoke-test / main.py`
  - 研究：`research` / `advance-pipeline`
  - 评分：scoring + ranking 已可用
  - 技术面：`track` / `advance-pipeline` 已联动
  - 交易：`buy / trigger-exit / sell`
  - 复盘：`archive-review`
  - 审批：`review-queue / review-decision`

- **证据**
  - 真实命令链路已多轮验收
  - `docs/PRODUCT-DELIVERY.md`
  - `docs/PRD-BASELINE-VERIFICATION.md`

- **当前缺口**
  - 反哺到配置的自动回写仍未完全完成

- **下一步**
  - 继续补“审批通过 -> 安全写回策略/参数”的闭环

---

### §3 唯一生命周期状态机

- **PRD 要求**
  - 使用唯一状态机，不允许状态语义混乱
  - 状态迁移可追踪、可审计

- **当前实现**
  - stock_master 生命周期字段已存在
  - `advance-pipeline` 可独立推进关键状态
  - `buy / sell / archive-review` 已驱动后半段流转
  - UI 生命周期页已展示状态分布、活跃股票、研究队列

- **证据**
  - `tests/unit/test_pipeline_workflow.py`
  - `tests/unit/test_state_machine.py`
  - `python3 -m us_stock_research advance-pipeline --symbol ZM`

- **当前缺口**
  - 更细失败态、重试态、再激活视图还未做成强产品表达

- **下一步**
  - 补状态失败分支说明和 archived/rejected 再激活展示

---

### §4 唯一主评分模型

- **PRD 要求**
  - 用统一评分体系支撑研究、排序、买入判断

- **当前实现**
  - 候选评分、排名快照、分数字段落库已完成主干
  - 研究结果能参与评分链路

- **证据**
  - `src/us_stock_research/cli.py` 中评分逻辑
  - `src/us_stock_research/ranking_workflow.py`
  - `tests/unit/test_cli.py`
  - `tests/unit/test_ranking_workflow.py`

- **当前缺口**
  - 与 PRD 完整 7 维模型相比，当前仍偏“可运行版”
  - partial_score 的解释性仍可增强

- **下一步**
  - 补评分拆解视图和更多异常样本验证

---

### §5 技术面模型（technical_signal / trade_gate）

- **PRD 要求**
  - 日线级技术分析，并形成 signal / gate

- **当前实现**
  - MA / RSI / MACD / ATR / 布林带 / 量比 主干已落地
  - `advance-pipeline` 与 `track` 已使用 gate 结果
  - `gate_blocked / gate_unblocked` 事件已联动

- **证据**
  - `src/us_stock_research/tracking_workflow.py`
  - `src/us_stock_research/pipeline_workflow.py`
  - `tests/unit/test_tracking_workflow.py`

- **当前缺口**
  - 参数精度和解释层仍可加强

- **下一步**
  - 增加技术信号解释看板和更多回归样本

---

### §6 统一数据模型（完整表结构）

- **PRD 要求**
  - 业务事实写 SQLite，表结构完整且稳定

- **当前实现**
  - 核心表已具备：
    - `stock_master`
    - `strategy_hit`
    - `research_snapshot`
    - `research_analysis`
    - `technical_snapshot`
    - `ranking_snapshot`
    - `notification_event`
    - `review_log` / `suggested_change`
  - schema 支持增量补列

- **证据**
  - `src/us_stock_research/models/schema.py`
  - UI / CLI 已直接消费这些表

- **当前缺口**
  - 个别表字段仍为简化商用版，不是 PRD 最终完整版

- **下一步**
  - 继续补齐 batch 级、通知治理级、审批回写级字段

---

### §7 排序与研究队列规则

- **PRD 要求**
  - 排名需可审计、可批次化
  - 研究队列需支持优先级、预算、恢复、重试

- **当前实现**
  - `rank` 已可生成排名快照
  - `research-queue-claim` / `research-queue-recover` 已可用
  - 研究诊断可输出新鲜度和触发建议

- **证据**
  - `src/us_stock_research/ranking_workflow.py`
  - `src/us_stock_research/research_queue.py`
  - `tests/unit/test_ranking_workflow.py`
  - `tests/unit/test_research_queue.py`

- **当前缺口**
  - ranking batch 的完整字段契约仍待补齐
  - 预算 / 并发 / backlog 告警 / 完整重试规则仍待继续 PRD 化

- **下一步**
  - 继续按 `docs/PRD-DELIVERY-CHECKLIST.md` 收口

---

### §8 通知契约总表

- **PRD 要求**
  - 通知由统一事件系统驱动，而不是仅发摘要

- **当前实现**
  - 已有 `notification_event`
  - 已接入：
    - `strategy_hit`
    - `daily_digest`
    - `weekly_digest`
    - `research_completed`
    - `review_pending`
    - `score_change_significant`
    - `price_alert`
    - `buy_signal`
    - `system_error`
    - `gate_blocked`
    - `gate_unblocked`

- **证据**
  - `src/us_stock_research/event_notifications.py`
  - `src/us_stock_research/scheduled_job.py`
  - `src/us_stock_research/tracking_workflow.py`
  - `src/us_stock_research/pipeline_workflow.py`
  - `tests/unit/test_event_notifications.py`

- **当前缺口**
  - 更严格的 cooldown / merge_rule / send governance 还可增强

- **下一步**
  - 补通知治理层与更细的失败重试策略

---

### §9 复盘与变更审批机制

- **PRD 要求**
  - review 后形成待审批变更集
  - approval/reject 可审计
  - 变更最终可回写

- **当前实现**
  - `archive-review` 可归档并生成 review 相关事实
  - `review-queue` / `review-decision` 已可用
  - `review_pending` 事件已联动

- **证据**
  - `src/us_stock_research/review_workflow.py`
  - `src/us_stock_research/portfolio_workflow.py`
  - `tests/unit/test_review_workflow.py`

- **当前缺口**
  - 审批通过后的自动写回配置仍未完成

- **下一步**
  - 做可审计、可回退的自动回写版本

---

### §10 调度系统与异常降级

- **PRD 要求**
  - 支持定时运行
  - 支持异常留痕和降级

- **当前实现**
  - `scheduled_job` 已可用
  - `doctor` / `smoke-test` 已可用
  - `system_error` / `daily_digest` / `weekly_digest` 已联动

- **证据**
  - `src/us_stock_research/scheduled_job.py`
  - `tests/unit/test_schedule.py`

- **当前缺口**
  - 调度异常的可观测性仍可进一步产品化

- **下一步**
  - 增强运行看板、失败追踪和恢复视图

---

### §11 开发分期与验收标准

- **PRD 要求**
  - 项目交付必须可运行、可测试、可核验

- **当前实现**
  - 已有：
    - `README.md`
    - `docs/PRODUCT-DELIVERY.md`
    - `docs/PRD-BASELINE-VERIFICATION.md`
    - `docs/PRD-DELIVERY-CHECKLIST.md`
    - `docs/PROJECT-MASTER-BOARD.md`
    - 当前新增 `docs/PRD-SECTION-PROGRESS-BOARD.md`
  - 现有自动化测试已达 82 项通过

- **证据**
  - `python3 -m unittest discover -s tests/unit -p 'test_*.py'`
  - `python3 -m compileall src app.py main.py tests`

- **当前缺口**
  - 之前“进度不可感知”的问题，现在已开始通过总盘体系修复，但还要持续维护

- **下一步**
  - 让总盘、逐章台账、UI、CLI 长期保持同步更新

---

## 4. 当前总判断

如果从 PRD 逐章对照来看，当前最准确的判断是：

> **PRD 主干已经进入“可直接使用的基线闭环产品”状态，部分章节已达到交付级，部分章节处于“可用但待继续收口”的状态。**

因此，当前项目不是“还在从 0 到 1 开发”，而是：

- **1 已经完成**：能运行、能用、能验证
- **接下来做的是 1 到 1.5 / 2**：把治理、解释性、可观测性、自动回写继续收口到更强的产品标准
