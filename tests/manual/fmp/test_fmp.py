#!/usr/bin/env python3
"""
测试FMP API
"""
import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]
load_dotenv(ROOT / ".env")

API_KEY = os.getenv("FMP_API_KEY", "").strip()
BASE_URL = "https://financialmodelingprep.com/api/v3"


def require_api_key() -> bool:
    if API_KEY:
        return True
    print("❌ FMP_API_KEY 缺失，请先在项目根目录 .env 中配置")
    return False


def test_fmp_screener():
    """测试FMP筛选API"""
    if not require_api_key():
        return None

    params = {
        "apikey": API_KEY,
        "marketCapMoreThan": 1000000000,  # > 10亿
        "peMoreThan": 0,
        "peLowerThan": 25,
        "isEarningPositive": "true",
        "priceChangePercentageLowerThan": -0.20,
        "priceChangePercentageMoreThan": -0.60,
        "volumeMoreThan": 5000000,
        "isEtf": "false",
        "isFund": "false",
        "isActivelyTrading": "true",
        "limit": 5
    }

    print("正在调用FMP筛选API...")
    print(f"参数: {json.dumps(params, indent=2, ensure_ascii=False)}\n")

    try:
        response = requests.get(f"{BASE_URL}/screener", params=params)
        response.raise_for_status()
        data = response.json()

        print(f"✅ 成功获取 {len(data)} 只候选股\n")

        print("="*80)
        print("候选股详情:")
        print("="*80)

        for stock in data:
            symbol = stock.get('symbol', 'N/A')
            name = stock.get('name', 'N/A')
            price = stock.get('price', 0)
            pe = stock.get('pe', 0)
            changes_pct = stock.get('changesPercentage', 0)
            market_cap = stock.get('marketCap', 0) / 1000000000
            volume = stock.get('volume', 0)
            year_high = stock.get('yearHigh', 0)
            year_low = stock.get('yearLow', 0)
            beta = stock.get('beta', 0)

            print(f"\n{symbol} - {name}")
            print(f"  价格: ${price:.2f}")
            print(f"  PE: {pe:.1f}")
            print(f"  涨跌幅: {changes_pct:.2f}%")
            print(f"  市值: ${market_cap:.1f}B")
            print(f"  成交量: {volume:,}")
            print(f"  52周区间: ${year_low:.2f} - ${year_high:.2f}")
            print(f"  Beta: {beta:.2f}")

        print("\n" + "="*80)
        print("API测试成功!")
        print("="*80)

        return data

    except requests.exceptions.RequestException as e:
        print(f"❌ API调用失败: {e}")
        if hasattr(e, 'response') and e.response:
            print(f"   状态码: {e.response.status_code}")
            print(f"   响应: {e.response.text}")
        return None
    except json.JSONDecodeError as e:
        print(f"❌ JSON解析失败: {e}")
        print(f"   响应内容: {response.text[:500]}")
        return None

if __name__ == "__main__":
    test_fmp_screener()
