from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure src/ is on the path when running from repo root (e.g. Streamlit Cloud)
_src = Path(__file__).parent / "src"
if _src.exists() and str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

import streamlit as st

# Inject Streamlit Cloud secrets into os.environ so existing os.getenv() calls work.
# When running locally, .env (loaded by python-dotenv) takes precedence.
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, str) and _k not in os.environ:
            os.environ[_k] = _v
except Exception:
    pass

from us_stock_research.config import DEFAULT_STRATEGY_NAME, ProjectPaths, list_strategy_names
from us_stock_research.config_store import save_app_config_data, save_strategy_config_data
from us_stock_research.fmp_client import FMPClientError
from us_stock_research.notifications import build_notification_lines, build_notification_text
from us_stock_research.portfolio_workflow import archive_after_review, record_buy, record_sell, trigger_exit_watch
from us_stock_research.service import ScreeningServiceError, run_screening
from us_stock_research.tracking_workflow import refresh_holding_tracking
from us_stock_research.ui_data import (
    acknowledge_alert,
    app_config_form_defaults,
    apply_app_config_form_values,
    apply_strategy_form_values,
    get_candidate_pool,
    get_historical_trades,
    get_portfolio_view,
    get_stock_detail,
    get_stock_notes,
    load_dashboard_bundle,
    load_project_master_board,
    load_research_diagnostics,
    mark_user_status,
    resolve_alert,
    set_stock_notes,
    strategy_form_defaults,
)


st.set_page_config(page_title='美股选股体系', page_icon='📈', layout='wide')

paths = ProjectPaths()
strategies = list_strategy_names(paths)
if not strategies:
    st.error('未找到任何策略配置，请先检查 config/strategies。')
    st.stop()

try:
    default_index = strategies.index(DEFAULT_STRATEGY_NAME)
except ValueError:
    default_index = 0

selected_strategy = st.sidebar.selectbox('策略', strategies, index=default_index)

if st.sidebar.button('立即运行筛选', use_container_width=True):
    try:
        latest_bundle = load_dashboard_bundle(selected_strategy, paths)
        strategy = latest_bundle['strategy']
        top_n = int(strategy.get('ranking', {}).get('top_n', 10))
        result = run_screening(selected_strategy, top_n=top_n, paths=paths)
        st.session_state['ui_success'] = f"筛选完成：{result.get('stockCount', 0)} 只股票"
        st.rerun()
    except (FMPClientError, ScreeningServiceError, FileNotFoundError, ValueError) as exc:
        st.session_state['ui_error'] = str(exc)
        st.rerun()

if st.session_state.get('ui_success'):
    st.success(st.session_state.pop('ui_success'))
if st.session_state.get('ui_error'):
    st.error(st.session_state.pop('ui_error'))

bundle = load_dashboard_bundle(selected_strategy, paths)
latest = bundle['latest']
summary = bundle['summary']
rows = bundle['rows']
strategy = bundle['strategy']
app_config = bundle['app_config']
lifecycle = bundle['lifecycle']
research_diagnostics = load_research_diagnostics(paths)
project_board = load_project_master_board()

st.title('美股选股体系')
st.caption('展示最近结果、维护生命周期、修改关键策略参数，并维护飞书通知与定时配置。')

board_tab, overview_tab, candidate_pool_tab, portfolio_tab, trades_tab, detail_tab, candidates_tab, lifecycle_tab, actions_tab, strategy_tab, notifications_tab = st.tabs(
    ['项目总盘', '总览', '候选池', '持仓', '历史交易', '个股详情', '候选列表', '生命周期', '交易动作', '策略配置', '通知与定时']
)


