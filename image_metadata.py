class ImageMetadata:
    def __init__(
        self,
        index,
        title,
        format,
        url,
        tile_size,
        overlap,
        width,
        height,
        rows,
        cols,
        max_zoom_level,
        direct_urls=None,
    ):
        self.index = index
        self.title = title
        self.format = format
        self.url = url
        self.tile_size = tile_size
        self.overlap = overlap
        self.width = width
        self.height = height
        self.rows = rows
        self.cols = cols
        self.max_zoom_level = max_zoom_level
        self.direct_urls = direct_urls or []

    def __str__(self):
        attrs = []
        for key, value in self.__dict__.items():
            if key.startswith("_"):
                continue
            if key == "direct_urls":
                attrs.append(f"{key}: {len(value)} candidates")
                continue
            attrs.append(f"{key}: {value}")
        return "\n".join(attrs)
