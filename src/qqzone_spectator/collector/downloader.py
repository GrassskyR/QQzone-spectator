from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import requests


def sanitize(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]", "_", value)
    return sanitized[:96] if sanitized else "unknown"


class MediaDownloader:
    def __init__(self, media_dir: Path) -> None:
        self.media_dir = Path(media_dir)
        self.media_dir.mkdir(parents=True, exist_ok=True)

    def download_image(
        self,
        *,
        media_url: str,
        target_qq: str,
        post_id: str,
        index: int,
        timeout: int = 20,
    ) -> str | None:
        if not media_url:
            return None

        parsed = urlparse(media_url)
        ext = Path(parsed.path).suffix.lower()
        if ext not in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}:
            ext = ".jpg"

        target_dir = self.media_dir / sanitize(target_qq)
        target_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{sanitize(post_id)}_{index:02d}{ext}"
        file_path = target_dir / filename

        if file_path.exists() and file_path.stat().st_size > 0:
            return str(file_path)

        response = requests.get(media_url, timeout=timeout)
        response.raise_for_status()
        file_path.write_bytes(response.content)
        return str(file_path)
