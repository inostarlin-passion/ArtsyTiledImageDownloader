import re

import requests
from bs4 import BeautifulSoup

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

pattern = r"^\s*var __RELAY_HYDRATION_DATA__ = "


def get_script(url):
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    html_content = response.text
    soup = BeautifulSoup(html_content, 'lxml')
    for script in soup.find_all('script'):
        if not re.search(pattern, script.text):
            continue
        return script.text
    raise ValueError("script not found")
