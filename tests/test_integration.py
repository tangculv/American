from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from us_stock_research.alert_manager import AlertManager
from us_stock_research.cli import cmd_run
from us_stock_research.config import AppSettings, ProjectPaths
from us_stock_research.event_notifications import send_alert_notifications_for_symbol
from us_stock_research.models import ensure_schema, get_connection
from us_stock_research.position_manager import record_buy
from us_stock_research.research_engine import GATE_FIELDS, QUALITY_FIELDS, TwoLayerResearchResult
from us_stock_research.tracking_workflow import execute_reresearch, run_daily_monitoring


def _make_paths(root: Path) -> ProjectPaths:
    return ProjectPaths(
        root=root,
        config_dir=root / 'config',
        strategy_dir=root / 'config' / 'strategies',
        app_config_path=root / 'config' / 'app.yaml',
        outputs_dir=root / 'outputs' / 'fmp-screening',
        watchlist_dir=root / 'watchlist',
        data_dir=root / 'data',
        database_path=root / 'data' / 'stock_research.db',
        logs_dir=root / 'logs',
    )


@pytest.fixture
def tmp_db(tmp_path: Path) -> ProjectPaths:
    paths = _make_paths(tmp_path)
    paths.ensure()
    ensure_schema(paths)
    return paths


@pytest.fixture
def mock_fmp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        'us_stock_research.tracking_workflow.refresh_holding_tracking',
        lambda *args, **kwargs: None,
    )


@pytest.fixture
def mock_fmp_screener(monkeypatch: pytest.MonkeyPatch) -> None:
    strategy = {
        'name': '低估值高质量科技股',
        'screen': {
            'limit': 50,
            'market_cap_min': 500_000_000,
            'market_cap_max': 100_000_000_000,
            'volume_min': 1_000_000,
            'sector': 'Technology',
            'exchange': 'NASDAQ',
        },
        'ranking': {
            'top_n': 10,
            'gates': {
                'max_pe': 30,
                'max_pb': 5,
                'min_valuation_score': 2,
                'require_positive_pe': True,
                'require_positive_pb': True,
                'min_roe_for_quality': 0.10,
            },
        },
    }
    fake_candidates = [
        {
            'symbol': 'AAPL',
            'companyName': 'Apple',
            'price': 150.0,
            'marketCap': 2_000_000_000_000,
            'volume': 5_000_000,
            'sector': 'Technology',
            'exchange': 'NASDAQ',
            'exchangeShortName': 'NASDAQ',
        },
        {
            'symbol': 'MSFT',
            'companyName': 'Microsoft',
            'price': 300.0,
            'marketCap': 1_800_000_000_000,
            'volume': 4_000_000,
            'sector': 'Technology',
            'exchange': 'NASDAQ',
            'exchangeShortName': 'NASDAQ',
        },
        {
            'symbol': 'GOOGL',
            'companyName': 'Alphabet',
            'price': 140.0,
            'marketCap': 1_500_000_000_000,
            'volume': 3_000_000,
            'sector': 'Technology',
            'exchange': 'NASDAQ',
            'exchangeShortName': 'NASDAQ',
        },
    ]
    ratios = {
        'AAPL': {
            'priceToEarningsRatioTTM': 15.0,
            'priceToBookRatioTTM': 2.0,
            'roeRatioTTM': 0.18,
            'netProfitMarginTTM': 0.23,
            'debtToEquityRatioTTM': 0.45,
            'currentRatioTTM': 2.1,
        },
        'MSFT': {
            'priceToEarningsRatioTTM': 18.0,
            'priceToBookRatioTTM': 3.0,
            'roeRatioTTM': 0.20,
            'netProfitMarginTTM': 0.25,
            'debtToEquityRatioTTM': 0.40,
            'currentRatioTTM': 2.0,
        },
        'GOOGL': {
            'priceToEarningsRatioTTM': 19.0,
            'priceToBookRatioTTM': 2.5,
            'roeRatioTTM': 0.17,
            'netProfitMarginTTM': 0.21,
            'debtToEquityRatioTTM': 0.35,
            'currentRatioTTM': 1.9,
        },
    }
    monkeypatch.setattr('us_stock_research.service.load_settings', lambda: AppSettings(fmp_api_key='demo'))
    monkeypatch.setattr('us_stock_research.service.load_strategy', lambda strategy_name, paths=None: strategy)
    monkeypatch.setattr(
        'us_stock_research.fmp_client.FMPClient.company_screener',
        lambda *args, **kwargs: list(fake_candidates),
    )
    monkeypatch.setattr(
        'us_stock_research.fmp_client.FMPClient.ratios_ttm',
        lambda self, symbol: dict(ratios.get(symbol, {})),
    )



