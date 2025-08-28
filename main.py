#!/usr/bin/env python3
import atexit
import shutil
import sys
import time

import get_metadatas
import download_image
from config import *


def log(message=""):
    print(message, flush=True)


def remove_temp_imgs_path():
    try:
        if os.path.exists(TEMP_IMGS_PATH):
            shutil.rmtree(TEMP_IMGS_PATH)
    except Exception:
        pass


def main(url):
    timestamp = time.time()
    log(f"URL: {url}")
    log("Fetching metadata...")

    try:
        image_metadatas = get_metadatas.get_metadatas(url)
    except Exception as e:
        sys.exit(f"get metadatas error: {e}")

    log(f"Images: {len(image_metadatas)}")
    for i, image_metadata in enumerate(image_metadatas):
        resolution = f"{image_metadata.width}x{image_metadata.height}"
        log(f"Image {i + 1}/{len(image_metadatas)}: {resolution}")
        log("Downloading...")

        try:
            output_path, method = download_image.download_full_image(image_metadata)
        except Exception as e:
            sys.exit(f"download image error: {e}")

        log(f"Saved: {output_path} ({method})")

    log(f"Elapsed: {time.time() - timestamp:.1f}s")


if __name__ == "__main__":
    atexit.register(remove_temp_imgs_path)
    if len(sys.argv) < 2:
        sys.exit("no url provided")
    url = sys.argv[1]
    main(url)
