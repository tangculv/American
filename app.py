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
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, str) and _k not in os.environ:
            os.environ[_k] = _v
except Exception:
    pass

from us_stock_research.config import DEFAULT_STRATEGY_NAME, ProjectPaths, list_strategy_names
from us_stock_research.config_store import save_app_config_data, save_strategy_config_data
from us_stock_research.fmp_client import FMPClientError
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
    load_research_diagnostics,
    mark_user_status,
    resolve_alert,
    set_stock_notes,
    strategy_form_defaults,
)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Helper: safely flush notifications after UI actions
# ---------------------------------------------------------------------------
def _flush_notifications():
    """Send all pending notifications. Called after buy/sell/screening actions."""
    try:
        from us_stock_research.event_notifications import flush_pending_notifications
        flush_pending_notifications(paths=paths)
    except Exception:
        pass


def _safe_save_yaml(save_fn, *args, **kwargs):
    """Attempt to save YAML config; gracefully handle read-only filesystem."""
    try:
        return save_fn(*args, **kwargs)
    except OSError as exc:
        st.error(f'配置保存失败（文件系统只读）：{exc}')
        st.info('如果在 Streamlit Cloud 上运行，配置文件无法修改。请在本地环境中调整配置后重新部署。')
        return None


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
st.sidebar.title('📈 美股选股')
selected_strategy = st.sidebar.selectbox('当前策略', strategies, index=default_index)

if st.sidebar.button('🔍 运行筛选', use_container_width=True):
    try:
        latest_bundle = load_dashboard_bundle(selected_strategy, paths)
        strategy = latest_bundle['strategy']
        top_n = int(strategy.get('ranking', {}).get('top_n', 10))
        result = run_screening(selected_strategy, top_n=top_n, paths=paths)
        _flush_notifications()
        st.session_state['ui_success'] = f"筛选完成：{result.get('stockCount', 0)} 只股票"
        st.rerun()
    except (FMPClientError, ScreeningServiceError, FileNotFoundError, ValueError) as exc:
        st.session_state['ui_error'] = str(exc)
        st.rerun()

if st.session_state.get('ui_success'):
    st.sidebar.success(st.session_state.pop('ui_success'))
if st.session_state.get('ui_error'):
    st.sidebar.error(st.session_state.pop('ui_error'))

# ---------------------------------------------------------------------------
# Load data (shared across tabs)
# ---------------------------------------------------------------------------
bundle = load_dashboard_bundle(selected_strategy, paths)
latest = bundle['latest']
summary = bundle['summary']
rows = bundle['rows']
strategy = bundle['strategy']
app_config = bundle['app_config']
lifecycle = bundle['lifecycle']

# ---------------------------------------------------------------------------
# Tabs — 5 tabs, grouped by user workflow
# ---------------------------------------------------------------------------
dashboard_tab, screening_tab, portfolio_tab, detail_tab, settings_tab = st.tabs(
    ['📊 仪表盘', '🔍 筛选与研究', '💼 持仓管理', '📋 个股详情', '⚙️ 设置']
)


# ===========================================================================
# TAB 1: 仪表盘
# ===========================================================================
with dashboard_tab:
    st.header('仪表盘')

    # Key metrics row
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric('最近筛选', summary['generated_at'])
    m2.metric('候选数量', summary['stock_count'])
    m3.metric('持仓数', lifecycle['totals']['active_count'])
    m4.metric('研究队列', lifecycle['totals']['research_queue_count'])
    m5.metric('通知事件', lifecycle['totals']['notification_count'])

    # Top 3
    st.subheader('Top 3 候选股')
    if rows:
        st.dataframe(rows[:3], use_container_width=True, hide_index=True)
    else:
        st.info('暂无筛选结果。点击左侧「运行筛选」开始。')

    # Recent notifications
    st.subheader('最近通知')
    if lifecycle['notifications']:
        st.dataframe(lifecycle['notifications'][:10], use_container_width=True, hide_index=True)
    else:
        st.info('暂无通知记录。')

    # Active holdings quick view
    if lifecycle['active_rows']:
        st.subheader('活跃持仓')
        st.dataframe(lifecycle['active_rows'], use_container_width=True, hide_index=True)


