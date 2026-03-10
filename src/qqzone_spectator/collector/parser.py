from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from ..models import MediaItem, QzonePost

MEDIA_URL_KEYS = (
    "url3",
    "url2",
    "url1",
    "origin_url",
    "raw",
    "url",
    "picurl",
    "smallurl",
)


def parse_posts(target_qq: str, raw_posts: list[dict[str, Any]]) -> list[QzonePost]:
    posts: list[QzonePost] = []
    for raw in raw_posts:
        post_id = _extract_post_id(raw)
        content = _extract_content(raw)
        created_at = _extract_created_at(raw)
        media_items = _extract_media(raw)
        payload = json.dumps(raw, ensure_ascii=False, separators=(",", ":"))

        posts.append(
            QzonePost(
                target_qq=target_qq,
                post_id=post_id,
                content=content,
                created_at=created_at,
                source_payload=payload,
                media=media_items,
            )
        )

    posts.sort(key=lambda item: item.created_at)
    return posts


def _extract_post_id(raw: dict[str, Any]) -> str:
    for key in ("tid", "id", "unikey", "fwd_tid"):
        value = raw.get(key)
        if value:
            return str(value)

    digest = hashlib.sha1(
        json.dumps(raw, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return digest[:20]


def _extract_content(raw: dict[str, Any]) -> str:
    content = raw.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()

    summary = raw.get("summary")
    if isinstance(summary, str):
        return summary.strip()
    if isinstance(summary, dict):
        summary_content = summary.get("content")
        if isinstance(summary_content, str):
            return summary_content.strip()

    return ""


def _extract_created_at(raw: dict[str, Any]) -> str:
    candidates = ("created_time", "created_time_abs", "pubtime", "time")
    for key in candidates:
        value = raw.get(key)
        normalized = _normalize_time(value)
        if normalized:
            return normalized
    return datetime.now(timezone.utc).isoformat()


def _normalize_time(value: Any) -> str | None:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        if value <= 0:
            return None
        return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.isdigit():
            return datetime.fromtimestamp(int(text), tz=timezone.utc).isoformat()
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(
                timezone.utc
            ).isoformat()
        except ValueError:
            return None

    return None


def _extract_media(raw: dict[str, Any]) -> list[MediaItem]:
    candidates: list[Any] = []
    for key in ("pic", "pics", "photos"):
        value = raw.get(key)
        if isinstance(value, list):
            candidates.extend(value)

    items: list[MediaItem] = []
    seen: set[str] = set()

    for item in candidates:
        url = _extract_media_url(item)
        if not url or url in seen:
            continue
        seen.add(url)
        items.append(MediaItem(url=url, media_type="image"))

    return items


def _extract_media_url(item: Any) -> str:
    if isinstance(item, str):
        return item.strip()

    if isinstance(item, dict):
        for key in MEDIA_URL_KEYS:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    return ""