with board_tab:
    bcol1, bcol2, bcol3, bcol4 = st.columns(4)
    bcol1.metric('整体完成度', f"{project_board['overall_completion_pct']}%")
    bcol2.metric('模块数', project_board['module_count'])
    bcol3.metric('已交付', project_board['delivered_count'])
    bcol4.metric('可用及以上', project_board['usable_count'])

    st.subheader('项目当前判断')
    st.write(project_board['status_summary'])

    st.subheader('模块总览')
    board_rows = [
        {
            '模块': item['name'],
            'PRD': item['prd_section'],
            '状态': item['status'],
            '完成度': f"{item['completion_pct']}%",
            '用户可感知形态': item['user_visible'],
            '下一步': item['next_actions'][0] if item['next_actions'] else '',
        }
        for item in project_board['modules']
    ]
    st.dataframe(board_rows, use_container_width=True, hide_index=True)

    st.subheader('里程碑视图')
    st.dataframe(project_board['milestones'], use_container_width=True, hide_index=True)

    st.subheader('当前主要风险')
    for risk in project_board['top_risks']:
        st.markdown(f'- {risk}')

    st.subheader('模块进度明细')
    for item in project_board['modules']:
        with st.expander(f"{item['name']}｜{item['status']}｜{item['completion_pct']}%", expanded=False):
            st.markdown(f"**PRD 对应**：{item['prd_section']}")
            st.markdown(f"**与主体关联性**：{item['relation']}")
            st.markdown(f"**和其他功能的影响**：{item['impact']}")
            st.markdown(f"**详细描述**：{item['goal']}")
            st.markdown(f"**用户可直接感知**：{item['user_visible']}")
            st.markdown('**已完成**')
            for sub in item['completed_items']:
                st.markdown(f'- {sub}')
            st.markdown('**待完成 / 待优化**')
            for sub in item['pending_items']:
                st.markdown(f'- {sub}')
            st.markdown('**验收标准**')
            for sub in item['acceptance_criteria']:
                st.markdown(f'- {sub}')
            st.markdown('**最近核验结果**')
            for sub in item['latest_validation']:
                st.markdown(f'- {sub}')
            st.markdown('**风险**')
            for sub in item['risks']:
                st.markdown(f'- {sub}')
            st.markdown('**下一步**')
            for sub in item['next_actions']:
                st.markdown(f'- {sub}')

with overview_tab:
    metric_col1, metric_col2, metric_col3 = st.columns(3)
    metric_col1.metric('最近运行时间', summary['generated_at'])
    metric_col2.metric('候选数量', summary['stock_count'])
    metric_col3.metric('当前策略', summary['strategy_name'])

    st.subheader('输出文件')
    st.write(f"Markdown 报告：`{summary['report_path'] or '暂无'}`")
    st.write(f"JSON 结果：`{summary['json_path'] or '暂无'}`")
    st.write(f"候选清单：`{summary['watchlist_path'] or '暂无'}`")

    st.subheader('Top 3 摘要')
    if rows:
        st.dataframe(rows[:3], use_container_width=True, hide_index=True)
    else:
        st.info('暂无运行结果，先点击左侧“立即运行筛选”。')


with candidate_pool_tab:
    st.subheader('候选池')
    candidate_filters_col1, candidate_filters_col2, candidate_filters_col3 = st.columns(3)
    candidate_strategy = candidate_filters_col1.text_input('按策略筛选')
    candidate_user_status = candidate_filters_col2.selectbox('按用户状态筛选', ['全部', 'watching', 'ignored', 'held', 'closed'])
    candidate_research_status = candidate_filters_col3.selectbox('按研究状态筛选', ['全部', '未研究', '已研究', '降级研究', '研究失败', '复用', '待研究'])
    candidate_pool = get_candidate_pool(
        filters={
            'strategy': candidate_strategy.strip() or None,
            'user_status': None if candidate_user_status == '全部' else candidate_user_status,
            'research_status': None if candidate_research_status == '全部' else candidate_research_status,
        },
        paths=paths,
    )
    if candidate_pool:
        st.dataframe(candidate_pool, use_container_width=True, hide_index=True)
        with st.form('candidate-status-form'):
            status_symbol = st.text_input('更新候选池用户状态代码').upper().strip()
            new_status = st.selectbox('新用户状态', ['watching', 'ignored', 'held', 'closed'])
            submit_status = st.form_submit_button('更新状态', use_container_width=True)
        if submit_status:
            try:
                mark_user_status(status_symbol, new_status, paths=paths)
                st.success(f'{status_symbol} 状态已更新为 {new_status}')
            except Exception as exc:
                st.error(str(exc))
    else:
        st.info('暂无候选池数据。')

