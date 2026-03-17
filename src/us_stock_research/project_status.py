from __future__ import annotations

from dataclasses import dataclass
from typing import Any


STATUS_ORDER = {
    '未开始': 0,
    '开发中': 1,
    '可用': 2,
    '待优化': 3,
    '已交付': 4,
}


@dataclass(frozen=True)
class ProjectModuleStatus:
    id: str
    name: str
    prd_section: str
    relation: str
    impact: str
    goal: str
    status: str
    completion_pct: int
    user_visible: str
    completed_items: list[str]
    pending_items: list[str]
    acceptance_criteria: list[str]
    latest_validation: list[str]
    risks: list[str]
    next_actions: list[str]


MODULES: list[ProjectModuleStatus] = [
    ProjectModuleStatus(
        id='data_config',
        name='数据源与配置层',
        prd_section='§1 / §6 / §10',
        relation='全系统底座；所有筛选、研究、通知、调度都依赖统一配置和 SQLite 事实源。',
        impact='若配置或数据源失效，整个主流程会中断，UI/CLI 也会同时失真。',
        goal='保证 FMP / Perplexity / 飞书 / YAML / SQLite 的读取、持久化与环境自检稳定可用。',
        status='已交付',
        completion_pct=95,
        user_visible='doctor 自检、.env 配置、config/*.yaml、SQLite data/stock_research.db',
        completed_items=[
            '环境变量读取与 .env 示例已落地',
            'SQLite schema 自动初始化可用',
            '策略配置 / 应用配置可通过 UI 和配置存储读写',
            'doctor 命令可检查 API Key、目录、策略、数据库可用性',
        ],
        pending_items=[
            '对外部 API 限流/配额状态的更细粒度探针仍可增强',
        ],
        acceptance_criteria=[
            '项目首次启动后可自动初始化数据库和目录结构',
            'doctor 输出应能准确提示关键配置是否就绪',
        ],
        latest_validation=[
            'python3 -m us_stock_research doctor 通过',
            'python3 -m compileall src app.py main.py tests 通过',
        ],
        risks=['外部 API 可用性受第三方网络与密钥状态影响。'],
        next_actions=['补充更细的运行时健康指标与失败分层提示。'],
    ),
    ProjectModuleStatus(
        id='screening',
        name='策略筛选层',
        prd_section='§2 步骤1-2 / §4',
        relation='主入口；决定哪些股票进入后续研究和评分流程。',
        impact='影响研究队列质量、排序结果、通知摘要与后续生命周期入口。',
        goal='基于策略 YAML 对 FMP 真数据执行筛选、初筛评分、落库与结果输出。',
        status='已交付',
        completion_pct=92,
        user_visible='run / smoke-test / main.py / 候选清单 markdown / JSON / Top3 / UI 候选列表',
        completed_items=[
            '支持读取 low_valuation_quality 策略并调用 FMP screener',
            '初筛评分与结果落盘已完成',
            'watchlist / Markdown / JSON / SQLite 写入已完成',
            'run / run-and-notify / smoke-test 可直接使用',
        ],
        pending_items=[
            '可继续扩展更多策略模板与更细的 rejected 原因透出',
        ],
        acceptance_criteria=[
            '能真实拉取 FMP 数据并输出排序后的候选结果',
            '候选结果需同时体现在 DB、文件输出和 UI 中',
        ],
        latest_validation=[
            'python3 -m us_stock_research smoke-test --strategy low_valuation_quality --top-n 5 通过',
            'README/PRODUCT-DELIVERY 已记录真实运行路径',
        ],
        risks=['FMP 字段波动可能影响部分评分字段完整性。'],
        next_actions=['补充更多 rejected/data_incomplete 可视化说明。'],
    ),
    ProjectModuleStatus(
        id='lifecycle',
        name='生命周期状态机',
        prd_section='§3',
        relation='贯穿全链路的唯一主线，统一股票从 discovered 到 archived 的状态流转。',
        impact='影响研究、交易、通知、复盘与 UI 生命周期展示的一致性。',
        goal='保证股票状态转移可追踪、可审计、可在 CLI/UI 中操作和查看。',
        status='可用',
        completion_pct=88,
        user_visible='生命周期页、buy/sell/trigger-exit/archive-review',
        completed_items=[
            '主状态字段与基础迁移逻辑已落地',
            '手工买入、卖出、卖点触发、归档复盘已可操作',
            'UI 生命周期页可查看状态分布和活跃股票',
        ],
        pending_items=[
            '部分 PRD 中更细的失败态/重试态仍可继续显式化',
            '归档再激活的产品化展示仍可增强',
        ],
        acceptance_criteria=[
            '关键状态变更需能在 DB 中追踪并由 CLI 触发',
            'UI 能展示主要生命周期状态分布和活跃标的',
        ],
        latest_validation=[
            'tests/unit/test_state_machine.py 通过',
        ],
        risks=['当前 screening 主兼容层未在每次运行中强推全状态推进，这是有意保守设计。'],
        next_actions=['继续完善状态机失败态说明与再激活视图。'],
    ),
    ProjectModuleStatus(
        id='research',
        name='深度研究（Perplexity）',
        prd_section='§2 步骤4 / §7',
        relation='是筛选后进入深度判断的核心桥梁，决定研究报告质量与综合评分输入。',
        impact='影响研究队列、综合评分、研究结果展示、后续触发和通知。',
        goal='支持手动/队列触发深度研究，生成结构化结论并持久化。',
        status='已交付',
        completion_pct=93,
        user_visible='research CLI、research-diagnostics、生命周期页最新研究结果、DB research_snapshot/research_analysis',
        completed_items=[
            'Perplexity API 集成已完成，并保留 derived fallback',
            '支持显式 research 命令与 provider 选择',
            '支持 prompt 展示、输入展示、落库、诊断与新鲜度建议',
            '真实 API 联调、持久化一致性修复、中文枚举归一化已完成',
        ],
        pending_items=[
            '研究触发策略仍可继续自动化细化（例如预算/并发/批量策略）',
        ],
        acceptance_criteria=[
            '可对单股票生成结构化研究结论并落库',
            '失败时必须支持 fallback 或明确可审计失败信息',
        ],
        latest_validation=[
            'python3 -m unittest tests.unit.test_perplexity_research tests.unit.test_research_cli -v 通过',
            'python3 -m us_stock_research research --symbol ZM --provider derived --persist 通过',
            'python3 -m us_stock_research research-diagnostics 通过',
        ],
        risks=['真实 Perplexity 质量依赖第三方模型输出稳定性。'],
        next_actions=['补充更细的自动触发条件与批量研究治理策略。'],
    ),
    ProjectModuleStatus(
        id='scoring',
        name='综合评分',
        prd_section='§2 步骤5 / §4',
        relation='连接研究结论与交易优先级，是候选排序和生命周期推进的关键依据。',
        impact='影响 shortlist 质量、buy_ready 判定、跟踪变更提醒与排名快照。',
        goal='形成稳定可解释的评分结果，并将分数写入事实表供后续使用。',
        status='可用',
        completion_pct=85,
        user_visible='候选列表 Score、DB scoring_breakdown、rank 输出、生命周期分数字段',
        completed_items=[
            '基础评分逻辑与评分明细已落地',
            '研究结果能进入后续评分使用链路',
            '排名快照支持基于评分范围输出',
        ],
        pending_items=[
            '与 PRD 7 维度模型的字段颗粒度仍可继续收口',
            '部分 partial_score 解释性展示仍可增强',
        ],
        acceptance_criteria=[
            '评分结果需可持久化并影响排序/生命周期判断',
            '缺失字段时应有可解释的降级逻辑',
        ],
        latest_validation=[
            'tests/unit/test_ranking_workflow.py 通过',
            'rank 命令真实执行通过',
        ],
        risks=['当前评分模型以可运行为优先，尚可继续贴近 PRD 完整权重矩阵。'],
        next_actions=['补评分拆解视图与更多异常样本回归。'],
    ),
    ProjectModuleStatus(
        id='technical_gate',
        name='技术面与交易闸门',
        prd_section='§2 步骤6-7 / §5',
        relation='决定研究通过的股票是否进入可买入状态，是连接研究与交易执行的门控层。',
        impact='直接影响 waiting_for_setup / buy_ready、跟踪提醒和通知触发。',
        goal='基于日线技术指标计算 signal/gate，并驱动买入就绪判定。',
        status='可用',
        completion_pct=86,
        user_visible='technical_snapshot、生命周期页 Gate/Signal、track 输出',
        completed_items=[
            'MA/RSI/MACD/ATR/布林带/量比 主干能力已落地',
            'trade_gate 已接入 tracking',
            'gate_blocked/gate_unblocked 事件联动已完成',
        ],
        pending_items=[
            '参数精度、更多形态解释和图形化展示仍可增强',
        ],
        acceptance_criteria=[
            '评分后个股可得到明确 signal/gate 结果',
            '闸门翻转需能产生对应事件和生命周期影响',
        ],
        latest_validation=[
            'tests/unit/test_tracking_workflow.py 通过',
            'track --symbol ZM 实测通过',
        ],
        risks=['技术面属于启发式模型，阈值还可继续迭代优化。'],
        next_actions=['增加更细的技术信号解释和回测样本校验。'],
    ),
    ProjectModuleStatus(
        id='ranking_queue',
        name='排序与研究队列',
        prd_section='§7',
        relation='承接筛选结果并决定研究/买入/跟踪的优先级。',
        impact='影响研究资源分配、用户关注顺序和通知节奏。',
        goal='支持排名快照、研究队列 claim/recover、优先级输出。',
        status='可用',
        completion_pct=82,
        user_visible='rank、research-queue-claim、research-queue-recover、生命周期研究队列',
        completed_items=[
            '排名快照命令已支持多个 scope',
            '研究队列 claim/recover 主干命令可用',
            '生命周期页可查看研究队列',
        ],
        pending_items=[
            'PRD 中更完整的预算/并发/重试/去重规则仍待继续收口',
            '队列 SLA 可视化还未单独成面板',
        ],
        acceptance_criteria=[
            '研究任务需具备可 claim/recover 的最小可运行队列能力',
            '排名结果需可持久化供 UI/通知使用',
        ],
        latest_validation=[
            'tests/unit/test_research_queue.py 通过',
            'python3 -m us_stock_research rank --scope global_overview 通过',
        ],
        risks=['当前优先级规则已可用，但离 PRD 的完整治理版本还有差距。'],
        next_actions=['继续补齐完整优先级矩阵与恢复策略说明。'],
    ),
    ProjectModuleStatus(
        id='portfolio',
        name='持仓跟踪与交易动作',
        prd_section='§2 步骤8-11',
        relation='是系统从“研究产品”走向“交易闭环”的核心可操作层。',
        impact='影响 holding / exit_watch / exited 状态、通知、复盘数据和 UI 操作体验。',
        goal='支持人工买卖执行、持仓刷新、卖点触发与状态更新。',
        status='已交付',
        completion_pct=90,
        user_visible='buy / trigger-exit / sell / track / 交易动作页',
        completed_items=[
            '买入、卖出、卖点触发、跟踪刷新 CLI 已可用',
            'UI 已提供交易动作与跟踪入口',
            '价格异动/评分变化/卖点联动通知已具备主干能力',
        ],
        pending_items=[
            '批量持仓运营视图与更细的收益拆解仍可增强',
        ],
        acceptance_criteria=[
            '用户能录入买卖并驱动生命周期变化',
            'holding 标的可刷新跟踪并产出事件/快照',
        ],
        latest_validation=[
            'buy / trigger-exit / sell / archive-review 历史实测通过',
            'tests/unit/test_portfolio_workflow.py 与 test_tracking_workflow.py 通过',
        ],
        risks=['当前执行仍是人工成交录入，不涉及券商自动下单。'],
        next_actions=['补充更直观的持仓收益和风险看板。'],
    ),
    ProjectModuleStatus(
        id='notifications',
        name='通知系统',
        prd_section='§8',
        relation='负责把系统关键状态变化变成用户可感知的提醒，是产品可运营性的关键一环。',
        impact='影响用户对策略命中、研究完成、买卖信号、异常的及时感知。',
        goal='实现事件事实表 + 飞书发送链路 + 基础通知契约。',
        status='可用',
        completion_pct=87,
        user_visible='run-and-notify / notify-latest / notification_event / UI 最新通知事件',
        completed_items=[
            'notification_event 事实表已落地',
            'strategy_hit / daily_digest / weekly_digest / research_completed / review_pending / buy_signal / system_error 等已接入',
            'UI 生命周期页可查看最新通知事件',
        ],
        pending_items=[
            '冷却、合并、重试、去噪规则仍可继续增强',
        ],
        acceptance_criteria=[
            '关键事件需能落库并在需要时发送飞书',
            '通知状态需可审计',
        ],
        latest_validation=[
            'tests/unit/test_event_notifications.py 与 test_notifications.py 通过',
            'run-and-notify / notify-latest 已具备真实发送路径',
        ],
        risks=['外部 webhook 与网络环境可能导致发送失败。'],
        next_actions=['补充更细的失败重试和冷却策略。'],
    ),
    ProjectModuleStatus(
        id='review',
        name='复盘与审批',
        prd_section='§9',
        relation='是策略闭环优化的入口，负责把交易结果反哺为待审批变更。',
        impact='影响 suggested_change、audit_log、策略持续迭代的可信度。',
        goal='支持归档复盘、建议变更、审批决策与审计记录。',
        status='可用',
        completion_pct=80,
        user_visible='archive-review、review-queue、review-decision、UI 待审批变更',
        completed_items=[
            'review queue / decision CLI 已落地',
            'review_pending 事件联动已完成',
            '待审批变更可在 UI 查看',
        ],
        pending_items=[
            '审批通过后的自动写回配置仍未封口',
            '复盘报告模板和收益归因仍可继续增强',
        ],
        acceptance_criteria=[
            '卖出后可形成待审批变更并支持审批/拒绝',
            '审批动作应留下审计记录',
        ],
        latest_validation=[
            'tests/unit/test_review_workflow.py 通过',
            'review-queue / review-decision 命令可执行',
        ],
        risks=['当前变更应用仍以人工确认和后续配置处理为主。'],
        next_actions=['实现审批后自动写回配置的安全版本。'],
    ),
    ProjectModuleStatus(
        id='schedule_ops',
        name='调度与自检',
        prd_section='§10',
        relation='保障系统在真实使用场景下可周期运行、可自检、可降级。',
        impact='影响系统连续运行能力、日报周报产出和异常发现效率。',
        goal='支持定时运行、故障告警、系统自检和基础降级执行。',
        status='可用',
        completion_pct=84,
        user_visible='doctor、scheduled_job、launchd/plist、通知与定时配置页',
        completed_items=[
            'doctor / smoke-test / scheduled_job 已落地',
            '本地定时脚本和 plist 已存在',
            'UI 可修改通知与定时配置',
        ],
        pending_items=[
            '更完整的异常分级与自动恢复策略仍可增强',
        ],
        acceptance_criteria=[
            '系统应可自检并支持定时触发主流程',
            '失败场景至少要有结构化错误输出或通知',
        ],
        latest_validation=[
            'tests/unit/test_schedule.py 通过',
            'doctor 和 scheduled 路径已有真实回归记录',
        ],
        risks=['本地调度依赖用户机器环境持续在线。'],
        next_actions=['完善定时任务运行看板和失败追踪。'],
    ),
    ProjectModuleStatus(
        id='product_surface',
        name='UI / CLI 产品形态',
        prd_section='交付形态覆盖全 PRD',
        relation='是用户感知项目进展和直接使用产品的统一入口。',
        impact='决定用户是否真正“看得到、用得上、感知到进度”。',
        goal='让用户能通过 CLI/Streamlit 看到结果、执行动作、理解系统状态。',
        status='可用',
        completion_pct=88,
        user_visible='Streamlit 页面、CLI 命令集、README 启动方式',
        completed_items=[
            '已有总览 / 候选列表 / 生命周期 / 交易动作 / 策略配置 / 通知与定时页面',
            'CLI 已覆盖筛选、研究、排名、交易、复盘、诊断等主干动作',
            '用户现在可直接预览和操作产品',
        ],
        pending_items=[
            '缺少一个统一的“项目总盘/进度总盘”页面与命令',
        ],
        acceptance_criteria=[
            '用户无需读代码即可启动和使用主要能力',
            '关键运行结果与状态应有统一可见入口',
        ],
        latest_validation=[
            'zsh scripts/run_ui.sh 可运行 UI',
            'CLI --help 与现有主命令可用',
        ],
        risks=['如果没有进度总盘，用户仍然会感到“做了很多但看不见”。'],
        next_actions=['本轮补齐项目总盘文档、CLI 和 UI 可视化入口。'],
    ),
    ProjectModuleStatus(
        id='quality_docs',
        name='测试、回归与交付文档',
        prd_section='§11',
        relation='是产品能否达到“开箱即用、可商用交付”的收口层。',
        impact='影响交付可信度、后续迭代安全性和用户 onboarding 成本。',
        goal='通过自动化测试、核验报告和使用文档证明系统当前可交付状态。',
        status='可用',
        completion_pct=90,
        user_visible='README、PRODUCT-DELIVERY、PRD-BASELINE-VERIFICATION、tests',
        completed_items=[
            'README 和 PRODUCT-DELIVERY 已覆盖运行入口与验收方式',
            'PRD 核验文档已沉淀',
            '当前全量单测已达 82 项通过',
        ],
        pending_items=[
            '需要把“真实进度”和“交付完成度”用总盘统一呈现，避免文档分散',
        ],
        acceptance_criteria=[
            '关键功能需有自动化测试覆盖',
            '交付文档需支持用户按步骤启动、核验和理解边界',
        ],
        latest_validation=[
            "python3 -m unittest discover -s tests/unit -p 'test_*.py' 通过（82 tests）",
        ],
        risks=['文档过于分散时，用户仍然很难快速判断整体进展。'],
        next_actions=['新增统一总盘文档并纳入 README / UI / CLI。'],
    ),
]


