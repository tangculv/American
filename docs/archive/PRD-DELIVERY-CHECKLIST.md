# PRD 交付清单（产品级可商用）

> 目标文档：`PRD-开发基线版.md`
> 
> 本清单用于把 PRD 转成“可执行、可测试、可回归”的交付项。每一项都按 **要求标准 / 当前现状 / 实施动作 / 测试标准** 拆解，执行中以“真实可运行、尽量不破坏现有兼容层”为原则。

## 1. 生命周期闭环

### 1.1 要求标准
- 生命周期必须遵循唯一状态机：
  - `discovered -> shortlisted/rejected -> queued_for_research -> researched -> scored -> waiting_for_setup/buy_ready -> holding -> exit_watch -> exited -> archived`
- screening 阶段可保守落在 `shortlisted`，但系统必须提供独立闭环推进能力。
- 每次状态迁移必须有 `audit_log`。
- `stock_master` 的 `lifecycle_state/current_state/latest_score/latest_signal/trade_gate_blocked` 必须与最新事实一致。

### 1.2 当前现状
- 状态机校验与基础迁移日志已具备。
- `persist_screening_run()` 会落研究、评分、技术分析基础事实，但默认不推进完整 PRD 终态。
- 缺少独立的 pipeline progression runner。

### 1.3 实施动作
- 新增独立 pipeline workflow，而不是改写 screening 主路径。
- 支持：
  - `shortlisted -> queued_for_research`
  - `queued_for_research -> researched`
  - `researched -> scored`
  - `scored -> waiting_for_setup/buy_ready`
- 增加 CLI 入口和可复跑逻辑。

### 1.4 测试标准
- 单测覆盖完整合法迁移路径。
- 非法跳转必须失败且不写脏数据。
- 真实命令可对真实 symbol 完成推进。

---

## 2. 排序批次事实表（ranking_snapshot）

### 2.1 要求标准
PRD §7.1 要求：
- 每次 rank 生成唯一 `snapshot_batch_id`
- 同批次下完整 universe 全量落库，不允许只写 Top N
- 每条记录必须带：
  - `scoring_id`
  - `universe_size`
  - `rank_percentile`
  - `trade_gate_status`
  - `actionable`
  - `tie_break_trace`
  - `rank_reason_1/2/3`
  - `vs_next_rank`
- 缺评分股票不得静默丢弃，必须审计 excluded symbols

### 2.2 当前现状
- 仅有简化版 `ranking_snapshot`
- 当前主要记录 `rank_position/score/tie_break_trace_json`
- 不满足 PRD 全量批次契约

### 2.3 实施动作
- 扩 schema + migration
- 独立实现 ranking batch builder
- 支持 `research_priority / buy_priority / holding_monitor / global_overview`
- 增加批次级 audit 记录

### 2.4 测试标准
- 同分 tie-break 顺序正确
- batch 内 `universe_size` 一致
- `rank_percentile` 公式正确
- 缺评分时生成 partial audit

---

## 3. 研究队列

### 3.1 要求标准
PRD §7.2 要求：
- 队列优先级：`P0 > P1-B > P1-C > P1-A > P2`
- 插入后立即全队列重排
- 并发槽位 = 3
- 软预算 = 20/日，硬上限 = 50/日
- 失败重试 3 次，有延迟和降级规则
- 次日 09:00 ET 重排恢复
- backlog > 50 触发系统告警
- 每次队列操作都写 `audit_log`

### 3.2 当前现状
- 有 `research_snapshot` 和基础 enqueue 能力
- 缺完整优先级调度、重排、预算、并发槽位、失败恢复

### 3.3 实施动作
- 为队列增加排序与调度服务
- 为 `research_snapshot` 补充运行状态管理所需字段（尽量增量）
- 先交付单进程可验证版本，再保留并发槽位调度能力

### 3.4 测试标准
- 新任务插入后队头符合 PRD 规则
- 重试次数和降级符合规则
- 预算耗尽后 P2 暂停，P0/P1 行为符合预期
- backlog 告警正确触发

