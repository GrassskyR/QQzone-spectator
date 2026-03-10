from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .config import AppConfig
from .db import Database
from .scheduler import SchedulerService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="QQZone spectator")
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Path to .env file (default: .env)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="Create database schema and sync targets")
    subparsers.add_parser("list-targets", help="List enabled target QQ accounts")

    crawl_once = subparsers.add_parser("crawl-once", help="Run one crawl cycle")
    crawl_once.add_argument("--no-push", action="store_true", help="Disable push actions")

    run = subparsers.add_parser("run", help="Run in loop mode")
    run.add_argument(
        "--interval",
        type=int,
        default=0,
        help="Polling interval in seconds (default from env)",
    )
    run.add_argument("--no-push", action="store_true", help="Disable push actions")

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
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    parser = build_parser()
    args = parser.parse_args()

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

        require_crawl_config(config)
        service = SchedulerService.from_config(config, db)

        if args.command == "crawl-once":
            result = service.crawl_once(push_enabled=not args.no_push)
            print(f"fetched={result['fetched']} inserted={result['inserted']}")
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
