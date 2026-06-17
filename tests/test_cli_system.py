from __future__ import annotations

import json
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from PIL import Image


class QuietHandler(BaseHTTPRequestHandler):
    tile_base_url = ""
    image_bytes = None

    def log_message(self, format: str, *args) -> None:
        return None

    def do_POST(self) -> None:
        _ = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        payload = {
            "data": {
                "artworkResult": {
                    "__typename": "Artwork",
                    "slug": "local-test",
                    "images": [],
                    "figures": [
                        {
                            "__typename": "Image",
                            "internalID": "image-1",
                            "isZoomable": True,
                            "deepZoom": {
                                "Image": {
                                    "Url": self.tile_base_url,
                                    "Format": "png",
                                    "TileSize": 2,
                                    "Overlap": 1,
                                    "Size": {"Width": 4, "Height": 4},
                                }
                            },
                        }
                    ],
                }
            }
        }
        self._send(200, json.dumps(payload).encode(), "application/json")

    def do_GET(self) -> None:
        assert self.image_bytes is not None
        self._send(200, self.image_bytes, "image/png")

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_cli_end_to_end_with_local_http_server(
    tmp_path: Path,
    project_root: Path,
    image_bytes,
) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
    host, port = server.server_address
    QuietHandler.tile_base_url = f"http://{host}:{port}/tiles/"
    QuietHandler.image_bytes = image_bytes((3, 3), (120, 30, 200))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "artsy_tiled_image_downloader",
                "--endpoint",
                f"http://{host}:{port}/graphql",
                "--output-dir",
                str(tmp_path),
                "--concurrency",
                "2",
                "--skip-direct",
                "https://www.artsy.net/artwork/local-test",
            ],
            cwd=project_root,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert result.returncode == 0, result.stderr
    output = tmp_path / "output_local-test_0.png"
    assert output.exists()
    with Image.open(output) as image:
        assert image.size == (4, 4)
        assert image.getpixel((3, 3)) == (120, 30, 200)
    assert "Saved:" in result.stdout
