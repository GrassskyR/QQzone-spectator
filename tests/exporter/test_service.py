"""Tests for qqzone_spectator.exporter.service."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from qqzone_spectator.db import Database
from qqzone_spectator.exporter.service import (
    ExportPostRecord,
    ExportMediaRecord,
    PdfExportService,
)
from qqzone_spectator.models import MediaItem, QzonePost


def _seed_db(db: Database, target_qq: str = "123", count: int = 3,
             with_media: bool = False) -> None:
    """Insert sample posts (and optionally media) into the database."""
    for i in range(count):
        post = QzonePost(
            target_qq=target_qq,
            author_qq=target_qq,
            post_id=f"tid_{i:03d}",
            content=f"Post content #{i}",
            created_at=f"2025-01-{i + 1:02d}T00:00:00+00:00",
            source_payload=json.dumps({"tid": f"tid_{i:03d}", "uin": int(target_qq)}),
            media=[MediaItem(url=f"https://img.com/{i}.jpg")] if with_media else [],
        )
        db.save_post(post)


class TestLoadPosts:
    def test_load_posts(self, tmp_db: Database):
        _seed_db(tmp_db, count=3)
        svc = PdfExportService(db=tmp_db, project_root=Path("."))
        posts = svc._load_posts(target_qq="123", limit=0)
        assert len(posts) == 3
        # should be DESC order
        assert posts[0].created_at >= posts[-1].created_at

    def test_load_posts_with_limit(self, tmp_db: Database):
        _seed_db(tmp_db, count=5)
        svc = PdfExportService(db=tmp_db, project_root=Path("."))
        posts = svc._load_posts(target_qq="123", limit=2)
        assert len(posts) == 2


class TestLoadMediaMap:
    def test_groups_by_post_id(self, tmp_db: Database):
        _seed_db(tmp_db, count=2, with_media=True)
        svc = PdfExportService(db=tmp_db, project_root=Path("."))
        media_map = svc._load_media_map(target_qq="123")
        assert "tid_000" in media_map
        assert len(media_map["tid_000"]) == 1


class TestRenderHtml:
    def _make_posts(self) -> list[ExportPostRecord]:
        return [
            ExportPostRecord(
                target_qq="123", author_qq="123", post_id="tid_001",
                content="Hello <World>", created_at="2025-01-01T00:00:00+00:00",
                inserted_at="2025-01-01T00:00:01+00:00",
            )
        ]

    def test_basic(self, tmp_db: Database):
        svc = PdfExportService(db=tmp_db, project_root=Path("."))
        html, count = svc._render_html(
            target_qq="123", posts=self._make_posts(), include_images=True,
        )
        assert "123" in html
        assert "Hello" in html
        assert count == 0  # no media attached

    def test_no_images_flag(self, tmp_db: Database):
        posts = self._make_posts()
        posts[0].media = [
            ExportMediaRecord(post_id="tid_001", media_url="https://img.com/a.jpg", local_path=""),
        ]
        svc = PdfExportService(db=tmp_db, project_root=Path("."))
        html, count = svc._render_html(
            target_qq="123", posts=posts, include_images=False,
        )
        assert "<img" not in html
        assert count == 0

    def test_escapes_content(self, tmp_db: Database):
        svc = PdfExportService(db=tmp_db, project_root=Path("."))
        html, _ = svc._render_html(
            target_qq="123", posts=self._make_posts(), include_images=True,
        )
        assert "&lt;World&gt;" in html  # HTML escaped

    def test_empty_content(self, tmp_db: Database):
        posts = self._make_posts()
        posts[0].content = ""
        svc = PdfExportService(db=tmp_db, project_root=Path("."))
        html, _ = svc._render_html(
            target_qq="123", posts=posts, include_images=True,
        )
        assert "(no text content)" in html


class TestBuildImageSrc:
    def test_valid_path(self, tmp_path: Path, tmp_db: Database):
        img = tmp_path / "test.jpg"
        img.write_bytes(b"fake")
        svc = PdfExportService(db=tmp_db, project_root=tmp_path)
        result = svc._build_image_src(str(img))
        assert result is not None
        assert result.startswith("file:///")

    def test_missing_path(self, tmp_path: Path, tmp_db: Database):
        svc = PdfExportService(db=tmp_db, project_root=tmp_path)
        result = svc._build_image_src("/nonexistent/image.jpg")
        assert result is None

    def test_empty_path(self, tmp_db: Database):
        svc = PdfExportService(db=tmp_db, project_root=Path("."))
        assert svc._build_image_src("") is None


class TestResolveMediaPath:
    def test_relative_path(self, tmp_path: Path, tmp_db: Database):
        (tmp_path / "data" / "media").mkdir(parents=True)
        img = tmp_path / "data" / "media" / "photo.jpg"
        img.write_bytes(b"data")

        svc = PdfExportService(db=tmp_db, project_root=tmp_path)
        result = svc._resolve_media_path("data/media/photo.jpg")
        assert result is not None
        assert result.name == "photo.jpg"
