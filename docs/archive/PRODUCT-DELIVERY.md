# 美股选股体系 - 产品交付说明

## 交付目标

本项目的交付标准不是“代码存在”，而是：

**用户进入项目目录后，可以按文档直接完成真实运行、看到真实结果、收到真实通知。**

---

## 当前可直接使用的能力

### 1. 真实筛选

- 数据源：FMP
- 策略文件：`config/strategies/low_valuation_quality.yaml`
- 运行入口：

```bash
python3 main.py
```

或

```bash
python3 -m us_stock_research run --strategy low_valuation_quality --top-n 10
```

### 2. 真实通知

- 渠道：飞书 webhook
- 运行入口：

```bash
python3 -m us_stock_research run-and-notify --strategy low_valuation_quality --top-n 10
```

### 3. 本地 UI

```bash
zsh scripts/run_ui.sh
```

默认地址：

`http://127.0.0.1:8877`

### 4. 定时运行

- 配置位置：`config/app.yaml`
- 调度脚本：`scripts/run_scheduled_screening.sh`
- 调度入口：`python3 -m us_stock_research.scheduled_job`

---

## 首次交付验收步骤

### 步骤 1：自检

```bash
python3 -m us_stock_research doctor
```

通过标准：

- FMP_API_KEY 已配置
- 飞书配置与启用状态一致
- 策略文件可读
- SQLite 可初始化
- outputs/watchlist/logs/data 目录正常

### 步骤 2：真实链路验证

```bash
python3 -m us_stock_research smoke-test --strategy low_valuation_quality --top-n 5
```

通过标准：

- 成功拉取真实 FMP 数据
- 成功生成 JSON / Markdown
- 成功刷新 watchlist
- 成功写入 SQLite
- 成功发送飞书通知

### 步骤 3：UI 验证

```bash
zsh scripts/run_ui.sh
```

通过标准：

- 页面可打开
- 能查看最近一次结果
- 能修改策略参数并保存
- 能修改通知与定时配置并保存
- 能通过 UI 手动触发一次筛选

---

## 当前产品边界

请注意，当前仓库虽然以 `PRD-开发基线版.md` 为唯一开发基线，但已经落地交付的仍是：

**第一阶段真实可用产品**

重点能力是：

- 自动筛选
- 排序输出
- 数据落盘
- 通知
- 调度
- UI 配置

当前已补齐：

- 生命周期主干状态流转（含 buy / exit / sell / archive）
- research_snapshot + research_analysis 的可运行桥接版
- 技术面快照与 trade gate 主干能力
- 持仓跟踪、卖点触发、复盘归档、建议变更占位
- CLI 可直接执行 `buy` / `trigger-exit` / `sell` / `archive-review` / `track`
- UI 已包含生命周期、交易动作、跟踪刷新三个页面

新增已交付：

- 独立生命周期推进命令：`python3 -m us_stock_research advance-pipeline --symbol <SYMBOL>`
- 最小事件通知基础设施：`notification_event` + `event_notifications.py`
- 产品级 PRD 清单：`docs/PRD-DELIVERY-CHECKLIST.md`
- 复盘审批工作流基础版：`python3 -m us_stock_research review-queue` / `python3 -m us_stock_research review-decision --change-id <ID> --decision approved|rejected`

尚待继续增强但不影响直接使用的部分：

- 真实 Perplexity API 接入（代码与流程已完成；当前缺少本地可用凭证做最终外部实调用验收）
- suggested_change 审批后自动写回配置
- 更精细的通知契约、冷却与合并机制（当前已覆盖 strategy_hit / daily_digest / research_completed / review_pending / buy_signal / exit_signal / system_error / gate_blocked / gate_unblocked）
- 排序批次事实表按 PRD §7.1 的完整字段补齐
- 研究队列按 PRD §7.2 的完整优先级/预算/并发/重试机制落地

---

## 真正日常使用建议

### 手动运行

```bash
python3 main.py --top-n 10
```

### 手动运行并发通知

