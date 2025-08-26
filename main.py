#!/usr/bin/env python3

import math
import os
import shutil
import sys

import get_max_zoom_level
import get_script
import get_metadata
import download_images
import combine_images

folder_path = os.path.expanduser("~/Downloads/")
temp_imgs_path = folder_path + "temp_imgs/"


def main():
    if len(sys.argv) < 2:
        sys.exit("no url provided")
    url = sys.argv[1]

    try:
        script = get_script.get_script(url)
    except Exception as e:
        sys.exit(f"get script error: {e}")

    try:
        url, format, tile_size, width, height = get_metadata.get_metadata(script)
    except Exception as e:
        sys.exit(f"get metadata error: {e}")

    if format != 'jpg':
        sys.exit("format not jpg")

    print(f"url: {url}")
    print(f"format: {format}")
    print(f"tile_size: {tile_size}")
    print(f"width: {width}")
    print(f"height: {height}")

    rows = math.ceil(height / tile_size)
    cols = math.ceil(width / tile_size)
    print(f"rows: {rows}")
    print(f"cols: {cols}")

    max_zoom_level = get_max_zoom_level.get_max_zoom_level(url)
    if not max_zoom_level:
        sys.exit("get max_zoom_level error")
    print(f"max_zoom_level: {max_zoom_level}")

    try:
        shutil.rmtree(temp_imgs_path)
    except FileNotFoundError:
        pass
    except OSError as e:
        sys.exit(f"remove folder error: {e}")

    try:
        os.makedirs(temp_imgs_path, exist_ok=True)
    except OSError as e:
        sys.exit(f"create folder error: {e}")

    url += f"{max_zoom_level}/"
    try:
        download_images.download_images(url, temp_imgs_path, rows, cols)
    except Exception as e:
        sys.exit(f"download images error: {e}")

    try:
        combine_images.combine_images(folder_path, temp_imgs_path, rows, cols)
    except Exception as e:
        sys.exit(f"combine images error: {e}")

    print("done.")


if __name__ == "__main__":
    main()
