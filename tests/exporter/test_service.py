"""Tests for qqzone_spectator.exporter.service."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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

    def test_embeds_existing_images(self, tmp_path: Path, tmp_db: Database):
        img = tmp_path / "data" / "media" / "photo.jpg"
        img.parent.mkdir(parents=True)
        img.write_bytes(b"data")

        posts = self._make_posts()
        posts[0].media = [
            ExportMediaRecord(
                post_id="tid_001",
                media_url="https://img.com/a.jpg",
                local_path="data/media/photo.jpg",
            ),
        ]
        svc = PdfExportService(db=tmp_db, project_root=tmp_path)

        html, count = svc._render_html(
            target_qq="123",
            posts=posts,
            include_images=True,
        )

        assert '<div class="image-grid">' in html
        assert "file:///" in html
        assert count == 1


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

    def test_uri_error_returns_none(self, tmp_db: Database):
        svc = PdfExportService(db=tmp_db, project_root=Path("."))
        mock_resolved = MagicMock()
        mock_resolved.as_uri.side_effect = ValueError("bad uri")
        mock_path = MagicMock()
        mock_path.resolve.return_value = mock_resolved

        with patch.object(svc, "_resolve_media_path", return_value=mock_path):
            assert svc._build_image_src("bad/path.jpg") is None


class TestResolveMediaPath:
    def test_relative_path(self, tmp_path: Path, tmp_db: Database):
        (tmp_path / "data" / "media").mkdir(parents=True)
        img = tmp_path / "data" / "media" / "photo.jpg"
        img.write_bytes(b"data")

        svc = PdfExportService(db=tmp_db, project_root=tmp_path)
        result = svc._resolve_media_path("data/media/photo.jpg")
        assert result is not None
        assert result.name == "photo.jpg"


class TestExportTargetTimelinePdf:
    def test_exports_relative_path_and_returns_counts(
        self,
        tmp_path: Path,
        tmp_db: Database,
    ):
        _seed_db(tmp_db, count=1, with_media=True)
        img = tmp_path / "data" / "media" / "photo.jpg"
        img.parent.mkdir(parents=True)
        img.write_bytes(b"data")
        tmp_db.update_media_local_path(
            "123",
            "tid_000",
            "https://img.com/0.jpg",
            "data/media/photo.jpg",
        )

        svc = PdfExportService(db=tmp_db, project_root=tmp_path)
        with patch.object(svc, "_render_pdf") as mock_render_pdf:
            result = svc.export_target_timeline_pdf(
                target_qq="123",
                output_path=Path("exports") / "timeline.pdf",
                include_images=True,
                limit=1,
            )

        assert result.output_path == tmp_path / "exports" / "timeline.pdf"
        assert result.post_count == 1
        assert result.embedded_image_count == 1
        mock_render_pdf.assert_called_once()
        assert mock_render_pdf.call_args.kwargs["output_path"] == tmp_path / "exports" / "timeline.pdf"
        assert "QQZone Timeline Export" in mock_render_pdf.call_args.kwargs["html_content"]

    def test_preserves_absolute_output_path(self, tmp_path: Path, tmp_db: Database):
        _seed_db(tmp_db, count=1)
        svc = PdfExportService(db=tmp_db, project_root=tmp_path)
        output_path = tmp_path / "nested" / "timeline.pdf"

        with patch.object(svc, "_render_pdf") as mock_render_pdf:
            result = svc.export_target_timeline_pdf(
                target_qq="123",
                output_path=output_path,
                include_images=False,
                limit=1,
            )

        assert result.output_path == output_path
        mock_render_pdf.assert_called_once_with(
            html_content=mock_render_pdf.call_args.kwargs["html_content"],
            output_path=output_path,
        )

    def test_raises_when_target_has_no_posts(self, tmp_db: Database):
        svc = PdfExportService(db=tmp_db, project_root=Path("."))

        with pytest.raises(RuntimeError, match="No posts found"):
            svc.export_target_timeline_pdf(
                target_qq="404",
                output_path=Path("exports") / "timeline.pdf",
            )


class _FakePage:
    def __init__(self) -> None:
        self.timeout = None
        self.goto_args: tuple[str, str] | None = None
        self.emulated_media: str | None = None
        self.pdf_kwargs: dict[str, object] | None = None

    def set_default_timeout(self, value: int) -> None:
        self.timeout = value

    def goto(self, url: str, *, wait_until: str) -> None:
        self.goto_args = (url, wait_until)

    def emulate_media(self, *, media: str) -> None:
        self.emulated_media = media

    def pdf(self, **kwargs: object) -> None:
        self.pdf_kwargs = kwargs


class _FakeBrowser:
    def __init__(self, page: _FakePage) -> None:
        self.page = page
        self.closed = False

    def new_page(self) -> _FakePage:
        return self.page

    def close(self) -> None:
        self.closed = True


class _FakePlaywrightContext:
    def __init__(self, browser: _FakeBrowser) -> None:
        self.browser = browser
        self.launch_kwargs: dict[str, object] | None = None
        self.chromium = SimpleNamespace(launch=self._launch)

    def _launch(self, **kwargs: object) -> _FakeBrowser:
        self.launch_kwargs = kwargs
        return self.browser

    def __enter__(self) -> "_FakePlaywrightContext":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class TestRenderPdf:
    def test_renders_with_playwright(self, tmp_path: Path, tmp_db: Database):
        svc = PdfExportService(db=tmp_db, project_root=tmp_path)
        page = _FakePage()
        browser = _FakeBrowser(page)
        context = _FakePlaywrightContext(browser)
        output_path = tmp_path / "timeline.pdf"

        with patch("playwright.sync_api.sync_playwright", return_value=context):
            svc._render_pdf(html_content="<html><body>ok</body></html>", output_path=output_path)

        assert context.launch_kwargs == {
            "headless": True,
            "args": ["--disable-dev-shm-usage"],
        }
        assert page.timeout == 300000
        assert page.goto_args is not None
        assert page.goto_args[0].startswith("file:///")
        assert page.goto_args[1] == "networkidle"
        assert page.emulated_media == "print"
        assert page.pdf_kwargs is not None
        assert page.pdf_kwargs["path"] == str(output_path)
        assert page.pdf_kwargs["format"] == "A4"
        assert browser.closed is True