# ===========================================================================
# TAB 2: 筛选与研究
# ===========================================================================
with screening_tab:
    st.header('筛选与研究')

    # --- Candidate pool with filters ---
    st.subheader('候选池')
    f1, f2, f3 = st.columns(3)
    candidate_strategy = f1.text_input('策略名称', key='cand_strategy')
    candidate_user_status = f2.selectbox(
        '用户状态', ['全部', 'watching', 'ignored', 'held', 'closed'], key='cand_ustatus'
    )
    candidate_research_status = f3.selectbox(
        '研究状态', ['全部', '未研究', '已研究', '降级研究', '研究失败', '复用', '待研究'], key='cand_rstatus'
    )
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
            sc1, sc2 = st.columns([2, 1])
            status_symbol = sc1.text_input('股票代码').upper().strip()
            new_status = sc2.selectbox('新状态', ['watching', 'ignored', 'held', 'closed'])
            if st.form_submit_button('更新状态', use_container_width=True):
                try:
                    mark_user_status(status_symbol, new_status, paths=paths)
                    st.success(f'{status_symbol} → {new_status}')
                except Exception as exc:
                    st.error(str(exc))
    else:
        st.info('暂无候选池数据。运行筛选后，命中的股票会出现在这里。')

    st.divider()

    # --- Research queue ---
    st.subheader('研究队列')
    if lifecycle['research_queue']:
        st.dataframe(lifecycle['research_queue'], use_container_width=True, hide_index=True)
    else:
        st.info('研究队列为空。')

    # --- Research diagnostics ---
    research_diagnostics = load_research_diagnostics(paths)
    st.subheader('研究新鲜度')
    d1, d2 = st.columns(2)
    d1.metric('跟踪股票', research_diagnostics['tracked_symbol_count'])
    d2.metric('建议重研究', research_diagnostics['needs_trigger_count'])
    if research_diagnostics['rows']:
        st.dataframe(research_diagnostics['rows'], use_container_width=True, hide_index=True)

    # --- Latest research results ---
    if lifecycle['research_results']:
        st.subheader('最新研究结果')
        st.dataframe(lifecycle['research_results'], use_container_width=True, hide_index=True)


# ===========================================================================
# TAB 3: 持仓管理
# ===========================================================================
with portfolio_tab:
    st.header('持仓管理')

    portfolio_view = get_portfolio_view(paths=paths)
    ps = portfolio_view['summary']

    # Summary cards
    pc1, pc2, pc3, pc4, pc5 = st.columns(5)
    pc1.metric('持仓数', ps['total_positions'])
    pc2.metric('需操作', ps['need_action_count'])
    pc3.metric('需关注', ps['need_attention_count'])
    pc4.metric('总投入', f"${ps['total_invested']:,.0f}" if ps['total_invested'] else '$0')
    pc5.metric('未实现盈亏', f"{ps['total_unrealized_pnl_pct']}%" if ps['total_unrealized_pnl_pct'] else 'N/A')

    # Holdings by section
    for section in portfolio_view['sections']:
        if section['items']:
            st.markdown(f"### {section['label']}")
            st.dataframe(section['items'], use_container_width=True, hide_index=True)

    if not any(s['items'] for s in portfolio_view['sections']):
        st.info('暂无持仓。通过下方「买入」操作录入持仓。')

    st.divider()

    # --- Trade actions ---
    st.subheader('交易操作')
    action_tab_buy, action_tab_sell, action_tab_exit, action_tab_archive, action_tab_refresh = st.tabs(
        ['买入', '卖出', '触发卖点', '归档复盘', '刷新跟踪']
    )

    with action_tab_buy:
        with st.form('buy-form'):
            bc1, bc2, bc3 = st.columns(3)
            buy_symbol = bc1.text_input('代码').upper().strip()
            buy_price = bc2.number_input('价格', min_value=0.0, step=0.01)
            buy_qty = bc3.number_input('数量', min_value=0.0, step=1.0)
            buy_notes = st.text_input('备注')
            if st.form_submit_button('确认买入', use_container_width=True):
                try:
                    record_buy(symbol=buy_symbol, price=buy_price, quantity=buy_qty, notes=buy_notes, paths=paths)
                    _flush_notifications()
                    st.success(f'{buy_symbol} 买入已录入')
                except Exception as exc:
                    st.error(str(exc))

    with action_tab_sell:
        with st.form('sell-form'):
            sc1, sc2, sc3 = st.columns(3)
            sell_symbol = sc1.text_input('代码').upper().strip()
            sell_price = sc2.number_input('价格', min_value=0.0, step=0.01)
            sell_qty = sc3.number_input('数量', min_value=0.0, step=1.0)
            sell_notes = st.text_input('备注')
            if st.form_submit_button('确认卖出', use_container_width=True):
                try:
                    record_sell(symbol=sell_symbol, price=sell_price, quantity=sell_qty, notes=sell_notes, paths=paths)
                    _flush_notifications()
                    st.success(f'{sell_symbol} 卖出已录入')
                except Exception as exc:
                    st.error(str(exc))

    with action_tab_exit:
        with st.form('exit-form'):
            exit_symbol = st.text_input('代码').upper().strip()
            exit_reason = st.text_input('卖点原因')
            if st.form_submit_button('触发 exit_watch', use_container_width=True):
                try:
                    trigger_exit_watch(symbol=exit_symbol, reason=exit_reason, paths=paths)
                    _flush_notifications()
                    st.success(f'{exit_symbol} → exit_watch')
                except Exception as exc:
                    st.error(str(exc))

    with action_tab_archive:
        with st.form('archive-form'):
            archive_symbol = st.text_input('代码').upper().strip()
            archive_summary = st.text_area('复盘摘要')
            archive_outcome = st.text_input('结论', value='completed')
            if st.form_submit_button('归档', use_container_width=True):
                try:
                    archive_after_review(symbol=archive_symbol, summary=archive_summary, outcome=archive_outcome, paths=paths)
                    st.success(f'{archive_symbol} 已归档')
                except Exception as exc:
                    st.error(str(exc))

    with action_tab_refresh:
        track_symbol = st.text_input('持仓代码（需 holding 状态）').upper().strip()
        if st.button('刷新持仓跟踪', use_container_width=True):
            if not track_symbol:
                st.warning('请输入股票代码。')
            else:
                try:
                    result = refresh_holding_tracking(symbol=track_symbol, paths=paths)
                    _flush_notifications()
                    st.json(result)
                except Exception as exc:
                    st.error(str(exc))

    st.divider()

    # --- Historical trades ---
    st.subheader('历史交易')
    historical_trades = get_historical_trades(paths=paths)
    if historical_trades:
        st.dataframe(historical_trades, use_container_width=True, hide_index=True)
    else:
        st.info('暂无已完成交易记录。')