def _make_structured_fields(*, overall_conclusion: str = '值得投') -> dict[str, Any]:
    payload = {
        'summary_table': {'symbol': 'AAPL', 'price': 100.0},
        'three_sentence_summary': '业务稳健，估值合理，建议持续跟踪。',
        'bull_thesis': [{'point': '现金流稳健', 'impact': 'high'}],
        'overall_conclusion': overall_conclusion,
        'top_risks': [{'type': 'macro', 'detail': '宏观波动', 'severity': 'medium'}],
        'valuation': {
            'valuation_view': 'attractive',
            'target_price': 120.0,
            'tangible_book_value_per_share': 20.0,
            'price_to_tbv': 5.0,
            'normalized_eps': 6.0,
            'normalized_earnings_yield': 0.06,
            'net_debt_to_ebitda': 1.5,
            'interest_coverage': 8.0,
            'goodwill_pct': 0.05,
            'intangible_pct': 0.04,
            'tangible_net_asset_positive': True,
            'safety_margin_source': 'base_case',
        },
        'earnings_bridge': {'status': 'ok'},
        'tangible_nav': {'status': 'ok'},
        'three_scenario_valuation': {
            'target_price_conservative': 110.0,
            'target_price_base': 120.0,
            'target_price_optimistic': 130.0,
        },
        'trade_plan': {
            'buy_range_low': 95.0,
            'buy_range_high': 105.0,
            'max_position_pct': 10.0,
            'stop_loss_condition': '跌破长期支撑',
            'add_position_condition': '业绩继续超预期',
            'reduce_position_condition': '估值显著透支',
        },
        'refinancing_risk': '低',
        'invalidation_conditions': ['核心假设失效'],
        'markdown_report': '# Report\n\n完整研究报告',
    }
    assert all(field in payload for field in GATE_FIELDS)
    assert all(field in payload for field in QUALITY_FIELDS)
    return payload



def _make_result(symbol: str, *, overall_conclusion: str = '值得投') -> TwoLayerResearchResult:
    structured = _make_structured_fields(overall_conclusion=overall_conclusion)
    return TwoLayerResearchResult(
        symbol=symbol,
        markdown_report=f'# {symbol} report',
        structured_fields={
            'tangible_book_value_per_share': 20.0,
            'price_to_tbv': 5.0,
            'normalized_eps': 6.0,
            'normalized_earnings_yield': 0.06,
            'net_debt_to_ebitda': 1.5,
            'interest_coverage': 8.0,
            'goodwill_pct': 0.05,
            'intangible_pct': 0.04,
            'tangible_net_asset_positive': True,
            'safety_margin_source': 'base_case',
            'buy_range_low': 95.0,
            'buy_range_high': 105.0,
            'max_position_pct': 10.0,
            'target_price_conservative': 110.0,
            'target_price_base': 120.0,
            'target_price_optimistic': 130.0,
            'stop_loss_condition': '跌破长期支撑',
            'add_position_condition': '业绩继续超预期',
            'reduce_position_condition': '估值显著透支',
            'overall_conclusion': overall_conclusion,
            'top_risks_json': json.dumps(structured['top_risks'], ensure_ascii=False),
            'invalidation_conditions_json': json.dumps(structured['invalidation_conditions'], ensure_ascii=False),
            'three_sentence_summary': structured['three_sentence_summary'],
            'refinancing_risk': '低',
        },
        quality_level='pass',
        quality_issues=[],
        fallback_used=False,
        provider='perplexity',
        prompt_template_id='tpl-two-layer',
        prompt_version='v1',
        error_message=None,
    )


