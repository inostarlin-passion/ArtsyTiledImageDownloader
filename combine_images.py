import datetime
from PIL import Image


def combine_images(folder_path, temp_imgs_path, rows, cols):
    now = datetime.datetime.now()
    timestamp_str = now.strftime('%Y-%m-%d_%H-%M-%S')
    output_path = f'{folder_path}output_{timestamp_str}.jpg'
    img_width = 0
    img_height = 0
    for i in range(cols):
        img_path = f'{temp_imgs_path}{i}_0.jpg'
        with Image.open(img_path) as img:
            img_width += img.width
    for i in range(rows):
        img_path = f'{temp_imgs_path}0_{i}.jpg'
        with Image.open(img_path) as img:
            img_height += img.height

    combined_image = Image.new('RGB', (img_width, img_height))
    x_offset = 0
    y_offset = 0
    for i in range(rows):
        for j in range(cols):
            img_path = f'{temp_imgs_path}{j}_{i}.jpg'
            with Image.open(img_path) as img:
                combined_image.paste(img, (x_offset, y_offset))
                x_offset += img.width
        x_offset = 0
        y_offset += img.height

    combined_image.save(output_path)
    print(f"combined images saved to {output_path}")
