import math

import esprima
import json
import re

import requests
from bs4 import BeautifulSoup

import image_metadata
from config import *


def is_url_ok(url):
    return requests.get(url, timeout=REQUEST_TIMEOUT).status_code == 200


def binary_search(url, low, high):
    if low > high:
        return
    img_url = f"{url}{high}/0_0.jpg"
    if is_url_ok(img_url):
        return high
    mid = (low + high) >> 1
    img_url = f"{url}{mid}/0_0.jpg"
    if is_url_ok(img_url):
        return binary_search(url, mid, high - 1)
    return binary_search(url, low, mid - 1)


def get_upper_limit(url):
    limit = 1
    img_url = f"{url}{limit}/0_0.jpg"
    while is_url_ok(img_url):
        limit <<= 1
        img_url = f"{url}{limit}/0_0.jpg"
    return limit


def get_max_zoom_level(url):
    upper_limit = get_upper_limit(url)
    return binary_search(url, upper_limit >> 1, upper_limit)


def get_script(url):
    response = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    html_content = response.text
    soup = BeautifulSoup(html_content, 'lxml')
    for script in soup.find_all('script'):
        if not re.search(SCRIPT_PATTERN, script.text):
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
            image_metadata.ImageMetadata(index=i, title=title, format=format, url=url, tile_size=tile_size, width=width,
                                         height=height, rows=rows, cols=cols, max_zoom_level=max_zoom_level))

    return image_metadatas
