#!/usr/bin/env python3

import os
import shutil
import sys

import get_metadatas
import download_image

folder_path = os.path.expanduser("~/Downloads/")
temp_imgs_path = folder_path + "temp_imgs/"


def main(url):
    try:
        image_metadatas = get_metadatas.get_metadatas(url)
    except Exception as e:
        sys.exit(f"get metadatas error: {e}")

    for i, image_metadata in enumerate(image_metadatas):
        print(f'---downloading image {i + 1}/{len(image_metadatas)}---')
        print(f"index: {image_metadata.index}")
        print(f"title: {image_metadata.title}")
        print(f"format: {image_metadata.format}")
        print(f"url: {image_metadata.url}")
        print(f"tile_size: {image_metadata.tile_size}")
        print(f"width: {image_metadata.width}")
        print(f"height: {image_metadata.height}")
        print(f"rows: {image_metadata.rows}")
        print(f"cols: {image_metadata.cols}")
        print(f"max_zoom_level: {image_metadata.max_zoom_level}")

        try:
            download_image.download_image(folder_path, temp_imgs_path, image_metadata)
        except Exception as e:
            sys.exit(f"download image error: {e}")

        print("done.\n")

    try:
        shutil.rmtree(temp_imgs_path)
    except Exception:
        pass

    print("all done.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("no url provided")
    url = sys.argv[1]
    main(url)