# ===========================================================================
# TAB 4: 个股详情
# ===========================================================================
with detail_tab:
    st.header('个股详情')
    detail_symbol = st.text_input('输入股票代码', key='detail_sym').upper().strip()

    if detail_symbol:
        detail = get_stock_detail(detail_symbol, paths=paths)

        # Basic info in a cleaner layout
        basic = detail['basic']
        st.subheader(f"{basic.get('company_name', detail_symbol)}（{detail_symbol}）")

        bi1, bi2, bi3, bi4 = st.columns(4)
        bi1.metric('当前价格', f"${basic.get('current_price', 'N/A')}")
        bi2.metric('行业', basic.get('sector', 'N/A'))
        bi3.metric('生命周期', basic.get('lifecycle_state', 'N/A'))
        bi4.metric('用户状态', basic.get('user_status', 'N/A'))

        # Research
        st.markdown('#### 最新研究')
        research = detail['latest_research']
        if research and research.get('overall_conclusion'):
            ri1, ri2, ri3 = st.columns(3)
            ri1.metric('投资结论', research.get('overall_conclusion', ''))
            ri2.metric('置信度', research.get('confidence_score', ''))
            ri3.metric('目标价', research.get('target_price_base') or research.get('target_price', 'N/A'))
            if research.get('three_sentence_summary'):
                st.info(research['three_sentence_summary'])
            if research.get('feishu_doc_url'):
                st.markdown(f"[📄 查看完整研究报告]({research['feishu_doc_url']})")
        else:
            st.info('暂无研究数据。')

        # Tabs for sub-sections
        hit_tab, research_hist_tab, alert_tab, trade_tab, position_tab, notes_tab = st.tabs(
            ['命中记录', '研究历史', '预警', '交易', '持仓', '备注']
        )
        with hit_tab:
            if detail['hit_history']:
                st.dataframe(detail['hit_history'], use_container_width=True, hide_index=True)
            else:
                st.info('无命中记录。')

        with research_hist_tab:
            if detail['research_history']:
                st.dataframe(detail['research_history'], use_container_width=True, hide_index=True)
            else:
                st.info('无研究历史。')

        with alert_tab:
            if detail['alerts']:
                st.dataframe(detail['alerts'], use_container_width=True, hide_index=True)
                with st.form('alert-actions-form'):
                    ac1, ac2 = st.columns([2, 1])
                    alert_id = ac1.number_input('预警 ID', min_value=1, step=1)
                    alert_action = ac2.selectbox('操作', ['acknowledge', 'resolve'])
                    if st.form_submit_button('执行', use_container_width=True):
                        try:
                            if alert_action == 'acknowledge':
                                acknowledge_alert(int(alert_id), paths=paths)
                            else:
                                resolve_alert(int(alert_id), paths=paths)
                            st.success('预警操作已执行')
                        except Exception as exc:
                            st.error(str(exc))
            else:
                st.info('无预警记录。')

        with trade_tab:
            if detail['trades']:
                st.dataframe(detail['trades'], use_container_width=True, hide_index=True)
            else:
                st.info('无交易记录。')

        with position_tab:
            pos = detail['position']
            if pos and pos.get('status'):
                pp1, pp2, pp3, pp4 = st.columns(4)
                pp1.metric('状态', pos.get('status', ''))
                pp2.metric('持股数', pos.get('total_shares', 0))
                pp3.metric('均价', f"${pos.get('avg_cost', 0):.2f}" if pos.get('avg_cost') else 'N/A')
                pp4.metric('首买日', pos.get('first_buy_date', 'N/A'))
            else:
                st.info('无持仓记录。')

        with notes_tab:
            current_notes = get_stock_notes(detail_symbol, paths=paths) or ''
            with st.form('stock-notes-form'):
                updated_notes = st.text_area('备注', value=current_notes, height=200)
                if st.form_submit_button('保存', use_container_width=True):
                    set_stock_notes(detail_symbol, updated_notes, paths=paths)
                    st.success('备注已保存')
    else:
        st.info('输入股票代码查看详情（命中/研究/预警/交易/持仓/备注）。')


