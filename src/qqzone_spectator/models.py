from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class MediaItem:
    url: str
    media_type: str = "image"
    local_path: str | None = None


@dataclass(slots=True)
class QzonePost:
    target_qq: str
    author_qq: str
    post_id: str
    content: str
    created_at: str
    source_payload: str
    media: list[MediaItem] = field(default_factory=list)
