---
title: 美股选股体系
project_type: 投资研究
status: active
created: 2026-03-06
updated: 2026-03-15
---

# 美股选股体系

当前项目文档体系已收敛为三份主文档：

1. `docs/PRD-BUSINESS.md`：业务可读 PRD
2. `docs/TECHNICAL-DESIGN.md`：技术设计文档
3. `docs/DEVELOPMENT-PLAN.md`：唯一开发计划

后续开发、跟进、验收统一按以下主线执行：

> 业务 PRD → 技术设计 → 开发计划 → 按计划开发 → 最后按 PRD 验收还原

---

## 快速开始

### 安装依赖
```bash
python3 -m pip install -r requirements.txt
```

### 配置环境变量
```bash
cp .env.example .env
```

至少填写：
- `FMP_API_KEY`

可选填写：
- `PERPLEXITY_API_KEY`
- `FEISHU_WEBHOOK_URL`
- `ALPHA_VANTAGE_API_KEY`

---

## 推荐使用顺序

### 1. 系统自检
```bash
python3 -m us_stock_research doctor
```

### 2. 跑一次真实筛选
```bash
python3 -m us_stock_research smoke-test --strategy low_valuation_quality --top-n 5
```

### 3. 日常运行
```bash
python3 main.py --top-n 10
```

---

## 常用命令

```bash
python3 -m us_stock_research --help
python3 -m us_stock_research run --strategy low_valuation_quality --top-n 10
python3 -m us_stock_research run-and-notify --strategy low_valuation_quality --top-n 10
python3 -m us_stock_research notify-latest
python3 -m us_stock_research research --symbol ZM --provider auto --persist
python3 -m us_stock_research research-diagnostics
python3 -m us_stock_research advance-pipeline --symbol ZM
python3 -m us_stock_research track --symbol ZM
python3 -m us_stock_research buy --symbol ZM --price 80 --quantity 10
python3 -m us_stock_research trigger-exit --symbol ZM --reason technical_reversal
python3 -m us_stock_research sell --symbol ZM --price 95 --quantity 10
python3 -m us_stock_research archive-review --symbol ZM --summary "完成复盘"
python3 -m us_stock_research review-queue
python3 -m us_stock_research review-decision --change-id 1 --decision approved
python3 -m us_stock_research rank --scope global_overview
python3 -m us_stock_research project-status
```

---

## UI

```bash
zsh scripts/run_ui.sh
```

默认地址：
- `http://127.0.0.1:8877`

当前 UI 页面包括：
- 项目总盘
- 总览
- 候选列表
- 生命周期
- 交易动作
- 策略配置
- 通知与定时

---

## 当前主文档

### 业务 PRD
- `docs/PRD-BUSINESS.md`

### 技术设计
- `docs/TECHNICAL-DESIGN.md`

### 开发计划
- `docs/DEVELOPMENT-PLAN.md`

### 历史文档归档
- `docs/archive/`

