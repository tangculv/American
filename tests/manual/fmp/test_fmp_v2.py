#!/usr/bin/env python3
"""
测试新版FMP Stock Screener API
"""
import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]
load_dotenv(ROOT / ".env")

API_KEY = os.getenv("FMP_API_KEY", "").strip()
BASE_URL = "https://financialmodelingprep.com/stable"


def require_api_key() -> bool:
    if API_KEY:
        return True
    print("❌ FMP_API_KEY 缺失，请先在项目根目录 .env 中配置")
    return False


def test_company_screener():
    """测试新版company-screener API"""
    if not require_api_key():
        return None

    params = {
        "apikey": API_KEY,
        "marketCapMoreThan": 1000000000,  # > 10亿
        "betaMoreThan": 0.8,
        "betaLowerThan": 1.5,
        "volumeMoreThan": 5000000,
        "isEtf": "false",
        "isFund": "false",
        "isActivelyTrading": "true",
        "limit": 5
    }

    print("="*80)
    print("测试新版FMP Stock Screener API")
    print("="*80)
    print(f"\n端点: {BASE_URL}/company-screener")
    print(f"\n参数:")
    for key, value in params.items():
        if key != 'apikey':
            print(f"  {key}: {value}")
    print(f"\n{len(params)} 个参数")

    print("\n" + "="*80)
    print("正在调用API...")
    print("="*80 + "\n")

    try:
        response = requests.get(f"{BASE_URL}/company-screener", params=params)
        response.raise_for_status()

        print(f"状态码: {response.status_code}")
        print(f"内容类型: {response.headers.get('Content-Type', 'N/A')}\n")

        data = response.json()

        # 检查返回格式
        if isinstance(data, list):
            print(f"✅ 成功获取 {len(data)} 只股票\n")

            print("="*80)
            print("股票详情:")
            print("="*80)

            for i, stock in enumerate(data, 1):
                print(f"\n[{i}] {stock.get('symbol', 'N/A')}")
                print(f"    公司名称: {stock.get('companyName', 'N/A')}")
                print(f"    价格: ${stock.get('price', 0):.2f}")
                print(f"    市值: ${stock.get('marketCap', 0)/1000000000:.1f}B")
                print(f"    Beta: {stock.get('beta', 0):.2f}")
                print(f"    成交量: {stock.get('volume', 0):,}")
                print(f"    行业: {stock.get('sector', 'N/A')}")
                print(f"    子行业: {stock.get('industry', 'N/A')}")
                print(f"    交易所: {stock.get('exchange', 'N/A')}")
                print(f"    是否ETF: {stock.get('isEtf', False)}")
                print(f"    是否基金: {stock.get('isFund', False)}")
                print(f"    活跃交易: {stock.get('isActivelyTrading', False)}")

            print("\n" + "="*80)
            print("✅ API测试成功!")
            print("="*80)

        elif isinstance(data, dict) and 'Error Message' in data:
            print(f"❌ API错误: {data['Error Message']}")
        else:
            print(f"⚠️ 未知返回格式: {type(data)}")
            print(f"   返回内容: {json.dumps(data, indent=2)[:500]}")

        return data

    except requests.exceptions.RequestException as e:
        print(f"❌ 请求失败: {e}")
        if hasattr(e, 'response') and e.response:
            print(f"   状态码: {e.response.status_code}")
            try:
                error_data = e.response.json()
                print(f"   错误详情: {json.dumps(error_data, indent=2)}")
            except:
                print(f"   响应内容: {e.response.text[:500]}")
        return None

if __name__ == "__main__":
    test_company_screener()
