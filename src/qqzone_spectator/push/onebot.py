from __future__ import annotations

from pathlib import Path
from typing import Any

import requests

from ..models import QzonePost


class OneBotClient:
    def __init__(self, base_url: str, *, access_token: str = "", timeout: int = 15) -> None:
        if not base_url:
            raise ValueError("ONEBOT_BASE_URL is required")

        self.base_url = base_url.rstrip("/")
        self.access_token = access_token
        self.timeout = timeout

    def send_private_msg(self, user_id: int, message: str) -> dict[str, Any]:
        return self._request("send_private_msg", {"user_id": user_id, "message": message})

    def send_group_msg(self, group_id: int, message: str) -> dict[str, Any]:
        return self._request("send_group_msg", {"group_id": group_id, "message": message})

    def _request(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"

        response = requests.post(
            f"{self.base_url}/{action}",
            json=payload,
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()

        result = response.json()
        if not isinstance(result, dict):
            raise RuntimeError("OneBot response is not a JSON object")

        status = result.get("status")
        retcode = int(result.get("retcode", 0))
        if status == "failed" or retcode != 0:
            raise RuntimeError(f"OneBot action failed: {result}")

        return result


def build_post_message(post: QzonePost, media_paths: list[str]) -> str:
    text = post.content.strip() if post.content.strip() else "(no text content)"
    lines = [
        f"[QQZone] target={post.target_qq}",
        f"post={post.post_id}",
        f"time={post.created_at}",
        text,
    ]
    message = "\n".join(lines)

    if media_paths:
        images = "".join(f"[CQ:image,file={Path(path).resolve().as_uri()}]" for path in media_paths)
        message = f"{message}\n{images}"

    return message