---

## 4. 通知契约系统

### 4.1 要求标准
PRD §8 要求：
- 通知以统一事件契约驱动，而不是仅发送筛选摘要
- 事件至少包括：
  - `strategy_hit`
  - `research_completed`
  - `score_change_significant`
  - `buy_signal`
  - `gate_blocked`
  - `gate_unblocked`
  - `exit_signal`
  - `price_alert`
  - `system_error`
  - `daily_digest`
  - `weekly_digest`
  - `review_pending`
- 所有通知先生成 `payload_json`，`message_content` 只是展示副本
- 要支持 `template_name/template_version/idempotency_key/cooldown/merge_rule/send_status`

### 4.2 当前现状
- 当前 notifications 以“筛选摘要推送”为主
- 缺通知事实表与事件去重/冷却机制
- 缺 PRD payload schema

### 4.3 实施动作
- 在不破坏现有 send_run_notification 的前提下，新增 event notification 层
- 先落最小可商用闭环：
  - `buy_signal`
  - `exit_signal`
  - `system_error`
  - `review_pending`
  - `research_completed`
- 增加通知落库、去重、冷却、发送审计

### 4.4 测试标准
- payload schema 字段完整
- cooldown 命中时不重复发送
- idempotency key 一致时不重复创建事件
- sender 被 mock 时可验证发送内容与落库一致

---

## 5. 复盘与审批

### 5.1 要求标准
- review 完成后生成待审批变更集
- 记录 approval/reject 状态
- 变更写回要原子化、可审计、可回滚

### 5.2 当前现状
- `review_log`、`suggested_change` 已有基础表
- 当前更偏记录复盘结果，审批闭环较弱

### 5.3 实施动作
- 补 review approval workflow
- 先支持：review_pending 通知 + 审批状态推进 + 审计（已完成基础版）

### 5.4 测试标准
- review 生成后可查询待审批变更（已完成基础版）
- approve/reject 会更新状态并写入审计（已完成基础版）

---

## 6. 调度与异常降级

### 6.1 要求标准
- 定时任务与事件驱动都要可运行
- 发生 API/调度异常时必须降级并留痕
- system_error 通知需包含 job/module/error/retry/fallback

### 6.2 当前现状
- 已有 doctor / scheduled job / smoke test 基础能力
- 异常告警契约未完全结构化

### 6.3 实施动作
- 将关键失败写入统一系统异常通知事件
- 为研究队列、排序批次、跟踪任务补充降级审计

### 6.4 测试标准
- 异常路径可落库 + 可通知 + 不致使主流程崩溃

---

## 7. 产品级真实回归

### 7.1 要求标准
- CLI 可开箱即用
- UI 可打开查看关键数据
- 真库可运行，不依赖 mock 才成立
- 文档可以指导非开发者直接使用

### 7.2 当前现状
- doctor / smoke-test / main / buy / sell / trigger-exit / archive-review / track 已验证通过
- UI 已可打开
- 但 PRD 闭环能力和事件通知层尚未完全收口

### 7.3 实施动作
- 每完成一个模块，就做真实命令回归
- 更新 README / docs / 操作手册 / 交付文档

### 7.4 测试标准
- 单测全绿
- 编译检查通过
- 真实命令链路通过
- UI 可见新能力或新数据



## 8. 详细执行拆解（高自治持续交付版）

> 说明：以下任务按“与主体关联性 / 和其他功能的影响 / 详细描述 / 验收标准”统一拆解；执行时必须先开发、再自测、未达标则继续优化直至通过。

### Task 8.1 生命周期推进与交易主干
- 与主体关联性：这是整个系统从“发现候选”走向“可交易、可复盘”的主干骨架。
- 和其他功能的影响：直接影响 tracking、ranking、review、notification、UI 生命周期面板。
- 详细描述：保持 screening 主路径兼容前提下，用独立 workflow 完成 shortlisted -> queued_for_research -> researched -> scored -> waiting_for_setup/buy_ready，以及 buy -> holding -> exit_watch -> exited -> archived。
- 验收标准：
  - 状态迁移全部有 audit_log
  - stock_master 的 lifecycle_state/current_state/latest_score/latest_signal/trade_gate_blocked 与最新事实一致
  - CLI 链路可真实执行
  - 单测通过

