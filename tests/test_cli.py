"""Tests for qqzone_spectator.cli."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from qqzone_spectator.cli import build_parser, main, require_crawl_config
from qqzone_spectator.config import AppConfig


def _make_config(
    tmp_path: Path,
    *,
    uin: str = "123456",
    cookie: str = "uin=o123456; p_skey=abc;",
    poll_interval_seconds: int = 300,
) -> AppConfig:
    return AppConfig(
        project_root=tmp_path,
        db_path=tmp_path / "data" / "test.db",
        media_dir=tmp_path / "data" / "media",
        qzone_uin=uin,
        qzone_cookie=cookie,
        target_qqs=["123456", "654321"],
        fetch_limit=20,
        poll_interval_seconds=poll_interval_seconds,
        request_timeout=10,
        onebot_base_url="http://127.0.0.1:5700",
        onebot_access_token="token",
        push_private_users=[111],
        push_groups=[222],
    )


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

    def test_log_level_after_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--log-level", "DEBUG"])
        assert args.command == "run"
        assert args.log_level == "DEBUG"

    def test_env_file_after_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["crawl-once", "--env-file", ".env.test"])
        assert args.command == "crawl-once"
        assert args.env_file == ".env.test"


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


class TestMain:
    def test_init_db_prints_summary_and_closes_db(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ):
        config = _make_config(tmp_path, uin="", cookie="")
        mock_db = MagicMock()
        mock_db.list_targets.return_value = ["111", "222"]

        monkeypatch.setattr(sys, "argv", ["qqzone-spectator", "init-db"])

        with (
            patch("qqzone_spectator.cli.AppConfig.from_env", return_value=config),
            patch("qqzone_spectator.cli.Database", return_value=mock_db),
        ):
            main()

        assert capsys.readouterr().out.strip().splitlines() == [
            f"database initialized: {config.db_path}",
            "enabled targets: 2",
        ]
        mock_db.init_schema.assert_called_once_with()
        mock_db.upsert_targets.assert_called_once_with(config.target_qqs)
        mock_db.close.assert_called_once_with()

    def test_list_targets_prints_empty_message(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ):
        config = _make_config(tmp_path, uin="", cookie="")
        mock_db = MagicMock()
        mock_db.list_targets.return_value = []

        monkeypatch.setattr(sys, "argv", ["qqzone-spectator", "list-targets"])

        with (
            patch("qqzone_spectator.cli.AppConfig.from_env", return_value=config),
            patch("qqzone_spectator.cli.Database", return_value=mock_db),
        ):
            main()

        assert capsys.readouterr().out.strip() == "no enabled targets"
        mock_db.close.assert_called_once_with()

    def test_export_pdf_uses_default_output_and_clamps_limit(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ):
        config = _make_config(tmp_path, uin="", cookie="")
        mock_db = MagicMock()
        mock_exporter = MagicMock()
        mock_exporter.export_target_timeline_pdf.return_value = SimpleNamespace(
            target_qq="123",
            post_count=2,
            embedded_image_count=1,
            output_path=tmp_path / "exports" / "123_20260101_010203.pdf",
        )
        mock_now = MagicMock()
        mock_now.strftime.return_value = "20260101_010203"

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "qqzone-spectator",
                "export-pdf",
                "--target-qq",
                "123",
                "--no-images",
                "--limit",
                "-5",
            ],
        )

        with (
            patch("qqzone_spectator.cli.AppConfig.from_env", return_value=config),
            patch("qqzone_spectator.cli.Database", return_value=mock_db),
            patch("qqzone_spectator.cli.PdfExportService", return_value=mock_exporter),
            patch("qqzone_spectator.cli.datetime") as mock_datetime,
        ):
            mock_datetime.now.return_value = mock_now
            main()

        mock_exporter.export_target_timeline_pdf.assert_called_once_with(
            target_qq="123",
            output_path=Path("exports") / "123_20260101_010203.pdf",
            include_images=False,
            limit=0,
        )
        assert capsys.readouterr().out.strip() == (
            "exported target=123 posts=2 embedded_images=1 "
            f"file={tmp_path / 'exports' / '123_20260101_010203.pdf'}"
        )
        mock_db.close.assert_called_once_with()

    def test_crawl_once_prints_result(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ):
        config = _make_config(tmp_path)
        mock_db = MagicMock()
        mock_service = MagicMock()
        mock_service.crawl_once.return_value = {
            "fetched": 3,
            "inserted": 2,
            "skipped_owner_mismatch": 1,
        }

        monkeypatch.setattr(sys, "argv", ["qqzone-spectator", "crawl-once", "--no-push"])

        with (
            patch("qqzone_spectator.cli.AppConfig.from_env", return_value=config),
            patch("qqzone_spectator.cli.Database", return_value=mock_db),
            patch("qqzone_spectator.cli.SchedulerService.from_config", return_value=mock_service),
        ):
            main()

        mock_service.crawl_once.assert_called_once_with(push_enabled=False)
        assert capsys.readouterr().out.strip() == (
            "fetched=3 inserted=2 skipped_owner_mismatch=1"
        )
        mock_db.close.assert_called_once_with()

    def test_run_uses_config_interval(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        config = _make_config(tmp_path, poll_interval_seconds=900)
        mock_db = MagicMock()
        mock_service = MagicMock()

        monkeypatch.setattr(sys, "argv", ["qqzone-spectator", "run"])

        with (
            patch("qqzone_spectator.cli.AppConfig.from_env", return_value=config),
            patch("qqzone_spectator.cli.Database", return_value=mock_db),
            patch("qqzone_spectator.cli.SchedulerService.from_config", return_value=mock_service),
        ):
            main()

        mock_service.run_loop.assert_called_once_with(900, push_enabled=True)
        mock_db.close.assert_called_once_with()

    def test_run_accepts_global_option_after_subcommand(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        config = _make_config(tmp_path, poll_interval_seconds=900)
        mock_db = MagicMock()
        mock_service = MagicMock()

        monkeypatch.setattr(
            sys,
            "argv",
            ["qqzone-spectator", "run", "--interval", "15", "--log-level", "DEBUG"],
        )

        with (
            patch("qqzone_spectator.cli.AppConfig.from_env", return_value=config),
            patch("qqzone_spectator.cli.Database", return_value=mock_db),
            patch("qqzone_spectator.cli.SchedulerService.from_config", return_value=mock_service),
        ):
            main()

        mock_service.run_loop.assert_called_once_with(15, push_enabled=True)
        mock_db.close.assert_called_once_with()