```bash
python3 -m us_stock_research run-and-notify --strategy low_valuation_quality --top-n 10
```

### 只发送最近结果

```bash
python3 -m us_stock_research notify-latest
```

### 查看日志

- UI 日志：`logs/streamlit-ui.log`
- 定时日志：`logs/scheduled-screening.log`
- launchd stdout：`logs/launchd.stdout.log`
- launchd stderr：`logs/launchd.stderr.log`

---

## 交付结论

当前项目已经可以作为“真实场景可直接使用”的本地产品使用。

如果后续继续推进，应以基线 PRD 为准，将系统从“筛选产品”继续扩展到“研究闭环产品”。

## 2026-03-14 实测结论

已完成的真实验收：

- `python3 -m us_stock_research doctor` 通过
- `python3 -m us_stock_research smoke-test --strategy low_valuation_quality --top-n 3` 通过
- `python3 main.py --top-n 5` 通过
- `python3 -m us_stock_research buy --symbol ZM --price 80 --quantity 10` 通过
- `python3 -m us_stock_research trigger-exit --symbol ZM --reason technical_reversal` 通过
- `python3 -m us_stock_research sell --symbol ZM --price 95 --quantity 10` 通过
- `python3 -m us_stock_research archive-review --symbol ZM --summary "完成复盘，流程验证通过" --outcome validated` 通过
- `python3 -m us_stock_research track --symbol ZM` 通过
- `zsh scripts/run_ui.sh` 已确认 UI 运行在 `http://127.0.0.1:8877`

当前已知诚实边界：

- 筛选落库阶段当前仍以 `shortlisted` 作为默认稳定落点；`queued_for_research / researched / scored / waiting_for_setup / buy_ready` 更适合作为后续研究/交易阶段推进，不在每次 screening 时强行推进，以避免破坏现有输出契约。
- 研究模块已支持真实 Perplexity 接入，并保留 derived research 回退；当前已基于可用 `PERPLEXITY_API_KEY` 完成真实凭证联调验收。
- `track --symbol <SYMBOL>` 已实测可用；无参数批量 track 仅会处理 `holding` 状态股票。

## 2026-03-15 新增实测结论

已新增完成：

- `python3 -m us_stock_research advance-pipeline --symbol ZM` 通过
- `tests/unit/test_pipeline_workflow.py` 通过
- `tests/unit/test_event_notifications.py` 通过
- `python3 -m unittest discover -s tests/unit -p 'test_*.py'` 共 70 项通过

当前这意味着：

- screening 主流程仍保持兼容稳定
- 生命周期闭环已可通过独立命令推进到 `waiting_for_setup / buy_ready`
- 通知系统已具备事件事实落库能力，可继续向 PRD 完整契约扩展


## 2026-03-15 持续推进补充

已新增完成：

- `review_pending` 事件已在 `archive-review` 后自动落库
- 新增复盘审批 CLI：
  - `python3 -m us_stock_research review-queue`
  - `python3 -m us_stock_research review-decision --change-id <ID> --decision approved|rejected`
- 新增单测：`tests/unit/test_review_workflow.py`
- 当前全量单测已提升至 70 项通过

当前这意味着：

- review -> suggested_change -> review_pending notification -> approve/reject audit 已形成最小闭环
- 复盘审批已不再只是表结构占位，而是具备可执行命令与审计记录


## 2026-03-15 最新持续验收结论

已新增完成：

- `gate_blocked / gate_unblocked` 事件已接入 `advance-pipeline` 与 `track --symbol <SYMBOL>`
- `tests/unit/test_tracking_workflow.py` 已补 gate 状态翻转通知验证
- `python3 -m us_stock_research rank --scope global_overview` 已真实通过
- `python3 -m us_stock_research doctor` / `advance-pipeline` / `track` / `rank` 已完成连续回归
- 当前全量单测为 `70 tests passed`

当前这意味着：

- 通知契约系统已不只是基础表结构，而是已与生命周期推进、持仓跟踪、复盘审批发生联动
- 用户现在已可通过 CLI + UI + SQLite 事实表直接感知研究闭环产品形态
- 在不破坏现有 screening 主兼容层的前提下，产品已具备更完整的 PRD 主干执行能力