### Task 8.2 排序批次事实表
- 与主体关联性：这是“今天该先看谁/先买谁”的排序中枢。
- 和其他功能的影响：直接影响 UI 候选列表、通知摘要、研究优先级、交易优先级判断。
- 详细描述：为 ranking_snapshot 提供 snapshot_batch_id、universe_size、rank_percentile、trade_gate_status、actionable、vs_next_rank、excluded_symbols_json 等事实字段，并保证 batch 一致性。
- 验收标准：
  - rank batch 全量落库，不只 top N
  - tie-break 可解释
  - excluded symbols 可审计
  - CLI 可生成 batch
  - 单测通过

### Task 8.3 研究队列 PRD 化
- 与主体关联性：这是研究产能调度中心，决定研究资源如何分配。
- 和其他功能的影响：影响 research_snapshot、system_error 通知、UI 生命周期面板、后续研究自动化。
- 详细描述：补齐优先级重排、claim、失败重试、优先级降级、每日软预算20、硬上限50、并发槽位3、backlog > 50 告警、日恢复重排。
- 验收标准：
  - P0/P1/P2 claim 规则符合 PRD
  - 预算耗尽后行为正确
  - backlog 超阈值触发 system_error 事件
  - recovery reorder 写审计
  - CLI 可调用
  - 单测通过

### Task 8.4 通知契约系统
- 与主体关联性：这是产品“对外表达”和异常反馈的统一出口。
- 和其他功能的影响：影响飞书通知、复盘审批、交易提醒、调度异常处理、未来通知中心 UI。
- 详细描述：建立 event notification 层，统一 payload_json、message_content、dedupe、cooldown、send_status，并逐步补齐 buy_signal / exit_signal / system_error / review_pending / research_completed / gate_blocked / gate_unblocked / strategy_hit / digest 等事件。
- 验收标准：
  - 事件具备结构化 payload
  - 冷却和幂等生效
  - 与 workflow 联动时不锁库
  - 可真实发送或真实落库
  - 单测通过

### Task 8.5 复盘审批闭环
- 与主体关联性：这是系统从“记录结果”走向“形成组织知识”的关键一环。
- 和其他功能的影响：影响 review_log、suggested_change、通知、审计、后续策略优化自动化。
- 详细描述：实现 review -> suggested_change -> review_pending -> approve/reject -> audit 的闭环，并提供 CLI 入口。
- 验收标准：
  - review 后可查询待审批变更
  - approve/reject 可执行且幂等
  - 审计日志完整
  - CLI 可直接使用
  - 单测通过

### Task 8.6 调度与异常降级
- 与主体关联性：这是保证系统长期真实运行的运维底座。
- 和其他功能的影响：影响 scheduled job、doctor、system_error 通知、真实运行稳定性。
- 详细描述：把关键模块失败纳入统一异常通知契约，确保失败时可留痕、可告警、不致使主流程整体崩溃。
- 验收标准：
  - 关键异常路径有 audit 或 notification_event
  - schedule 逻辑保持可回归
  - 真实命令失败时输出可解释
  - 单测通过

### Task 8.7 用户可感知产品形态
- 与主体关联性：这是“代码项目”变成“使用者可用产品”的最后一层包装。
- 和其他功能的影响：影响 README、PRODUCT-DELIVERY、UI、CLI 使用体验。
- 详细描述：持续把已完成能力收口进 UI、CLI 和交付文档，让非开发者也能按文档直接使用。
- 验收标准：
  - doctor / run / rank / advance-pipeline / review / queue CLI 直接可用
  - UI 可查看核心数据
  - 交付文档与现状一致
  - 真实回归通过
