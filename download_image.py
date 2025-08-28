import os
import shutil

import requests
from PIL import Image


def combine_images(folder_path, temp_imgs_path, image_metadata):
    index = image_metadata.index
    title = image_metadata.title
    format = image_metadata.format
    rows = image_metadata.rows
    cols = image_metadata.cols
    output_path = f'{folder_path}output_{title}_{index}.{format}'
    img_width = 0
    img_height = 0

    for i in range(cols):
        img_path = f'{temp_imgs_path}{i}_0.{format}'
        with Image.open(img_path) as img:
            img_width += img.width
    for i in range(rows):
        img_path = f'{temp_imgs_path}0_{i}.{format}'
        with Image.open(img_path) as img:
            img_height += img.height

    combined_image = Image.new('RGB', (img_width, img_height))
    x_offset = 0
    y_offset = 0
    for i in range(rows):
        for j in range(cols):
            img_path = f'{temp_imgs_path}{j}_{i}.{format}'
            with Image.open(img_path) as img:
                combined_image.paste(img, (x_offset, y_offset))
                x_offset += img.width
        x_offset = 0
        y_offset += img.height

    combined_image.save(output_path)
    print(f"combined images saved to {output_path}")


def download_image(folder_path, temp_imgs_path, image_metadata):
    format = image_metadata.format
    url = image_metadata.url
    rows = image_metadata.rows
    cols = image_metadata.cols

    try:
        shutil.rmtree(temp_imgs_path)
    except FileNotFoundError:
        pass

    os.makedirs(temp_imgs_path)

    for i in range(rows):
        for j in range(cols):
            file_name = f"{j}_{i}.{format}"
            img_url = f"{url}{file_name}"
            response = requests.get(img_url, timeout=10)
            response.raise_for_status()
            with open(temp_imgs_path + file_name, "wb") as f:
                f.write(response.content)
            print(f"{file_name} downloaded")

    combine_images(folder_path, temp_imgs_path, image_metadata)
