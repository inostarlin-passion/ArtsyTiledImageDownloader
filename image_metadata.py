class ImageMetadata:
    def __init__(self, index, title, format, url, tile_size, width, height, rows, cols, max_zoom_level):
        self.index = index
        self.title = title
        self.format = format
        self.url = url
        self.tile_size = tile_size
        self.width = width
        self.height = height
        self.rows = rows
        self.cols = cols
        self.max_zoom_level = max_zoom_level

    def __str__(self):
        attrs = (f"{key}: {value}" for key, value in self.__dict__.items() if not key.startswith('_'))
        return "\n".join(attrs)
