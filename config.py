import os

REQUEST_HEADERS = {
    "User-Agent": "ArtsyTiledImageDownloader/1.0",
}

GRAPHQL_HEADERS = {
    **REQUEST_HEADERS,
    "Accept": "application/json",
    "Content-Type": "application/json",
}

IMAGE_HEADERS = {
    **REQUEST_HEADERS,
    "Accept": "image/avif,image/webp,image/jpeg,image/*,*/*;q=0.8",
}

REQUEST_TIMEOUT = 10

METAPHYSICS_ENDPOINT = "https://metaphysics-production.artsy.net/v2"

FOLDER_PATH = os.path.expanduser("~/Downloads/")

TEMP_IMGS_PATH = FOLDER_PATH + ".temp_imgs/"

MAX_WORKERS = 10

DOWNLOAD_RETRIES = 3
