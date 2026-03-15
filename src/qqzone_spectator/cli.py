from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

from .config import AppConfig
from .db import Database
from .exporter import PdfExportService
from .scheduler import SchedulerService


def build_global_options_parser(*, include_defaults: bool) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--env-file",
        default=".env" if include_defaults else argparse.SUPPRESS,
        help="Path to .env file (default: .env)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO" if include_defaults else argparse.SUPPRESS,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: INFO)",
    )
    return parser


def build_parser() -> argparse.ArgumentParser:
    global_options = build_global_options_parser(include_defaults=True)
    shared_global_options = build_global_options_parser(include_defaults=False)
    parser = argparse.ArgumentParser(
        description="QQZone spectator",
        parents=[global_options],
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "init-db",
        parents=[shared_global_options],
        help="Create database schema and sync targets",
    )
    subparsers.add_parser(
        "list-targets",
        parents=[shared_global_options],
        help="List enabled target QQ accounts",
    )

    crawl_once = subparsers.add_parser(
        "crawl-once",
        parents=[shared_global_options],
        help="Run one crawl cycle",
    )
    crawl_once.add_argument("--no-push", action="store_true", help="Disable push actions")

    run = subparsers.add_parser(
        "run",
        parents=[shared_global_options],
        help="Run in loop mode",
    )
    run.add_argument(
        "--interval",
        type=int,
        default=0,
        help="Polling interval in seconds (default from env)",
    )
    run.add_argument("--no-push", action="store_true", help="Disable push actions")

    export_pdf = subparsers.add_parser(
        "export-pdf",
        parents=[shared_global_options],
        help="Export one target QQ timeline to an A4 PDF",
    )
    export_pdf.add_argument(
        "--target-qq",
        required=True,
        help="Target QQ number to export",
    )
    export_pdf.add_argument(
        "--output",
        default="",
        help="Output PDF path (default: exports/<target_qq>_<time>.pdf)",
    )
    export_pdf.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum number of posts to export (default: all)",
    )
    export_pdf.add_argument(
        "--no-images",
        action="store_true",
        help="Export text only without embedded images",
    )

    return parser


def require_crawl_config(config: AppConfig) -> None:
    missing: list[str] = []
    if not config.qzone_uin:
        missing.append("QZONE_UIN")
    if not config.qzone_cookie:
        missing.append("QZONE_COOKIE")

    if missing:
        keys = ", ".join(missing)
        raise RuntimeError(f"Missing required env keys for crawling: {keys}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="[%(levelname)s][%(asctime)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    config = AppConfig.from_env(Path(args.env_file))
    config.ensure_directories()

    db = Database(config.db_path)
    db.init_schema()
    db.upsert_targets(config.target_qqs)

    try:
        if args.command == "init-db":
            print(f"database initialized: {config.db_path}")
            targets = db.list_targets()
            print(f"enabled targets: {len(targets)}")
            return

        if args.command == "list-targets":
            targets = db.list_targets()
            if not targets:
                print("no enabled targets")
                return
            for target in targets:
                print(target)
            return

        if args.command == "export-pdf":
            output_path = Path(args.output) if args.output else Path("exports") / (
                f"{args.target_qq}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            )
            exporter = PdfExportService(db=db, project_root=config.project_root)
            result = exporter.export_target_timeline_pdf(
                target_qq=str(args.target_qq).strip(),
                output_path=output_path,
                include_images=not args.no_images,
                limit=max(0, int(args.limit)),
            )
            print(
                "exported target={target} posts={posts} embedded_images={images} file={path}".format(
                    target=result.target_qq,
                    posts=result.post_count,
                    images=result.embedded_image_count,
                    path=result.output_path,
                )
            )
            return

        require_crawl_config(config)
        service = SchedulerService.from_config(config, db)

        if args.command == "crawl-once":
            result = service.crawl_once(push_enabled=not args.no_push)
            print(
                "fetched={fetched} inserted={inserted} skipped_owner_mismatch={skipped}".format(
                    fetched=result["fetched"],
                    inserted=result["inserted"],
                    skipped=result.get("skipped_owner_mismatch", 0),
                )
            )
            return

        if args.command == "run":
            interval = args.interval if args.interval > 0 else config.poll_interval_seconds
            service.run_loop(interval, push_enabled=not args.no_push)
            return

        parser.print_help()
    finally:
        db.close()


if __name__ == "__main__":
    main()
