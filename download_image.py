import asyncio
import os
import re
import shutil
from io import BytesIO

import httpx
from PIL import Image
from config import *


def safe_filename(value):
    filename = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return filename or "artwork"


def get_output_path(image_metadata):
    index = image_metadata.index
    title = safe_filename(image_metadata.title)
    format = image_metadata.format
    return os.path.join(FOLDER_PATH, f"output_{title}_{index}.{format}")


def download_direct_image(image_metadata):
    if not image_metadata.direct_urls:
        return None

    output_path = get_output_path(image_metadata)
    expected_size = (image_metadata.width, image_metadata.height)

    for direct_url in image_metadata.direct_urls:
        try:
            response = httpx.get(
                direct_url,
                headers=IMAGE_HEADERS,
                timeout=REQUEST_TIMEOUT,
                follow_redirects=True,
            )
            response.raise_for_status()

            with Image.open(BytesIO(response.content)) as img:
                actual_size = img.size

            if actual_size != expected_size:
                continue

            with open(output_path, "wb") as f:
                f.write(response.content)

            return output_path
        except (httpx.HTTPError, OSError, Image.UnidentifiedImageError):
            continue

    return None


def combine_images(image_metadata):
    output_path = get_output_path(image_metadata)
    format = image_metadata.format
    rows = image_metadata.rows
    cols = image_metadata.cols
    tile_size = image_metadata.tile_size
    overlap = image_metadata.overlap

    combined_image = Image.new("RGB", (image_metadata.width, image_metadata.height))
    for i in range(rows):
        for j in range(cols):
            img_path = os.path.join(TEMP_IMGS_PATH, f"{j}_{i}.{format}")
            with Image.open(img_path) as img:
                left = overlap if j > 0 else 0
                top = overlap if i > 0 else 0
                tile_width = min(tile_size, image_metadata.width - j * tile_size)
                tile_height = min(tile_size, image_metadata.height - i * tile_size)
                tile = img.crop((left, top, left + tile_width, top + tile_height))
                combined_image.paste(tile, (j * tile_size, i * tile_size))

    combined_image.save(output_path)
    return output_path


def write_tile(path, content):
    with open(path, "wb") as f:
        f.write(content)


async def download_tile_image(client, semaphore, img_url, file_path):
    async with semaphore:
        for attempt in range(DOWNLOAD_RETRIES):
            try:
                response = await client.get(img_url)
                response.raise_for_status()
                await asyncio.to_thread(write_tile, file_path, response.content)
                return
            except (httpx.HTTPError, OSError):
                if attempt == DOWNLOAD_RETRIES - 1:
                    raise
                await asyncio.sleep(0.5 * (attempt + 1))


async def download_tile_images(tile_requests):
    timeout = httpx.Timeout(REQUEST_TIMEOUT)
    limits = httpx.Limits(
        max_connections=MAX_WORKERS,
        max_keepalive_connections=MAX_WORKERS,
    )
    semaphore = asyncio.Semaphore(MAX_WORKERS)
    tasks = []

    try:
        async with httpx.AsyncClient(
            headers=IMAGE_HEADERS,
            http2=True,
            timeout=timeout,
            limits=limits,
            follow_redirects=True,
        ) as client:
            tasks = [
                asyncio.create_task(
                    download_tile_image(client, semaphore, img_url, file_path)
                )
                for img_url, file_path in tile_requests
            ]

            for task in asyncio.as_completed(tasks):
                await task
    except Exception:
        for task in tasks:
            task.cancel()
        raise


def download_full_image(image_metadata):
    direct_output_path = download_direct_image(image_metadata)
    if direct_output_path:
        return direct_output_path, "direct"

    format = image_metadata.format
    url = image_metadata.url
    rows = image_metadata.rows
    cols = image_metadata.cols

    if os.path.exists(TEMP_IMGS_PATH):
        shutil.rmtree(TEMP_IMGS_PATH)

    os.makedirs(TEMP_IMGS_PATH)

    tile_requests = [
        (
            f"{url}{i % cols}_{int(i / cols)}.{format}",
            os.path.join(TEMP_IMGS_PATH, f"{i % cols}_{int(i / cols)}.{format}"),
        )
        for i in range(rows * cols)
    ]
    asyncio.run(download_tile_images(tile_requests))
    return combine_images(image_metadata), "tiles"
