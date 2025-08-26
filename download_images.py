import requests


def download_images(url, folder_path, rows, cols):
    for i in range(rows):
        for j in range(cols):
            file_name = f"{j}_{i}.jpg"
            img_url = f"{url}{file_name}"
            response = requests.get(img_url, timeout=10)
            response.raise_for_status()
            with open(folder_path + file_name, "wb") as f:
                f.write(response.content)
            print(f"{file_name} downloaded")
