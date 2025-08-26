import requests


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
