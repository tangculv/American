from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / 'src'
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from us_stock_research.cli import build_parser


class ResearchCliParserTests(unittest.TestCase):
    def test_research_parser_accepts_product_flags(self) -> None:
        parser = build_parser()
        args = parser.parse_args(['research', '--symbol', 'ZM', '--provider', 'perplexity', '--persist', '--show-prompt', '--show-input'])
        self.assertEqual(args.command, 'research')
        self.assertEqual(args.symbol, 'ZM')
        self.assertEqual(args.provider, 'perplexity')
        self.assertTrue(args.persist)
        self.assertTrue(args.show_prompt)
        self.assertTrue(args.show_input)

    def test_research_diagnostics_parser_exists(self) -> None:
        parser = build_parser()
        args = parser.parse_args(['research-diagnostics'])
        self.assertEqual(args.command, 'research-diagnostics')


if __name__ == '__main__':
    unittest.main()
