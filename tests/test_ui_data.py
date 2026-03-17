from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / 'src'
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from us_stock_research.alert_engine import Signal  # noqa: E402
from us_stock_research.alert_manager import AlertManager  # noqa: E402
from us_stock_research.config import ProjectPaths  # noqa: E402
from us_stock_research.models import ensure_schema, get_connection  # noqa: E402
from us_stock_research.position_manager import record_buy, record_sell  # noqa: E402
from us_stock_research.ui_data import (  # noqa: E402
    acknowledge_alert,
    get_candidate_pool,
    get_historical_trades,
    get_portfolio_view,
    get_stock_detail,
    get_stock_notes,
    mark_user_status,
    resolve_alert,
    set_stock_notes,
)


def make_paths(root: Path) -> ProjectPaths:
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


class UIDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.paths = make_paths(Path(self.temp_dir.name))
        ensure_schema(self.paths)
        with get_connection(self.paths) as connection:
            connection.execute(
                "INSERT INTO stock_master (symbol, company_name, sector, market_cap, source, hit_count, user_status, current_price) VALUES ('AAPL', 'Apple', 'Tech', 2000000000, 'strategy', 2, 'watching', 110)"
            )
            connection.execute(
                "INSERT INTO stock_master (symbol, company_name, sector, market_cap, source, hit_count, user_status, current_price) VALUES ('MSFT', 'Microsoft', 'Tech', 1800000000, 'strategy', 1, 'held', 210)"
            )
            connection.execute(
                "INSERT INTO strategy_hit (symbol, strategy_id, strategy_name, hit_date, hit_at, screen_payload_json, result) VALUES ('AAPL', 'value', 'value', '2026-03-16', '2026-03-16T10:00:00', ?, 'passed')",
                ('{"scoreDetail": {"metrics": {"pe": 12, "pb": 3, "roe": 0.22}, "eligibility": {"reasons": ["PE低", "ROE高"]}}, "previousClose": 100}',),
            )
            connection.execute(
                "INSERT INTO strategy_hit (symbol, strategy_id, strategy_name, hit_date, hit_at, screen_payload_json, result) VALUES ('AAPL', 'quality', 'quality', '2026-03-17', '2026-03-17T10:00:00', ?, 'passed')",
                ('{"scoreDetail": {"metrics": {"pe": 13, "pb": 3.2, "roe": 0.21}, "eligibility": {"reasons": ["现金流稳健"]}}, "previousClose": 108}',),
            )
            connection.execute(
                "INSERT INTO strategy_hit (symbol, strategy_id, strategy_name, hit_date, hit_at, screen_payload_json, result) VALUES ('MSFT', 'quality', 'quality', '2026-03-17', '2026-03-17T09:00:00', ?, 'passed')",
                ('{"scoreDetail": {"metrics": {"pe": 25, "pb": 8, "roe": 0.18}, "eligibility": {"reasons": ["质量高"]}}, "previousClose": 200}',),
            )
            connection.execute(
                "INSERT INTO scoring_breakdown (symbol, strategy_name, strategy_id, score_date, notes_json, detail_json, total_score, passed_screening) VALUES ('AAPL', 'quality', 'quality', '2026-03-17T10:00:00', ?, ?, 88, 1)",
                ('{"eligibility_reasons": ["ROE高", "低估值"]}', '{"eligibility_reasons": ["现金流稳健"]}'),
            )
            connection.execute(
                "INSERT INTO technical_snapshot (symbol, snapshot_date, price, ma_50, ma_200, signal, gate_is_blocked, weekly_trend) VALUES ('AAPL', '2026-03-16', 108, 100, 95, 'wait', 0, 'up')"
            )
            connection.execute(
                "INSERT INTO technical_snapshot (symbol, snapshot_date, price, ma_50, ma_200, signal, gate_is_blocked, weekly_trend) VALUES ('AAPL', '2026-03-17', 110, 101, 95, 'wait', 0, 'up')"
            )
            connection.execute(
                "INSERT INTO technical_snapshot (symbol, snapshot_date, price, ma_50, ma_200, signal, gate_is_blocked, weekly_trend) VALUES ('MSFT', '2026-03-16', 200, 190, 180, 'wait', 0, 'up')"
            )
            connection.execute(
                "INSERT INTO technical_snapshot (symbol, snapshot_date, price, ma_50, ma_200, signal, gate_is_blocked, weekly_trend) VALUES ('MSFT', '2026-03-17', 210, 191, 181, 'wait', 0, 'up')"
            )
            connection.execute(
                "INSERT INTO research_snapshot (id, symbol, research_date, trigger_type, trigger_priority, prompt_template_id, prompt_version, strategy_id, input_data_json, raw_response, status, expires_at) VALUES (1, 'AAPL', '2026-03-17T11:00:00', 'manual', 'P0', 'tpl', 'v1', 'quality', '{}', 'report', 'completed', '2026-03-27T11:00:00')"
            )
            connection.execute(
                "INSERT INTO research_analysis (research_snapshot_id, symbol, next_review_date, overall_recommendation, overall_conclusion, three_sentence_summary, feishu_doc_url) VALUES (1, 'AAPL', '2026-04-01', 'hold', '值得投', '三句话总结', 'https://doc.test/aapl')"
            )
        record_buy('MSFT', 200, 10, '2026-03-01', reason='建仓', paths=self.paths)
        manager = AlertManager(paths=self.paths)
        manager.process_signals('MSFT', [Signal(type='止损触发', level='action', action='考虑止损', detail='触发止损')])

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_get_candidate_pool(self) -> None:
        rows = get_candidate_pool(paths=self.paths)
        self.assertEqual(rows[0]['symbol'], 'AAPL')
        self.assertEqual(rows[0]['hit_count'], 2)
        self.assertEqual(rows[0]['research_status'], '已研究')
        self.assertEqual(rows[0]['strategy_name'], 'quality')
        self.assertEqual(rows[0]['sector'], 'Tech')
        self.assertEqual(rows[0]['hit_reasons'], ['ROE高', '低估值', '现金流稳健'])
        self.assertAlmostEqual(rows[0]['daily_change_pct'], 1.85, places=2)

    def test_get_candidate_pool_filters(self) -> None:
        rows = get_candidate_pool(filters={'user_status': 'held'}, paths=self.paths)
        self.assertEqual([row['symbol'] for row in rows], ['MSFT'])

    def test_get_portfolio_view(self) -> None:
        view = get_portfolio_view(paths=self.paths)
        self.assertEqual(view['summary']['total_positions'], 1)
        self.assertEqual(view['summary']['need_action_count'], 1)
        self.assertEqual(view['sections'][0]['items'][0]['symbol'], 'MSFT')
        self.assertEqual(view['sections'][0]['items'][0]['top_action'], '考虑止损')

    def test_get_historical_trades(self) -> None:
        record_buy('AAPL', 100, 10, '2026-03-01', reason='买入', paths=self.paths)
        record_sell('AAPL', 120, 10, '2026-03-10', reason='止盈', paths=self.paths)
        rows = get_historical_trades(paths=self.paths)
        self.assertEqual(rows[0]['symbol'], 'AAPL')
        self.assertEqual(rows[0]['sell_reason'], '止盈')
        self.assertEqual(rows[0]['buy_reason'], '买入')
        self.assertAlmostEqual(rows[0]['realized_pnl'], 200.0)

    def test_get_stock_detail(self) -> None:
        detail = get_stock_detail('AAPL', paths=self.paths)
        self.assertEqual(detail['basic']['company_name'], 'Apple')
        self.assertEqual(detail['latest_research']['conclusion'], '值得投')
        self.assertEqual(detail['research_history'][0]['feishu_doc_url'], 'https://doc.test/aapl')
        self.assertEqual(detail['hit_history'][0]['strategy_name'], 'quality')

    def test_mark_user_status(self) -> None:
        mark_user_status('AAPL', 'ignored', paths=self.paths)
        with get_connection(self.paths) as connection:
            value = connection.execute("SELECT user_status FROM stock_master WHERE symbol='AAPL'").fetchone()[0]
        self.assertEqual(value, 'ignored')

    def test_mark_user_status_invalid(self) -> None:
        with self.assertRaises(ValueError):
            mark_user_status('AAPL', 'bad-status', paths=self.paths)

    def test_acknowledge_and_resolve_alert(self) -> None:
        with get_connection(self.paths) as connection:
            alert_id = connection.execute("SELECT id FROM alert_event WHERE symbol='MSFT' ORDER BY id DESC LIMIT 1").fetchone()[0]
        acknowledge_alert(int(alert_id), paths=self.paths)
        resolve_alert(int(alert_id), paths=self.paths)
        with get_connection(self.paths) as connection:
            status = connection.execute('SELECT status FROM alert_event WHERE id = ?', (alert_id,)).fetchone()[0]
        self.assertEqual(status, 'resolved')

    def test_stock_notes_crud(self) -> None:
        self.assertIsNone(get_stock_notes('TSLA', paths=self.paths))
        set_stock_notes('TSLA', '观察一下', paths=self.paths)
        self.assertEqual(get_stock_notes('TSLA', paths=self.paths), '观察一下')
        set_stock_notes('TSLA', '', paths=self.paths)
        self.assertIsNone(get_stock_notes('TSLA', paths=self.paths))


if __name__ == '__main__':
    unittest.main()