with portfolio_tab:
    st.subheader('持仓视图')
    portfolio_view = get_portfolio_view(paths=paths)
    summary_cards = st.columns(7)
    summary_cards[0].metric('持仓数', portfolio_view['summary']['total_positions'])
    summary_cards[1].metric('需操作', portfolio_view['summary']['need_action_count'])
    summary_cards[2].metric('需关注', portfolio_view['summary']['need_attention_count'])
    summary_cards[3].metric('正常', portfolio_view['summary']['normal_count'])
    summary_cards[4].metric('总投入', portfolio_view['summary']['total_invested'])
    summary_cards[5].metric('未实现盈亏', portfolio_view['summary']['total_unrealized_pnl'])
    summary_cards[6].metric('未实现盈亏%', portfolio_view['summary']['total_unrealized_pnl_pct'])
    for section in portfolio_view['sections']:
        st.markdown(f"### {section['label']}")
        if section['items']:
            st.dataframe(section['items'], use_container_width=True, hide_index=True)
        else:
            st.info(f"{section['label']}暂无股票。")

with trades_tab:
    st.subheader('历史交易')
    historical_trades = get_historical_trades(paths=paths)
    if historical_trades:
        st.dataframe(historical_trades, use_container_width=True, hide_index=True)
    else:
        st.info('暂无已完成历史交易。')

with detail_tab:
    st.subheader('个股详情')
    detail_symbol = st.text_input('输入股票代码查看详情').upper().strip()
    if detail_symbol:
        detail = get_stock_detail(detail_symbol, paths=paths)
        st.markdown('### 基础信息')
        st.json(detail['basic'])
        st.markdown('### 命中记录')
        st.dataframe(detail['hit_history'], use_container_width=True, hide_index=True)
        st.markdown('### 最新研究')
        st.json(detail['latest_research'])
        st.markdown('### 研究历史')
        st.dataframe(detail['research_history'], use_container_width=True, hide_index=True)
        st.markdown('### 预警记录')
        st.dataframe(detail['alerts'], use_container_width=True, hide_index=True)
        st.markdown('### 交易记录')
        st.dataframe(detail['trades'], use_container_width=True, hide_index=True)
        st.markdown('### 持仓情况')
        st.json(detail['position'])
        current_notes = get_stock_notes(detail_symbol, paths=paths) or ''
        with st.form('stock-notes-form'):
            updated_notes = st.text_area('用户备注', value=current_notes)
            save_notes = st.form_submit_button('保存备注', use_container_width=True)
        if save_notes:
            set_stock_notes(detail_symbol, updated_notes, paths=paths)
            st.success('备注已保存')
        if detail['alerts']:
            with st.form('alert-actions-form'):
                alert_id = st.number_input('预警 ID', min_value=1, step=1)
                alert_action = st.selectbox('预警操作', ['acknowledge', 'resolve'])
                submit_alert = st.form_submit_button('执行预警操作', use_container_width=True)
            if submit_alert:
                try:
                    if alert_action == 'acknowledge':
                        acknowledge_alert(int(alert_id), paths=paths)
                    else:
                        resolve_alert(int(alert_id), paths=paths)
                    st.success('预警操作已执行')
                except Exception as exc:
                    st.error(str(exc))
    else:
        st.info('输入股票代码后可查看候选/持仓/研究/预警/交易详情。')

with candidates_tab:
    st.subheader('最新候选列表')
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info('暂无结果可展示。')

