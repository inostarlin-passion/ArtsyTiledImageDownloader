import math

import esprima
import json
import re

import requests
from bs4 import BeautifulSoup

import image_metadata

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

pattern = r"^\s*var __RELAY_HYDRATION_DATA__ = "


def binary_search(url, low, high):
    if low > high:
        return
    img_url = f"{url}{high}/0_0.jpg"
    response = requests.get(img_url, timeout=10)
    if response.status_code == 200:
        return high
    mid = (low + high) >> 1
    img_url = f"{url}{mid}/0_0.jpg"
    response = requests.get(img_url, timeout=10)
    if response.status_code == 200:
        return binary_search(url, mid, high - 1)
    return binary_search(url, low, mid - 1)


def find_upper_limit(url):
    limit = 1
    img_url = f"{url}{limit}/0_0.jpg"
    response = requests.get(img_url, timeout=10)
    while response.status_code == 200:
        limit <<= 1
        img_url = f"{url}{limit}/0_0.jpg"
        response = requests.get(img_url, timeout=10)
    return limit


def get_max_zoom_level(url):
    upper_limit = find_upper_limit(url)
    return binary_search(url, upper_limit >> 1, upper_limit)


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


def get_metadatas(url):
    script = get_script(url)
    ast = esprima.parseScript(script)
    if ast.type == 'Program' and ast.body:
        statement = ast.body[0]
        if statement and statement.type == 'VariableDeclaration':
            declaration = statement.declarations[0]
            if declaration.type == 'VariableDeclarator':
                right_hand_side = declaration.init
                if right_hand_side and right_hand_side.type == 'Literal':
                    value = right_hand_side.value

    json_data = json.loads(value)
    title = json.loads(json_data[0][0])['variables']['artworkID']
    figures = json_data[0][1]['json']['data']['artworkResult']['figures']
    image_metadatas = []
    for i in range(len(figures)):
        format = figures[i]['deepZoom']['Image']['Format']
        url = figures[i]['deepZoom']['Image']['Url']
        tile_size = figures[i]['deepZoom']['Image']['TileSize']
        width = figures[i]['deepZoom']['Image']['Size']['Width']
        height = figures[i]['deepZoom']['Image']['Size']['Height']
        max_zoom_level = get_max_zoom_level(url)
        url += f"{max_zoom_level}/"
        rows = math.ceil(height / tile_size)
        cols = math.ceil(width / tile_size)
        image_metadatas.append(
            image_metadata.ImageMetadata(i, title, format, url, tile_size, width, height, rows, cols, max_zoom_level))

    return image_metadatas
