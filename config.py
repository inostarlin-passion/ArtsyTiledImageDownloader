import os

REQUEST_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

REQUEST_TIMEOUT = 10

SCRIPT_PATTERN = r"^\s*var __RELAY_HYDRATION_DATA__ = "

FOLDER_PATH = os.path.expanduser("~/Downloads/")

TEMP_IMGS_PATH = FOLDER_PATH + ".temp_imgs/"

MAX_WORKERS = 10