# ===========================================================================
# TAB 5: 设置
# ===========================================================================
with settings_tab:
    st.header('设置')

    settings_strategy, settings_notify = st.tabs(['策略参数', '通知与研究'])

    # --- Strategy config ---
    with settings_strategy:
        st.subheader(f'策略：{selected_strategy}')
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
            min_valuation_score = col2.number_input('最小估值得分', min_value=0.0, value=float(defaults['min_valuation_score']), step=0.5)
            min_roe_for_quality = col1.number_input('质量线最小 ROE', min_value=0.0, value=float(defaults['min_roe_for_quality']), step=0.01, format='%.2f')

            if st.form_submit_button('保存策略配置', use_container_width=True):
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
                result = _safe_save_yaml(save_strategy_config_data, selected_strategy, updated, paths)
                if result is not None:
                    st.session_state['ui_success'] = '策略配置已保存'
                    st.rerun()

    # --- Notification & research config ---
    with settings_notify:
        st.subheader('通知与研究配置')
        nd = app_config_form_defaults(app_config)

        with st.form('app-config-form'):
            col1, col2 = st.columns(2)
            feishu_enabled = col1.checkbox('启用飞书通知', value=nd['feishu_enabled'])
            digest_mode = col2.selectbox('摘要模式', ['top3_only', 'full_watchlist'],
                                         index=0 if nd['digest_mode'] == 'top3_only' else 1)
            feishu_webhook_url = st.text_input('飞书 Webhook URL', value=nd['feishu_webhook_url'], type='password')

            st.markdown('---')
            st.markdown('**Perplexity 深度研究**')
            pcol1, pcol2 = st.columns(2)
            perplexity_enabled = pcol1.checkbox('启用', value=nd['perplexity_enabled'])
            perplexity_fallback = pcol2.checkbox('失败回退派生研究', value=nd['perplexity_fallback_to_derived'])
            perplexity_template = pcol1.text_input('Prompt 模板', value=nd['perplexity_prompt_template_id'])
            perplexity_version = pcol2.text_input('Prompt 版本', value=nd['perplexity_prompt_version'])

            st.markdown('---')
            st.markdown('**定时任务**（仅本地运行时生效）')
            tcol1, tcol2 = st.columns(2)
            schedule_enabled = tcol1.checkbox('启用定时', value=nd['schedule_enabled'])
            schedule_top_n = tcol2.number_input('Top N', min_value=1, value=nd['schedule_top_n'], step=1)
            schedule_cron = tcol1.text_input('Cron', value=nd['schedule_cron'])
            schedule_timezone = tcol2.text_input('时区', value=nd['schedule_timezone'])
            schedule_strategy = st.selectbox(
                '定时运行策略', strategies,
                index=strategies.index(nd['schedule_strategy']) if nd['schedule_strategy'] in strategies else default_index,
            )

            if st.form_submit_button('保存配置', use_container_width=True):
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
                    'perplexity_prompt_template_id': perplexity_template,
                    'perplexity_prompt_version': perplexity_version,
                    'perplexity_fallback_to_derived': perplexity_fallback,
                }
                updated = apply_app_config_form_values(app_config, values)
                result = _safe_save_yaml(save_app_config_data, updated, paths)
                if result is not None:
                    st.session_state['ui_success'] = '配置已保存'
                    st.rerun()

        st.caption('API Key 通过环境变量 / .env 注入，不在此处配置。')
