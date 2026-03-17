#!/usr/bin/env python3
"""
Extract FMP API screener parameters from official documentation
"""
import requests
from bs4 import BeautifulSoup
import json

def extract_params_from_html():
    """Extract all query parameters from FMP screener docs"""
    url = "https://site.financialmodelingprep.com/developer/docs/stable/search-company-screener"

    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')

        # Look for all parameter mentions
        params = set()

        # Search for code blocks and text that contain parameter names
        all_text = soup.get_text()

        # Common parameter patterns
        patterns = [
            r'\b(pe|pb|roe|roa|debtToEquity|currentRatio|revenue|netIncome|grossMargin|operatingMargin|dividendYield|beta|marketCap|volume|price|exchange|sector|industry|isEtf|isFund)(MoreThan|LowerThan|Max|Min|Min|max)\b',
        ]

        import re
        for pattern in patterns:
            matches = re.findall(pattern, all_text, re.IGNORECASE)
            params.update(matches)

        # Also search for parameter names in tables or code blocks
        code_blocks = soup.find_all('code')
        for block in code_blocks:
            code_text = block.get_text()
            # Extract query parameters from URLs
            url_params = re.findall(r'[?&]([a-zA-Z]+(?:MoreThan|LowerThan|Min|Max|Min|max))=', code_text)
            params.update(url_params)

        return sorted(list(params))

    except Exception as e:
        print(f"Error: {e}")
        return []

if __name__ == "__main__":
    print("Extracting FMP Screener API parameters...")
    params = extract_params_from_html()

    print(f"\nFound {len(params)} potential parameters:")
    for param in params:
        print(f"  - {param}")