with lifecycle_tab:
    metric1, metric2, metric3, metric4 = st.columns(4)
    metric1.metric('活跃股票', lifecycle['totals']['active_count'])
    metric2.metric('研究队列', lifecycle['totals']['research_queue_count'])
    metric3.metric('待审批变更', lifecycle['totals']['review_queue_count'])
    metric4.metric('最新通知数', lifecycle['totals']['notification_count'])

    st.subheader('生命周期状态分布')
    if lifecycle['state_counts']:
        st.dataframe(lifecycle['state_counts'], use_container_width=True, hide_index=True)
    else:
        st.info('暂无生命周期数据。')

    st.subheader('研究队列')
    if lifecycle['research_queue']:
        st.dataframe(lifecycle['research_queue'], use_container_width=True, hide_index=True)
    else:
        st.info('当前研究队列为空。')

    st.subheader('待审批变更')
    if lifecycle['review_queue']:
        st.dataframe(lifecycle['review_queue'], use_container_width=True, hide_index=True)
    else:
        st.info('当前没有待审批变更。')

    st.subheader('最新通知事件')
    if lifecycle['notifications']:
        st.dataframe(lifecycle['notifications'], use_container_width=True, hide_index=True)
    else:
        st.info('暂无通知事件。')

    st.subheader('最新研究结果')
    if lifecycle['research_results']:
        st.dataframe(lifecycle['research_results'], use_container_width=True, hide_index=True)
    else:
        st.info('暂无研究结果。')

    st.subheader('研究新鲜度与触发建议')
    dcol1, dcol2 = st.columns(2)
    dcol1.metric('跟踪股票数', research_diagnostics['tracked_symbol_count'])
    dcol2.metric('建议重触发', research_diagnostics['needs_trigger_count'])
    if research_diagnostics['rows']:
        st.dataframe(research_diagnostics['rows'], use_container_width=True, hide_index=True)
    else:
        st.info('暂无研究诊断数据。')

    st.subheader('活跃生命周期股票')
    if lifecycle['active_rows']:
        st.dataframe(lifecycle['active_rows'], use_container_width=True, hide_index=True)
    else:
        st.info('暂无 waiting_for_setup / buy_ready / holding / exit_watch 股票。')

with actions_tab:
    st.subheader('手动生命周期动作')
    action_col1, action_col2 = st.columns(2)

    with action_col1.form('buy-form'):
        buy_symbol = st.text_input('买入代码').upper().strip()
        buy_price = st.number_input('买入价格', min_value=0.0, value=0.0, step=0.01)
        buy_qty = st.number_input('买入数量', min_value=0.0, value=0.0, step=1.0)
        buy_notes = st.text_input('买入备注')
        buy_submitted = st.form_submit_button('录入买入', use_container_width=True)
    if buy_submitted:
        try:
            record_buy(symbol=buy_symbol, price=buy_price, quantity=buy_qty, notes=buy_notes, paths=paths)
            st.success(f'{buy_symbol} 已转入 holding')
        except Exception as exc:
            st.error(str(exc))

    with action_col2.form('exit-form'):
        exit_symbol = st.text_input('触发卖点代码').upper().strip()
        exit_reason = st.text_input('卖点原因')
        exit_submitted = st.form_submit_button('触发 exit_watch', use_container_width=True)
    if exit_submitted:
        try:
            trigger_exit_watch(symbol=exit_symbol, reason=exit_reason, paths=paths)
            st.success(f'{exit_symbol} 已转入 exit_watch')
        except Exception as exc:
            st.error(str(exc))

    action_col3, action_col4 = st.columns(2)
    with action_col3.form('sell-form'):
        sell_symbol = st.text_input('卖出代码').upper().strip()
        sell_price = st.number_input('卖出价格', min_value=0.0, value=0.0, step=0.01)
        sell_qty = st.number_input('卖出数量', min_value=0.0, value=0.0, step=1.0)
        sell_notes = st.text_input('卖出备注')
        sell_submitted = st.form_submit_button('录入卖出', use_container_width=True)
    if sell_submitted:
        try:
            record_sell(symbol=sell_symbol, price=sell_price, quantity=sell_qty, notes=sell_notes, paths=paths)
            st.success(f'{sell_symbol} 已转入 exited')
        except Exception as exc:
            st.error(str(exc))

    with action_col4.form('archive-form'):
        archive_symbol = st.text_input('归档代码').upper().strip()
        archive_summary = st.text_area('复盘摘要')
        archive_outcome = st.text_input('复盘结论', value='completed')
        archive_submitted = st.form_submit_button('归档复盘', use_container_width=True)
    if archive_submitted:
        try:
            archive_after_review(symbol=archive_symbol, summary=archive_summary, outcome=archive_outcome, paths=paths)
            st.success(f'{archive_symbol} 已归档')
        except Exception as exc:
            st.error(str(exc))

    st.subheader('持仓跟踪刷新')
    track_symbol = st.text_input('跟踪指定持仓代码（留空表示不执行）').upper().strip()
    if st.button('刷新持仓跟踪', use_container_width=True):
        if not track_symbol:
            st.info('请输入 holding 状态股票代码。')
        else:
            try:
                result = refresh_holding_tracking(symbol=track_symbol, paths=paths)
                st.json(result)
            except Exception as exc:
                st.error(str(exc))

