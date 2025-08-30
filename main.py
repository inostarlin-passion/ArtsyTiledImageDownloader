#!/usr/bin/env python3
import atexit
import shutil
import sys
import time

import get_metadatas
import download_image
from config import *


def remove_temp_imgs_path():
    try:
        if os.path.exists(TEMP_IMGS_PATH):
            shutil.rmtree(TEMP_IMGS_PATH)
    except Exception:
        pass


def main(url):
    timestamp = time.time()

    try:
        image_metadatas = get_metadatas.get_metadatas(url)
    except Exception as e:
        sys.exit(f"get metadatas error: {e}")

    for i, image_metadata in enumerate(image_metadatas):
        print(f'---downloading image {i + 1}/{len(image_metadatas)}---')
        print(image_metadata)

        try:
            download_image.download_full_image(image_metadata)
        except Exception as e:
            sys.exit(f"download image error: {e}")

        print("done.\n")

    print("all done.")
    print(f"time elapsed: {int(time.time() - timestamp)}s")


if __name__ == "__main__":
    atexit.register(remove_temp_imgs_path)
    if len(sys.argv) < 2:
        sys.exit("no url provided")
    url = sys.argv[1]
    main(url)
