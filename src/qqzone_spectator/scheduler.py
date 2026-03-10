from __future__ import annotations

import logging
import time

from .collector import MediaDownloader, QzoneClient, parse_posts
from .config import AppConfig
from .db import Database
from .models import QzonePost
from .push import OneBotClient, build_post_message

LOGGER = logging.getLogger(__name__)


class SchedulerService:
    def __init__(
        self,
        *,
        config: AppConfig,
        db: Database,
        qzone_client: QzoneClient,
        downloader: MediaDownloader,
        onebot_client: OneBotClient | None,
    ) -> None:
        self.config = config
        self.db = db
        self.qzone_client = qzone_client
        self.downloader = downloader
        self.onebot_client = onebot_client

    @classmethod
    def from_config(cls, config: AppConfig, db: Database) -> "SchedulerService":
        qzone_client = QzoneClient(
            config.qzone_uin,
            config.qzone_cookie,
            timeout=config.request_timeout,
        )
        downloader = MediaDownloader(config.media_dir)

        onebot_client: OneBotClient | None = None
        if config.onebot_base_url and (config.push_private_users or config.push_groups):
            onebot_client = OneBotClient(
                config.onebot_base_url,
                access_token=config.onebot_access_token,
                timeout=config.request_timeout,
            )

        return cls(
            config=config,
            db=db,
            qzone_client=qzone_client,
            downloader=downloader,
            onebot_client=onebot_client,
        )

    def crawl_once(self, *, push_enabled: bool = True) -> dict[str, int]:
        targets = self.db.list_targets()
        if not targets:
            raise RuntimeError("No target QQ found. Set TARGET_QQS and run init-db first.")

        run_id = self.db.record_crawl_start()
        fetched_posts = 0
        inserted_posts = 0

        try:
            for target_qq in targets:
                raw_posts = self.qzone_client.fetch_posts(target_qq, num=self.config.fetch_limit)
                posts = parse_posts(target_qq, raw_posts)
                fetched_posts += len(posts)

                for post in posts:
                    is_new = self.db.save_post(post)
                    if not is_new:
                        continue

                    inserted_posts += 1
                    media_paths = self._download_post_media(post)

                    if push_enabled and self.onebot_client is not None:
                        self._push_post(post, media_paths)

            self.db.record_crawl_finish(
                run_id,
                status="success",
                fetched_posts=fetched_posts,
                inserted_posts=inserted_posts,
                error_message=None,
            )
            return {"fetched": fetched_posts, "inserted": inserted_posts}
        except Exception as exc:
            self.db.record_crawl_finish(
                run_id,
                status="failed",
                fetched_posts=fetched_posts,
                inserted_posts=inserted_posts,
                error_message=str(exc),
            )
            raise

    def run_loop(self, interval_seconds: int, *, push_enabled: bool = True) -> None:
        while True:
            try:
                result = self.crawl_once(push_enabled=push_enabled)
                LOGGER.info(
                    "crawl done: fetched=%s inserted=%s",
                    result["fetched"],
                    result["inserted"],
                )
            except Exception:
                LOGGER.exception("crawl cycle failed")

            time.sleep(interval_seconds)

    def _download_post_media(self, post: QzonePost) -> list[str]:
        downloaded: list[str] = []
        for index, media in enumerate(post.media, start=1):
            try:
                local_path = self.downloader.download_image(
                    media_url=media.url,
                    target_qq=post.target_qq,
                    post_id=post.post_id,
                    index=index,
                    timeout=self.config.request_timeout,
                )
            except Exception as exc:
                LOGGER.warning("download failed url=%s error=%s", media.url, exc)
                continue

            if not local_path:
                continue

            downloaded.append(local_path)
            self.db.update_media_local_path(post.target_qq, post.post_id, media.url, local_path)

        return downloaded

    def _push_post(self, post: QzonePost, media_paths: list[str]) -> None:
        if self.onebot_client is None:
            return

        message = build_post_message(post, media_paths)

        for user_id in self.config.push_private_users:
            push_target_id = str(user_id)
            if self.db.has_success_push_record(post.target_qq, post.post_id, "private", push_target_id):
                continue
            try:
                self.onebot_client.send_private_msg(user_id, message)
            except Exception as exc:
                self.db.record_push_result(
                    target_qq=post.target_qq,
                    post_id=post.post_id,
                    push_target_type="private",
                    push_target_id=push_target_id,
                    status="failed",
                    error_message=str(exc),
                )
                continue

            self.db.record_push_result(
                target_qq=post.target_qq,
                post_id=post.post_id,
                push_target_type="private",
                push_target_id=push_target_id,
                status="success",
                error_message=None,
            )

        for group_id in self.config.push_groups:
            push_target_id = str(group_id)
            if self.db.has_success_push_record(post.target_qq, post.post_id, "group", push_target_id):
                continue
            try:
                self.onebot_client.send_group_msg(group_id, message)
            except Exception as exc:
                self.db.record_push_result(
                    target_qq=post.target_qq,
                    post_id=post.post_id,
                    push_target_type="group",
                    push_target_id=push_target_id,
                    status="failed",
                    error_message=str(exc),
                )
                continue

            self.db.record_push_result(
                target_qq=post.target_qq,
                post_id=post.post_id,
                push_target_type="group",
                push_target_id=push_target_id,
                status="success",
                error_message=None,
            )
