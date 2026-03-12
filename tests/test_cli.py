"""Tests for qqzone_spectator.cli."""
from __future__ import annotations

from pathlib import Path

import pytest

from qqzone_spectator.cli import build_parser, require_crawl_config
from qqzone_spectator.config import AppConfig


# ---------------------------------------------------------------------------
# build_parser
# ---------------------------------------------------------------------------
class TestBuildParser:
    def test_init_db(self):
        parser = build_parser()
        args = parser.parse_args(["init-db"])
        assert args.command == "init-db"

    def test_list_targets(self):
        parser = build_parser()
        args = parser.parse_args(["list-targets"])
        assert args.command == "list-targets"

    def test_crawl_once(self):
        parser = build_parser()
        args = parser.parse_args(["crawl-once", "--no-push"])
        assert args.command == "crawl-once"
        assert args.no_push is True

    def test_run(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--interval", "60"])
        assert args.command == "run"
        assert args.interval == 60

    def test_export_pdf(self):
        parser = build_parser()
        args = parser.parse_args([
            "export-pdf", "--target-qq", "123", "--no-images", "--limit", "10",
        ])
        assert args.command == "export-pdf"
        assert args.target_qq == "123"
        assert args.no_images is True
        assert args.limit == 10

    def test_log_level(self):
        parser = build_parser()
        args = parser.parse_args(["--log-level", "DEBUG", "init-db"])
        assert args.log_level == "DEBUG"


# ---------------------------------------------------------------------------
# require_crawl_config
# ---------------------------------------------------------------------------
class TestRequireCrawlConfig:
    def _make_config(self, uin: str = "", cookie: str = "") -> AppConfig:
        return AppConfig(
            project_root=Path("."),
            db_path=Path("test.db"), media_dir=Path("media"),
            qzone_uin=uin, qzone_cookie=cookie, target_qqs=[],
            fetch_limit=1, poll_interval_seconds=30, request_timeout=5,
            onebot_base_url="", onebot_access_token="",
            push_private_users=[], push_groups=[],
        )

    def test_missing_uin(self):
        with pytest.raises(RuntimeError, match="QZONE_UIN"):
            require_crawl_config(self._make_config(cookie="x"))

    def test_missing_cookie(self):
        with pytest.raises(RuntimeError, match="QZONE_COOKIE"):
            require_crawl_config(self._make_config(uin="x"))

    def test_valid(self):
        require_crawl_config(self._make_config(uin="123", cookie="abc"))