def get_project_modules() -> list[dict[str, Any]]:
    return [
        {
            'id': module.id,
            'name': module.name,
            'prd_section': module.prd_section,
            'relation': module.relation,
            'impact': module.impact,
            'goal': module.goal,
            'status': module.status,
            'completion_pct': module.completion_pct,
            'user_visible': module.user_visible,
            'completed_items': list(module.completed_items),
            'pending_items': list(module.pending_items),
            'acceptance_criteria': list(module.acceptance_criteria),
            'latest_validation': list(module.latest_validation),
            'risks': list(module.risks),
            'next_actions': list(module.next_actions),
        }
        for module in MODULES
    ]


def get_project_master_board() -> dict[str, Any]:
    modules = get_project_modules()
    overall_completion = round(sum(item['completion_pct'] for item in modules) / len(modules), 1) if modules else 0.0
    delivered_count = sum(1 for item in modules if item['status'] == '已交付')
    usable_count = sum(1 for item in modules if item['status'] in {'已交付', '可用', '待优化'})
    top_risks: list[str] = []
    for item in modules:
        for risk in item['risks']:
            if risk not in top_risks:
                top_risks.append(risk)
    next_focus = [
        '补齐项目总盘的 CLI/UI 可见入口，解决“进度不可感知”问题',
        '继续向 PRD 完整规则收口：研究队列、通知治理、复盘自动写回',
        '增强评分/技术面/持仓运营的解释性看板',
    ]
    milestone_view = [
        {'milestone': '基础可运行', 'status': '已完成', 'description': '筛选、落库、通知、UI、自检已可直接运行'},
        {'milestone': '研究闭环可运行', 'status': '已完成', 'description': '研究、评分、技术面、队列、诊断主干可运行'},
        {'milestone': '交易闭环可运行', 'status': '已完成主干', 'description': 'buy/track/exit/sell/review 主干已可操作'},
        {'milestone': '运营可观测', 'status': '开发中', 'description': '已有生命周期页和通知事件，现补总盘/进度总览'},
        {'milestone': '商用收口', 'status': '开发中', 'description': '继续收口 PRD 细则、治理策略和自动回写'},
    ]
    return {
        'project_name': '美股选股体系',
        'baseline_document': 'PRD-开发基线版.md',
        'overall_completion_pct': overall_completion,
        'module_count': len(modules),
        'delivered_count': delivered_count,
        'usable_count': usable_count,
        'modules': modules,
        'top_risks': top_risks[:8],
        'next_focus': next_focus,
        'milestones': milestone_view,
        'status_summary': '当前已形成可直接使用的基线闭环产品；正在补齐“项目总盘 + 进度可视化 + PRD 细则收口”。',
    }