@pytest.fixture
def mock_perplexity(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_execute(symbol: str, stock_context: dict[str, Any], skip_dedup: bool = False, paths: ProjectPaths | None = None) -> TwoLayerResearchResult:
        del skip_dedup, paths
        calls.append((symbol, dict(stock_context)))
        return _make_result(symbol, overall_conclusion='值得投')

    monkeypatch.setattr('us_stock_research.cli.execute_research_with_two_layer_output', fake_execute)
    monkeypatch.setattr('us_stock_research.tracking_workflow.execute_research_with_two_layer_output', fake_execute)
    return calls


@pytest.fixture
def mock_perplexity_conclusion_flip(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_execute(symbol: str, stock_context: dict[str, Any], skip_dedup: bool = False, paths: ProjectPaths | None = None) -> TwoLayerResearchResult:
        del skip_dedup, paths
        calls.append((symbol, dict(stock_context)))
        return _make_result(symbol, overall_conclusion='不值得投')

    monkeypatch.setattr('us_stock_research.tracking_workflow.execute_research_with_two_layer_output', fake_execute)
    return calls


@pytest.fixture
def mock_feishu_doc(monkeypatch: pytest.MonkeyPatch):
    doc_calls: list[dict[str, Any]] = []

    def fake_create(**kwargs: Any) -> str:
        doc_calls.append(dict(kwargs))
        symbol = str(kwargs['symbol'])
        return f'https://feishu.test/docx/{symbol.lower()}'

    monkeypatch.setattr('us_stock_research.cli.create_research_doc', fake_create)
    monkeypatch.setattr('us_stock_research.tracking_workflow.create_research_doc', fake_create)
    return doc_calls


@pytest.fixture
def mock_feishu_webhook(monkeypatch: pytest.MonkeyPatch):
    webhook_calls: list[dict[str, Any]] = []

    def fake_send_post(title: str, lines: list[str], webhook_url: str) -> dict[str, Any]:
        webhook_calls.append({'title': title, 'lines': list(lines), 'webhook_url': webhook_url})
        return {'ok': True}

    monkeypatch.setattr('us_stock_research.event_notifications.send_post', fake_send_post)
    return webhook_calls



def _insert_technical(
    paths: ProjectPaths,
    *,
    symbol: str,
    snapshot_date: str,
    price: float,
    ma_50: float = 100.0,
    ma_200: float = 95.0,
    rsi_14: float = 55.0,
    ma_20_slope: float = 0.5,
    high_52w: float = 120.0,
    volume: int = 1_000_000,
    volume_ratio: float = 1.2,
    weekly_trend: str = 'up',
) -> None:
    with get_connection(paths) as connection:
        connection.execute(
            """
            INSERT INTO technical_snapshot (
                symbol, snapshot_date, price, ma_50, ma_200, rsi_14, ma_20_slope,
                high_52w, volume, volume_ratio, weekly_trend, signal, gate_is_blocked
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'wait', 0)
            """,
            (symbol, snapshot_date, price, ma_50, ma_200, rsi_14, ma_20_slope, high_52w, volume, volume_ratio, weekly_trend),
        )



def _latest_notification_rows(paths: ProjectPaths, *, event_type: str | None = None, symbol: str | None = None) -> list[Any]:
    query = 'SELECT event_type, symbol, payload_json, send_status FROM notification_event WHERE 1=1'
    params: list[Any] = []
    if event_type is not None:
        query += ' AND event_type = ?'
        params.append(event_type)
    if symbol is not None:
        query += ' AND symbol = ?'
        params.append(symbol)
    query += ' ORDER BY id ASC'
    with get_connection(paths) as connection:
        return connection.execute(query, params).fetchall()



def test_daily_pipeline_end_to_end(
    tmp_db: ProjectPaths,
    mock_fmp_screener: None,
    mock_perplexity,
    mock_feishu_doc,
    mock_feishu_webhook,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr('us_stock_research.cli.time.sleep', lambda *_args, **_kwargs: None)

    exit_code = cmd_run(notify=True, strategy_name='low_valuation_quality', top_n=3, paths=tmp_db)

    assert exit_code == 0
    assert len(mock_perplexity) == 0
    assert len(mock_feishu_doc) == 0

    with get_connection(tmp_db) as connection:
        strategy_hit_count = connection.execute('SELECT COUNT(*) FROM strategy_hit').fetchone()[0]
        scoring_count = connection.execute('SELECT COUNT(*) FROM scoring_breakdown').fetchone()[0]
        ranking_count = connection.execute('SELECT COUNT(*) FROM ranking_snapshot').fetchone()[0]
        screening_snapshot_count = connection.execute(
            "SELECT COUNT(*) FROM research_snapshot WHERE symbol IN ('AAPL', 'MSFT', 'GOOGL')"
        ).fetchone()[0]
        analysis_rows = connection.execute(
            "SELECT symbol, overall_conclusion, feishu_doc_url FROM research_analysis WHERE symbol IN ('AAPL', 'MSFT', 'GOOGL') ORDER BY symbol, id DESC"
        ).fetchall()
        daily_event = connection.execute(
            "SELECT event_type, payload_json FROM notification_event WHERE event_type = 'daily_screening' ORDER BY id DESC LIMIT 1"
        ).fetchone()

    assert strategy_hit_count == 3
    assert scoring_count == 3
    assert ranking_count == 3
    assert screening_snapshot_count >= 3

    latest_analysis = {}
    for row in analysis_rows:
        latest_analysis.setdefault(str(row[0]), row)
    assert set(latest_analysis) == {'AAPL', 'GOOGL', 'MSFT'}

    assert daily_event is not None
    payload = json.loads(daily_event[1])
    assert daily_event[0] == 'daily_screening'
    results = payload['facts']['results']
    assert len(results) == 3
    assert {item['symbol'] for item in results} == {'AAPL', 'GOOGL', 'MSFT'}
    assert {item['status'] for item in results} == {'reused'}



def test_buy_to_alert_notification(
    tmp_db: ProjectPaths,
    mock_fmp: None,
    mock_feishu_webhook,
) -> None:
    record_buy('AAPL', price=100.0, quantity=50, buy_date='2026-03-10', paths=tmp_db)
    _insert_technical(tmp_db, symbol='AAPL', snapshot_date='2026-03-15', price=100.0)
    _insert_technical(tmp_db, symbol='AAPL', snapshot_date='2026-03-16', price=90.0)

    result = run_daily_monitoring(paths=tmp_db)
    assert result['signals_detected'] == 3

    with get_connection(tmp_db) as connection:
        alerts = connection.execute(
            "SELECT signal_type, action, status FROM alert_event WHERE symbol = 'AAPL' ORDER BY id"
        ).fetchall()
    assert [(row[0], row[1], row[2]) for row in alerts] == [
        ('急跌预警', '重点关注', 'triggered'),
        ('阶段回撤', '重点关注', 'upgraded'),
        ('止损触发', '考虑止损', 'triggered'),
    ]

    manager = AlertManager(paths=tmp_db)
    merged = manager.merge_for_notification('AAPL')
    assert merged is not None
    assert merged['signal_count'] == 2
    assert merged['top_action'] == '考虑止损'

    sent = send_alert_notifications_for_symbol('AAPL', manager, 'https://feishu.example/hook', 'cid-buy-alert', paths=tmp_db)
    assert sent['sent'] is True
    assert sent['event_type'] == 'sell_reminder'

    rows = _latest_notification_rows(tmp_db, event_type='sell_reminder', symbol='AAPL')
    assert len(rows) == 1
    assert rows[0][3] == 'sent'



def test_alert_lifecycle_expiry(tmp_db: ProjectPaths, mock_fmp: None) -> None:
    record_buy('AAPL', price=100.0, quantity=10, buy_date='2026-03-01', paths=tmp_db)
    _insert_technical(tmp_db, symbol='AAPL', snapshot_date='2026-03-15', price=100.0)
    _insert_technical(tmp_db, symbol='AAPL', snapshot_date='2026-03-16', price=99.0)

    with get_connection(tmp_db) as connection:
        connection.execute(
            """
            INSERT INTO alert_event (
                symbol, signal_type, signal_level, action, status,
                trigger_value, trigger_threshold, detail, triggered_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now', '-4 days'))
            """,
            ('AAPL', '急跌预警', 'warning', '重点关注', 'triggered', -6.0, -5.0, 'old signal'),
        )

    run_daily_monitoring(paths=tmp_db)

    with get_connection(tmp_db) as connection:
        row = connection.execute(
            "SELECT status, expired_at FROM alert_event WHERE symbol = 'AAPL' AND signal_type = '急跌预警' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    assert row[0] == 'expired'
    assert row[1] is not None



def test_reresearch_conclusion_flip(
    tmp_db: ProjectPaths,
    mock_fmp: None,
    mock_perplexity_conclusion_flip,
    mock_feishu_doc,
) -> None:
    record_buy('AAPL', price=100.0, quantity=10, buy_date='2026-03-01', paths=tmp_db)
    with get_connection(tmp_db) as connection:
        connection.execute(
            "INSERT INTO research_snapshot (symbol, research_date, trigger_type, trigger_priority, prompt_template_id, prompt_version, strategy_id, input_data_json, raw_response, status, retry_count, expires_at) VALUES (?, ?, 'manual', 'P0', 'tpl', 'v1', 'two_layer_research', '{}', 'raw', 'completed', 0, ?)",
            ('AAPL', '2026-03-01T00:00:00', '2026-03-01T00:00:00'),
        )
        snapshot_id = int(connection.execute('SELECT last_insert_rowid()').fetchone()[0])
        connection.execute(
            "INSERT INTO research_analysis (research_snapshot_id, symbol, overall_conclusion, invalidation_conditions_json, confidence_score, next_review_date) VALUES (?, ?, ?, '[]', 80, '2026-04-01')",
            (snapshot_id, 'AAPL', '值得投'),
        )
    _insert_technical(tmp_db, symbol='AAPL', snapshot_date='2026-03-15', price=100.0, weekly_trend='up')
    _insert_technical(tmp_db, symbol='AAPL', snapshot_date='2026-03-16', price=94.0, weekly_trend='down')

    monitoring = run_daily_monitoring(paths=tmp_db)
    assert 'AAPL' in monitoring['reresearch_triggered']

    result = execute_reresearch('AAPL', paths=tmp_db)
    assert result['success'] is True
    assert result['conclusion_flipped'] is True
    assert result['doc_url'] == 'https://feishu.test/docx/aapl'

    with get_connection(tmp_db) as connection:
        conclusion = connection.execute(
            "SELECT overall_conclusion, feishu_doc_url FROM research_analysis WHERE symbol = 'AAPL' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        alert_row = connection.execute(
            "SELECT signal_type, action FROM alert_event WHERE symbol = 'AAPL' AND signal_type = '持有逻辑失效' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        event_row = connection.execute(
            "SELECT event_type, payload_json FROM notification_event WHERE event_type = 'reresearch_completed' ORDER BY id DESC LIMIT 1"
        ).fetchone()

    assert conclusion[0] == '不值得投'
    assert conclusion[1] == 'https://feishu.test/docx/aapl'
    assert alert_row is not None
    assert tuple(alert_row) == ('持有逻辑失效', '考虑清仓')
    assert event_row is not None
    event_payload = json.loads(event_row[1])
    assert event_payload['facts']['conclusion_flipped'] is True



def test_multi_signal_merge(
    tmp_db: ProjectPaths,
    mock_fmp: None,
    mock_feishu_webhook,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record_buy('MSFT', price=100.0, quantity=20, buy_date='2026-03-01', paths=tmp_db)
    with get_connection(tmp_db) as connection:
        connection.execute(
            "INSERT INTO research_snapshot (symbol, research_date, trigger_type, trigger_priority, prompt_template_id, prompt_version, strategy_id, input_data_json, raw_response, status, retry_count, expires_at) VALUES (?, ?, 'manual', 'P0', 'tpl', 'v1', 'two_layer_research', '{}', 'raw', 'completed', 0, ?)",
            ('MSFT', '2026-03-01T00:00:00', '2026-03-01T00:00:00'),
        )
        snapshot_id = int(connection.execute('SELECT last_insert_rowid()').fetchone()[0])
        connection.execute(
            """
            INSERT INTO research_analysis (
                research_snapshot_id, symbol, overall_conclusion, invalidation_conditions_json,
                confidence_score, next_review_date
            ) VALUES (?, ?, '值得投', '[]', 80, '2026-04-01')
            """,
            (snapshot_id, 'MSFT'),
        )
    _insert_technical(tmp_db, symbol='MSFT', snapshot_date='2026-03-15', price=100.0, weekly_trend='up')
    _insert_technical(
        tmp_db,
        symbol='MSFT',
        snapshot_date='2026-03-16',
        price=88.0,
        rsi_14=75.0,
        ma_20_slope=-0.5,
        weekly_trend='up',
    )

    monkeypatch.setattr('us_stock_research.event_notifications.time.sleep', lambda *_args, **_kwargs: None)
    monitoring = run_daily_monitoring(paths=tmp_db)
    assert monitoring['signals_detected'] == 4

    manager = AlertManager(paths=tmp_db)
    merged = manager.merge_for_notification('MSFT')
    assert merged is not None
    assert merged['signal_count'] == 3
    assert merged['top_action'] == '考虑止损'
    assert {signal['type'] for signal in merged['signals']} == {'急跌预警', '止损触发', '技术顶部信号'}

    sent = send_alert_notifications_for_symbol('MSFT', manager, 'https://feishu.example/hook', 'cid-msft-alert', paths=tmp_db)
    assert sent['sent'] is True
    assert sent['event_type'] == 'sell_reminder'

    rows = _latest_notification_rows(tmp_db, event_type='sell_reminder', symbol='MSFT')
    assert len(rows) == 1
    payload = json.loads(rows[0][2])
    assert payload['facts']['signal_count'] == 3
    assert payload['facts']['top_action'] == '考虑止损'