with strategy_tab:
    st.subheader('策略关键参数')
    defaults = strategy_form_defaults(strategy)
    with st.form('strategy-config-form'):
        col1, col2 = st.columns(2)
        screen_limit = col1.number_input('筛选上限', min_value=1, value=defaults['screen_limit'], step=1)
        top_n = col2.number_input('保留候选数', min_value=1, value=defaults['top_n'], step=1)

        market_cap_min = col1.number_input('最小市值', min_value=0, value=defaults['market_cap_min'], step=1000000)
        market_cap_max = col2.number_input('最大市值', min_value=0, value=defaults['market_cap_max'], step=1000000)

        volume_min = col1.number_input('最小成交量', min_value=0, value=defaults['volume_min'], step=1000)
        sector = col2.text_input('行业', value=defaults['sector'])
        exchange = col1.text_input('交易所', value=defaults['exchange'])

        max_pe = col2.number_input('最大 PE', min_value=0.0, value=float(defaults['max_pe']), step=0.5)
        max_pb = col1.number_input('最大 PB', min_value=0.0, value=float(defaults['max_pb']), step=0.1)
        min_valuation_score = col2.number_input(
            '最小估值得分', min_value=0.0, value=float(defaults['min_valuation_score']), step=0.5
        )
        min_roe_for_quality = col1.number_input(
            '质量线最小 ROE', min_value=0.0, value=float(defaults['min_roe_for_quality']), step=0.01, format='%.2f'
        )

        submitted = st.form_submit_button('保存策略配置', use_container_width=True)

    if submitted:
        values = {
            'screen_limit': screen_limit,
            'market_cap_min': market_cap_min,
            'market_cap_max': market_cap_max,
            'volume_min': volume_min,
            'sector': sector,
            'exchange': exchange,
            'top_n': top_n,
            'max_pe': max_pe,
            'max_pb': max_pb,
            'min_valuation_score': min_valuation_score,
            'min_roe_for_quality': min_roe_for_quality,
        }
        updated = apply_strategy_form_values(strategy, values)
        save_strategy_config_data(selected_strategy, updated, paths)
        st.session_state['ui_success'] = '策略配置已保存'
        st.rerun()

    st.caption(f"配置文件：{paths.strategy_dir / f'{selected_strategy}.yaml'}")