def render_master_board_markdown(board: dict[str, Any] | None = None) -> str:
    board = board or get_project_master_board()
    lines: list[str] = []
    lines.append('# 项目总盘（自动生成）')
    lines.append('')
    lines.append(f"- 项目：{board['project_name']}")
    lines.append(f"- 开发基线：`{board['baseline_document']}`")
    lines.append(f"- 整体完成度：**{board['overall_completion_pct']}%**")
    lines.append(f"- 模块数：**{board['module_count']}**，已交付：**{board['delivered_count']}**，可用及以上：**{board['usable_count']}**")
    lines.append(f"- 当前判断：{board['status_summary']}")
    lines.append('')
    lines.append('## 一、总盘概览')
    lines.append('')
    lines.append('| 模块 | PRD 对应 | 当前状态 | 完成度 | 用户可感知形态 | 下一步 |')
    lines.append('|---|---|---:|---:|---|---|')
    for module in board['modules']:
        next_step = module['next_actions'][0] if module['next_actions'] else '-'
        lines.append(
            f"| {module['name']} | {module['prd_section']} | {module['status']} | {module['completion_pct']}% | {module['user_visible']} | {next_step} |"
        )
    lines.append('')
    lines.append('## 二、里程碑视图')
    lines.append('')
    for item in board['milestones']:
        lines.append(f"- **{item['milestone']}**：{item['status']} —— {item['description']}")
    lines.append('')
    lines.append('## 三、模块进度明细')
    lines.append('')
    for module in board['modules']:
        lines.append(f"### {module['name']}")
        lines.append(f"- 与主体关联性：{module['relation']}")
        lines.append(f"- 和其他功能的影响：{module['impact']}")
        lines.append(f"- 详细描述：{module['goal']}")
        lines.append(f"- 当前状态：**{module['status']}**（{module['completion_pct']}%）")
        lines.append(f"- 用户可直接感知：{module['user_visible']}")
        lines.append('- 已完成：')
        for item in module['completed_items']:
            lines.append(f"  - {item}")
        lines.append('- 待完成 / 待优化：')
        for item in module['pending_items']:
            lines.append(f"  - {item}")
        lines.append('- 验收标准：')
        for item in module['acceptance_criteria']:
            lines.append(f"  - {item}")
        lines.append('- 最近核验结果：')
        for item in module['latest_validation']:
            lines.append(f"  - {item}")
        lines.append('- 风险：')
        for item in module['risks']:
            lines.append(f"  - {item}")
        lines.append('- 下一步：')
        for item in module['next_actions']:
            lines.append(f"  - {item}")
        lines.append('')
    lines.append('## 四、当前主要风险')
    lines.append('')
    for risk in board['top_risks']:
        lines.append(f'- {risk}')
    lines.append('')
    lines.append('## 五、当前下一阶段重点')
    lines.append('')
    for item in board['next_focus']:
        lines.append(f'- {item}')
    lines.append('')
    return '\n'.join(lines)


def render_master_board_text(board: dict[str, Any] | None = None) -> str:
    board = board or get_project_master_board()
    lines: list[str] = []
    lines.append('美股选股体系｜项目总盘')
    lines.append(f"整体完成度: {board['overall_completion_pct']}% | 模块: {board['module_count']} | 已交付: {board['delivered_count']} | 可用及以上: {board['usable_count']}")
    lines.append(f"当前判断: {board['status_summary']}")
    lines.append('')
    for module in board['modules']:
        lines.append(f"[{module['status']}] {module['name']} ({module['completion_pct']}%)")
        lines.append(f"  PRD: {module['prd_section']}")
        lines.append(f"  目标: {module['goal']}")
        lines.append(f"  可感知: {module['user_visible']}")
        if module['latest_validation']:
            lines.append(f"  核验: {module['latest_validation'][0]}")
        if module['next_actions']:
            lines.append(f"  下一步: {module['next_actions'][0]}")
        lines.append('')
    return '\n'.join(lines)
