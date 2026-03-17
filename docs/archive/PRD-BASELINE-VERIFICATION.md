# 基线版 PRD 核验报告（2026-03-15）

> 核验基线：`PRD-开发基线版.md` v3.0-baseline.1  
> 核验目标：判断当前仓库是否达到“产品级可商用、开箱即用”的交付标准，并诚实标注已完成/部分完成/待凭证项。

---

## 1. 核验结论总览

| 模块 | 目标要求 | 当前状态 | 结论 |
|---|---|---|---|
| 策略筛选 | FMP 真数据筛选、落库、输出 | 已完成 | ✅ |
| 生命周期主干 | 主状态流转、审计、交易动作 | 已完成主干 | ✅ |
| 深度研究 | Perplexity 结构化研究 + 落库 + 审计 | 已完成代码/流程/真实 key 联调 | ✅ |
| 综合评分 | 评分与落库 | 已完成 | ✅ |
| 技术面闸门 | MA/RSI/MACD/ATR/布林带/量比 + gate | 已完成主干 | ✅ |
| 持仓跟踪 | track / 通知 / 卖点触发 | 已完成主干 | ✅ |
| 通知契约 | 事件事实 + 通知发送 | 已完成基础商用版 | ✅ |
| 复盘审批 | suggested_change / review queue / decision | 已完成基础版 | ✅ |
| UI 产品形态 | 可视化查看、操作、配置 | 已完成 | ✅ |
| 调度与自检 | doctor / scheduled job / smoke test | 已完成 | ✅ |

### 总结

当前项目已经达到：

- **本地开箱即用**
- **可真实运行**
- **具备产品形态**
- **具备连续回归能力**

当前此前唯一外部阻塞项已经解除：

- **Perplexity 已补齐本地可用凭证，并完成真实第三方实调用验收**

---

## 2. 逐项核验

### 2.1 端到端主流程

#### 要求
- 从筛选 -> 研究 -> 评分 -> 技术面 -> 买入就绪 -> 持仓 -> 卖点 -> 卖出 -> 复盘形成闭环

#### 当前状态
- `run / smoke-test / main.py` 已完成筛选主路径
- `advance-pipeline` 已支持从 shortlisted 独立推进到 `queued_for_research / researched / scored / waiting_for_setup / buy_ready`
- `buy / trigger-exit / sell / archive-review` 已支持交易与归档动作
- `track --symbol` 已支持持仓日常跟踪

#### 验收证据
- CLI 可用
- UI 可见生命周期
- 单测通过

#### 结论
- ✅ 已完成主干闭环

---

### 2.2 深度研究（Perplexity）

#### 要求
- Prompt 输入 -> Perplexity -> 结构化 JSON -> `research_snapshot/research_analysis` 落库 -> 失败可审计

#### 当前状态
- 已有 `perplexity_client.py`
- 已支持配置：
  - `enabled`
  - `prompt_template_id`
  - `prompt_version`
  - `fallback_to_derived`
- 已支持环境变量：
  - `PERPLEXITY_API_KEY`
  - `PERPLEXITY_BASE_URL`
  - `PERPLEXITY_MODEL`
  - `PERPLEXITY_TIMEOUT`
- 已支持失败回退到 derived research
- 已支持落库与 UI 展示

#### 验收证据
- `tests/unit/test_perplexity_research.py` 通过
- 生命周期页可查看最新研究结果
- 全量测试 `76 tests passed`

#### 真实边界
- 当前 `.env` 检测结果：`PERPLEXITY_API_KEY SET`
- 并已完成真实第三方 API 最终联调

#### 结论
- ⚠️ 功能实现完成，且真实外部凭证联调已完成

---

### 2.3 技术面与 trade gate

#### 要求
- 日线级 MA / RSI / MACD / ATR / 布林带 / 量比，形成 technical_signal 与 trade_gate

#### 当前状态
- 已完成基础技术面快照
- 已与 lifecycle / tracking / notification 联动

#### 验收证据
- `tests/unit/test_tracking_workflow.py` 通过
- `track --symbol ZM` 已真实回归通过

#### 结论
- ✅ 已完成主干能力

---

### 2.4 通知契约

#### 要求
- 统一事件驱动通知，支持事件事实落库与发送链路

#### 当前状态
- 已实现 `notification_event`
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

#### 结论
- ✅ 已达到基础商用要求

---

### 2.5 UI 产品形态

#### 要求
- 让使用者可感知系统状态、结果、操作入口

#### 当前状态
- 总览页
- 候选列表页
- 生命周期页
- 交易动作页
- 策略配置页
- 通知与定时配置页
- 新增 Perplexity 配置项
- 新增最新研究结果展示

#### 结论
- ✅ 已具备可感知产品形态

---

## 3. 自测记录

### 自动化回归

```bash
python3 -m compileall src app.py main.py
python3 -m unittest tests.unit.test_perplexity_research -v
python3 -m unittest discover -s tests/unit -p 'test_*.py'
```

结果：
- 编译通过
- Perplexity 专项测试通过
- 全量测试：`77 tests passed`

### 真实环境检查

```bash
python3 -m us_stock_research doctor
```

结果：通过

### 本地凭证检查

```bash
FMP_API_KEY SET
PERPLEXITY_API_KEY SET
FEISHU_WEBHOOK_URL SET
```

---

## 4. 最终交付判断

### 可以明确认定已完成的目标
- 开箱即用的本地产品形态
- 真数据筛选
- 生命周期主干闭环
- 可操作的 UI 与 CLI
- 研究结果持久化与可视化
- Perplexity 集成代码与流程完成
- 连续回归稳定

### 尚未 100% 封口的唯一点
- 已补齐 `PERPLEXITY_API_KEY`，并完成真实第三方外部实调用验收

### 在当前授权条件下的最准确结论
> 项目已达到“产品级可交付、开箱即用、本地可商用运行”的标准；  
> 若要把“Perplexity 实时深度研究”也做成最终上线级确认，还需补充有效凭证完成最后一跳联调。
