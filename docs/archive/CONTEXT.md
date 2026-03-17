# Project Context — 美股选股体系

## Current State
- **Doing**: Phase 1 交付物验收 + Phase 2 研究集成准备
- **Blocking**: Perplexity 真实 API 未接入（Phase 2 前置）；研究队列 8 条硬规则未全部实现
- **Next**: 完成 PRD-DELIVERY-CHECKLIST.md 验收清单；拆分 Phase 2 任务（T2.1~T2.7）
- **Last Updated**: 2026-03-15

## Recent Work

1. **2026-03-15** 新增复盘审批闭环 — CLI review-queue / review-decision 命令 + 单测
2. **2026-03-15** 生命周期独立推进 — advance-pipeline 命令 + gate 事件通知
3. **2026-03-14** 全链路 smoke-test 验证 — 所有 CLI 命令通过 + UI 正常 + SQLite 持久化完整

## Known Issues

- **FMP API 限流**：大量请求时 429，当前 3 次重试 + 指数退避，考虑 Redis 缓存或降频到周度
- **SQLite 并发写入**：WAL 模式 + 写入锁 + 3 次重试，目前未触发冲突
- **评分公式变更导致历史不可比**：formula_version 字段已预留，但回溯重算机制未建
- **飞书 Webhook 偶尔延迟**：3 次重试 + 指数退避 + 每日摘要兜底

## Cross-Project References

- 无
