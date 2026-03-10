from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import QzonePost


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row

    def init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS targets (
                qq TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 1,
                remark TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_qq TEXT NOT NULL,
                post_id TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                source_payload TEXT NOT NULL,
                inserted_at TEXT NOT NULL,
                UNIQUE(target_qq, post_id)
            );

            CREATE TABLE IF NOT EXISTS media (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_qq TEXT NOT NULL,
                post_id TEXT NOT NULL,
                media_url TEXT NOT NULL,
                media_type TEXT NOT NULL DEFAULT 'image',
                local_path TEXT,
                inserted_at TEXT NOT NULL,
                UNIQUE(target_qq, post_id, media_url)
            );

            CREATE TABLE IF NOT EXISTS crawl_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                fetched_posts INTEGER NOT NULL DEFAULT 0,
                inserted_posts INTEGER NOT NULL DEFAULT 0,
                error_message TEXT
            );

            CREATE TABLE IF NOT EXISTS push_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_qq TEXT NOT NULL,
                post_id TEXT NOT NULL,
                push_target_type TEXT NOT NULL,
                push_target_id TEXT NOT NULL,
                status TEXT NOT NULL,
                error_message TEXT,
                pushed_at TEXT NOT NULL,
                UNIQUE(target_qq, post_id, push_target_type, push_target_id)
            );
            """
        )
        self.conn.commit()

    def upsert_targets(self, target_qqs: list[str]) -> None:
        if not target_qqs:
            return
        now = utc_now()
        for qq in target_qqs:
            self.conn.execute(
                """
                INSERT INTO targets (qq, created_at)
                VALUES (?, ?)
                ON CONFLICT(qq) DO UPDATE SET enabled = 1
                """,
                (qq, now),
            )
        self.conn.commit()

    def list_targets(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT qq FROM targets WHERE enabled = 1 ORDER BY qq"
        ).fetchall()
        return [str(row["qq"]) for row in rows]

    def record_crawl_start(self) -> int:
        cursor = self.conn.execute(
            "INSERT INTO crawl_runs (started_at, status) VALUES (?, ?)",
            (utc_now(), "running"),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def record_crawl_finish(
        self,
        run_id: int,
        *,
        status: str,
        fetched_posts: int,
        inserted_posts: int,
        error_message: str | None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE crawl_runs
            SET finished_at = ?, status = ?, fetched_posts = ?, inserted_posts = ?, error_message = ?
            WHERE id = ?
            """,
            (utc_now(), status, fetched_posts, inserted_posts, error_message, run_id),
        )
        self.conn.commit()

    def save_post(self, post: QzonePost) -> bool:
        try:
            self.conn.execute(
                """
                INSERT INTO posts (target_qq, post_id, content, created_at, source_payload, inserted_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    post.target_qq,
                    post.post_id,
                    post.content,
                    post.created_at,
                    post.source_payload,
                    utc_now(),
                ),
            )
        except sqlite3.IntegrityError:
            return False

        for media in post.media:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO media (target_qq, post_id, media_url, media_type, local_path, inserted_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    post.target_qq,
                    post.post_id,
                    media.url,
                    media.media_type,
                    media.local_path,
                    utc_now(),
                ),
            )

        self.conn.commit()
        return True

    def update_media_local_path(
        self, target_qq: str, post_id: str, media_url: str, local_path: str
    ) -> None:
        self.conn.execute(
            """
            UPDATE media
            SET local_path = ?
            WHERE target_qq = ? AND post_id = ? AND media_url = ?
            """,
            (local_path, target_qq, post_id, media_url),
        )
        self.conn.commit()

    def has_success_push_record(
        self, target_qq: str, post_id: str, push_target_type: str, push_target_id: str
    ) -> bool:
        row = self.conn.execute(
            """
            SELECT 1
            FROM push_records
            WHERE target_qq = ? AND post_id = ?
              AND push_target_type = ? AND push_target_id = ?
              AND status = 'success'
            LIMIT 1
            """,
            (target_qq, post_id, push_target_type, push_target_id),
        ).fetchone()
        return row is not None

    def record_push_result(
        self,
        *,
        target_qq: str,
        post_id: str,
        push_target_type: str,
        push_target_id: str,
        status: str,
        error_message: str | None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO push_records
            (target_qq, post_id, push_target_type, push_target_id, status, error_message, pushed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(target_qq, post_id, push_target_type, push_target_id)
            DO UPDATE SET
                status = excluded.status,
                error_message = excluded.error_message,
                pushed_at = excluded.pushed_at
            """,
            (
                target_qq,
                post_id,
                push_target_type,
                push_target_id,
                status,
                error_message,
                utc_now(),
            ),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