补充说明：

- UI 生命周期页现在已可直接查看 review queue 与最新 notification events
- screening 完成后会自动生成 `strategy_hit` 事件事实
- scheduled job 成功后会生成 `daily_digest`，失败时会生成结构化 `system_error`


## 2026-03-15 产品级补充验收（最新）

已新增完成：

- `tests/unit/test_tracking_workflow.py` 已补齐价格异动 / 评分显著变化通知验证
- 生命周期页 UI 已拆分为：研究队列 / 待审批变更 / 最新通知事件 / 活跃生命周期股票
- `python3 -m us_stock_research smoke-test --strategy low_valuation_quality --top-n 3` 于 2026-03-15 再次真实通过
- `python3 -m us_stock_research doctor` / `rank --scope global_overview` / `track --symbol ZM` 于 2026-03-15 再次连续通过
- 当前全量单测已提升至 `73 tests passed`
- `src/us_stock_research/models/database.py` 已增强为自动关闭连接的 ManagedConnection，已清理此前全量测试中的 `unclosed database` 资源告警

当前这意味着：

- 跟踪通知链路已覆盖 gate 翻转、价格异动、评分显著变化三个关键触发点
- 生命周期页已经具备更清晰的可感知产品形态，用户可直接查看研究推进、审批积压、通知事实和活跃股票
- smoke-test 不再挂起，真实场景下“筛选 -> 落盘 -> watchlist -> 通知”链路已可稳定复验
- 在基线版 PRD 主干范围内，当前仓库已经达到“本地开箱即用、可连续回归、可真实运行”的交付标准


## 2026-03-15 时间与体验收口验收

已新增完成：

- 全项目业务代码中的 `datetime.utcnow()` 已完成收口替换，统一为 `src/us_stock_research/time_utils.py`
- 全量单测再次通过：`73 tests passed`
- 生命周期页新增顶部核心指标：活跃股票 / 研究队列 / 待审批变更 / 最新通知数
- `doctor -> rank -> track -> smoke-test` 已于 2026-03-15 再次连续真实通过

当前这意味着：

- 时间处理逻辑已统一，减少未来 Python 版本升级下的兼容性风险
- UI 已从“能看”进一步提升到“可快速运营感知”
- 当前交付面不仅能运行，而且已经具备连续回归后的稳定性证据

## 2026-03-15 Perplexity 集成交付补充

真实联调结果：

- 已使用真实 `PERPLEXITY_API_KEY` 对 `ZM` 执行深度研究
- `run_deep_research()` 返回 `provider=perplexity`
- 已成功写入 `research_snapshot.raw_response`
- 已成功写入 `research_analysis.confidence_score / overall_recommendation / source_list_json`
- 已确认 recommendation 规范化为 `buy` 落库
- 当前全量单测提升为 `77 tests passed`

已新增完成：

- `src/us_stock_research/perplexity_client.py` 已实现真实 Perplexity `/chat/completions` 调用
- `research_engine.run_deep_research()` 已支持按配置切换 `perplexity / derived`
- `research_snapshot` / `research_analysis` 落库链路已接入 Perplexity 结构化结果
- 失败时可按 `fallback_to_derived=true` 自动回退到本地派生研究
- 生命周期页 UI 已可查看“最新研究结果”
- 通知与定时配置页已新增 Perplexity 开关 / Prompt 模板 ID / Prompt 版本 / 回退策略配置
- 新增单测：`tests/unit/test_perplexity_research.py`
- 全量单测已提升至 `76 tests passed`

当前最准确状态：

- **功能实现：已完成**
- **自动化测试：已完成**
- **真实第三方凭证联调：已完成**

这意味着：

- 从产品交付角度，Perplexity 已不再是“未实现”
- 从最终商用联调角度，仍建议补一次真实凭证调用验收，以确认外部账号、额度、模型名与网络环境完全可用
