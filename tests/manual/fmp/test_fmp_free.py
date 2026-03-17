#!/usr/bin/env python3
"""
测试FMP免费版API
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


def endpoint_url(path: str) -> str:
    return f"{BASE_URL}/{path.lstrip('/')}"


def mask_params(params: dict[str, str | int]) -> dict[str, str | int]:
    masked = dict(params)
    if "apikey" in masked:
        masked["apikey"] = "***"
    return masked


def test_basic_endpoints():
    """测试基础免费API端点"""
    if not require_api_key():
        return None

    endpoints = [
        ("Profile API", endpoint_url("profile"), {"symbol": "AAPL", "apikey": API_KEY}),
        ("Quote API", endpoint_url("quote-short/AAPL"), {"apikey": API_KEY}),
        ("Stock List API", endpoint_url("stock-list"), {"apikey": API_KEY, "limit": 3}),
        ("Active Trading List", endpoint_url("actively-trading-list"), {"apikey": API_KEY, "limit": 3}),
        ("Search Name API", endpoint_url("search-name"), {"query": "Apple", "apikey": API_KEY, "limit": 3}),
    ]

    print("=" * 80)
    print("测试FMP免费版API端点")
    print("=" * 80)

    for name, url, params in endpoints:
        print(f"\n测试: {name}")
        print(f"Endpoint: {url}")
        print(f"Params: {mask_params(params)}")

        try:
            response = requests.get(url, params=params, timeout=10)
            print(f"状态码: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and len(data) > 0:
                    print(f"✅ 成功 - 返回 {len(data)} 条数据")
                    if name == "Profile API" and data:
                        print(f"   示例: {data[0].get('symbol')} - {data[0].get('companyName')}")
                elif isinstance(data, list):
                    print("✅ 成功")
                elif isinstance(data, dict):
                    if "Error Message" in data:
                        print(f"❌ API错误: {data['Error Message']}")
                    else:
                        print("✅ 成功 - 返回字典")
            else:
                print("❌ 失败")
                if response.text:
                    try:
                        error_data = response.json()
                        print(f"   错误: {json.dumps(error_data, indent=2)[:300]}")
                    except Exception:
                        print(f"   响应: {response.text[:200]}")

        except Exception as e:
            print(f"❌ 异常: {e}")

    print("\n" + "=" * 80)
    print("测试完成")
    print("=" * 80)


if __name__ == "__main__":
    test_basic_endpoints()