with notifications_tab:
    st.subheader('飞书通知与定时任务')
    defaults = app_config_form_defaults(app_config)

    with st.form('app-config-form'):
        col1, col2 = st.columns(2)
        feishu_enabled = col1.checkbox('启用飞书通知', value=defaults['feishu_enabled'])
        digest_mode = col2.selectbox(
            '摘要模式',
            options=['top3_only', 'full_watchlist'],
            index=0 if defaults['digest_mode'] == 'top3_only' else 1,
        )
        feishu_webhook_url = st.text_input('飞书 Webhook URL', value=defaults['feishu_webhook_url'], type='password')

        schedule_enabled = col1.checkbox('启用定时任务', value=defaults['schedule_enabled'])
        schedule_top_n = col2.number_input('定时任务 Top N', min_value=1, value=defaults['schedule_top_n'], step=1)
        schedule_cron = col1.text_input('Cron 表达式', value=defaults['schedule_cron'])
        schedule_timezone = col2.text_input('时区', value=defaults['schedule_timezone'])
        schedule_strategy = st.selectbox(
            '定时运行策略',
            options=strategies,
            index=strategies.index(defaults['schedule_strategy']) if defaults['schedule_strategy'] in strategies else default_index,
        )

        st.markdown('### Perplexity 深度研究')
        pcol1, pcol2 = st.columns(2)
        perplexity_enabled = pcol1.checkbox('启用 Perplexity 研究', value=defaults['perplexity_enabled'])
        perplexity_fallback_to_derived = pcol2.checkbox('失败时回退到派生研究', value=defaults['perplexity_fallback_to_derived'])
        perplexity_prompt_template_id = pcol1.text_input('Prompt 模板 ID', value=defaults['perplexity_prompt_template_id'])
        perplexity_prompt_version = pcol2.text_input('Prompt 版本', value=defaults['perplexity_prompt_version'])

        submitted = st.form_submit_button('保存通知与定时配置', use_container_width=True)

    if submitted:
        values = {
            'feishu_enabled': feishu_enabled,
            'feishu_webhook_url': feishu_webhook_url,
            'digest_mode': digest_mode,
            'schedule_enabled': schedule_enabled,
            'schedule_cron': schedule_cron,
            'schedule_timezone': schedule_timezone,
            'schedule_strategy': schedule_strategy,
            'schedule_top_n': schedule_top_n,
            'perplexity_enabled': perplexity_enabled,
            'perplexity_prompt_template_id': perplexity_prompt_template_id,
            'perplexity_prompt_version': perplexity_prompt_version,
            'perplexity_fallback_to_derived': perplexity_fallback_to_derived,
        }
        updated = apply_app_config_form_values(app_config, values)
        save_app_config_data(updated, paths)
        st.session_state['ui_success'] = '通知与定时配置已保存'
        st.rerun()

    st.caption(f'配置文件：{paths.app_config_path}')

    st.info('Perplexity API Key 通过 .env / 环境变量注入；UI 只控制是否启用、Prompt 版本和失败回退策略。')

    st.subheader('通知预览')
    if latest:
        preview_lines = build_notification_lines(latest, digest_mode=defaults['digest_mode'], paths=paths)
        summary_lines: list[str] = []
        detail_lines: list[str] = []
        attachment_lines: list[str] = []
        section = 'summary'
        for line in preview_lines:
            if line == '详细报告摘要':
                section = 'detail'
            elif line == '补充落盘位置':
                section = 'attachment'

            if section == 'summary':
                summary_lines.append(line)
            elif section == 'detail':
                detail_lines.append(line)
            else:
                attachment_lines.append(line)

        st.markdown('### 飞书卡片预览')
        if summary_lines:
            st.info('\n'.join(summary_lines))
        if detail_lines:
            st.markdown('### 详细分析预览')
            st.code('\n'.join(detail_lines), language='text')
        if attachment_lines:
            st.markdown('### 落盘文件')
            st.caption('\n'.join(attachment_lines))

        with st.expander('查看完整原始通知文本'):
            preview = build_notification_text(latest, digest_mode=defaults['digest_mode'], paths=paths)
            st.code(preview, language='text')
    else:
        st.info('暂无最近结果，通知预览会在运行一次筛选后显示。')
