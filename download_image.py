import concurrent.futures
import shutil

import requests
from PIL import Image
from config import *


def combine_images(image_metadata):
    index = image_metadata.index
    title = image_metadata.title
    format = image_metadata.format
    rows = image_metadata.rows
    cols = image_metadata.cols
    output_path = f'{FOLDER_PATH}output_{title}_{index}.{format}'
    img_width = 0
    img_height = 0

    for i in range(cols):
        img_path = f'{TEMP_IMGS_PATH}{i}_0.{format}'
        with Image.open(img_path) as img:
            img_width += img.width
    for i in range(rows):
        img_path = f'{TEMP_IMGS_PATH}0_{i}.{format}'
        with Image.open(img_path) as img:
            img_height += img.height

    combined_image = Image.new('RGB', (img_width, img_height))
    x_offset = 0
    y_offset = 0
    for i in range(rows):
        for j in range(cols):
            img_path = f'{TEMP_IMGS_PATH}{j}_{i}.{format}'
            with Image.open(img_path) as img:
                combined_image.paste(img, (x_offset, y_offset))
                x_offset += img.width
        x_offset = 0
        y_offset += img.height

    combined_image.save(output_path)
    print(f"combined images saved to {output_path}")


def download_tile_image(arg):
    img_url = arg[0]
    file_name = arg[1]

    try:
        response = requests.get(img_url, timeout=10)
        response.raise_for_status()
    except Exception as e:
        return e

    try:
        with open(TEMP_IMGS_PATH + file_name, "wb") as f:
            f.write(response.content)
    except Exception as e:
        return e

    print(f"{file_name} downloaded")


def download_full_image(image_metadata):
    format = image_metadata.format
    url = image_metadata.url
    rows = image_metadata.rows
    cols = image_metadata.cols

    if os.path.exists(TEMP_IMGS_PATH):
        shutil.rmtree(TEMP_IMGS_PATH)

    os.makedirs(TEMP_IMGS_PATH)

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        args = [(f"{url}{i % cols}_{int(i / cols)}.{format}", f"{i % cols}_{int(i / cols)}.{format}") for i in
                range(rows * cols)]
        results = executor.map(download_tile_image, args)

    for result in results:
        if result:
            raise result

    combine_images(image_metadata)
