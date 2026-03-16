from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import requests

from .collector import MediaDownloader, QzoneAPIError, QzoneAuthError, QzoneClient, parse_posts
from .config import AppConfig
from .db import Database
from .models import QzonePost
from .push import OneBotClient, build_post_message

LOGGER = logging.getLogger(__name__)


def build_content_preview(content: str, max_length: int = 60) -> str:
    normalized = " ".join(content.split())
    if not normalized:
        return "(no text content)"
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[: max_length - 3]}..."


def parse_post_created_at_seconds(created_at: str) -> int | None:
    text = created_at.strip()
    if not text:
        return None

    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.astimezone(timezone.utc).timestamp())


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
        if (
            config.push_enabled
            and config.onebot_base_url
            and (config.push_private_users or config.push_groups)
        ):
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

    def crawl_once(
        self,
        *,
        push_enabled: bool = False,
        published_after: int | None = None,
    ) -> dict[str, int]:
        targets = self.db.list_targets()
        if not targets:
            raise RuntimeError("No target QQ found. Set TARGET_QQS and run init-db first.")

        LOGGER.info(
            "CRAWL_START targets=%s fetch_limit=%s push_enabled=%s",
            len(targets),
            self.config.fetch_limit,
            push_enabled,
        )

        run_id = self.db.record_crawl_start()
        fetched_posts = 0
        inserted_posts = 0
        skipped_owner_mismatch = 0
        skipped_before_start = 0
        cutoff = published_after

        try:
            for target_qq in targets:
                LOGGER.info("TARGET_START qq=%s", target_qq)
                raw_posts = self.qzone_client.fetch_posts(target_qq, num=self.config.fetch_limit)
                posts = parse_posts(target_qq, raw_posts)
                self._populate_author_names(target_qq, posts)
                fetched_posts += len(posts)

                LOGGER.info("TARGET_FETCHED qq=%s posts=%s", target_qq, len(posts))

                for index, post in enumerate(posts, start=1):
                    if cutoff is not None:
                        created_at = parse_post_created_at_seconds(post.created_at)
                        if created_at is None or created_at < cutoff:
                            skipped_before_start += 1
                            LOGGER.debug(
                                "POST_BEFORE_START_SKIP qq=%s post=%s created_at=%s created_at_seconds=%s cutoff_seconds=%s",
                                post.target_qq,
                                post.post_id,
                                post.created_at,
                                created_at,
                                cutoff,
                            )
                            continue

                    if post.author_qq and post.author_qq != post.target_qq:
                        skipped_owner_mismatch += 1
                        LOGGER.info(
                            "Crawling [%s] qq=%s author=%s post=%s idx=%s/%s status=owner-mismatch-skip",
                            build_content_preview(post.content),
                            post.target_qq,
                            post.author_qq,
                            post.post_id,
                            index,
                            len(posts),
                        )
                        LOGGER.warning(
                            "OWNER_MISMATCH_SKIP target=%s author=%s post=%s",
                            post.target_qq,
                            post.author_qq,
                            post.post_id,
                        )
                        continue

                    is_new = self.db.save_post(post)
                    status = "new" if is_new else "duplicate"
                    LOGGER.info(
                        "Crawling [%s] qq=%s post=%s idx=%s/%s status=%s",
                        build_content_preview(post.content),
                        post.target_qq,
                        post.post_id,
                        index,
                        len(posts),
                        status,
                    )

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

            LOGGER.info(
                "CRAWL_DONE run_id=%s fetched=%s inserted=%s skipped_before_start=%s skipped_owner_mismatch=%s",
                run_id,
                fetched_posts,
                inserted_posts,
                skipped_before_start,
                skipped_owner_mismatch,
            )
            return {
                "fetched": fetched_posts,
                "inserted": inserted_posts,
                "skipped_before_start": skipped_before_start,
                "skipped_owner_mismatch": skipped_owner_mismatch,
            }
        except Exception as exc:
            self.db.record_crawl_finish(
                run_id,
                status="failed",
                fetched_posts=fetched_posts,
                inserted_posts=inserted_posts,
                error_message=str(exc),
            )
            LOGGER.error(
                "CRAWL_FAILED run_id=%s fetched=%s inserted=%s skipped_before_start=%s skipped_owner_mismatch=%s error=%s",
                run_id,
                fetched_posts,
                inserted_posts,
                skipped_before_start,
                skipped_owner_mismatch,
                exc,
            )
            raise

    def run_loop(self, interval_seconds: int, *, push_enabled: bool = False) -> None:
        session_started_at = datetime.now(timezone.utc)
        session_started_at_seconds = int(session_started_at.timestamp())
        LOGGER.info(
            "RUN_LOOP_START interval=%s push_enabled=%s session_started_at=%s session_started_at_seconds=%s",
            interval_seconds,
            push_enabled,
            session_started_at.isoformat(),
            session_started_at_seconds,
        )

        while True:
            try:
                result = self.crawl_once(
                    push_enabled=push_enabled,
                    published_after=session_started_at_seconds,
                )
                LOGGER.info(
                    "crawl done: fetched=%s inserted=%s skipped_before_start=%s skipped_owner_mismatch=%s",
                    result["fetched"],
                    result["inserted"],
                    result.get("skipped_before_start", 0),
                    result.get("skipped_owner_mismatch", 0),
                )
            except QzoneAuthError as exc:
                LOGGER.error(
                    "crawl loop stopped: QZONE_COOKIE may be expired. Update QZONE_COOKIE and rerun. detail=%s",
                    exc.message,
                )
                return
            except Exception:
                LOGGER.exception("crawl cycle failed")

            time.sleep(interval_seconds)

    def _populate_author_names(self, target_qq: str, posts: list[QzonePost]) -> None:
        if not posts:
            return

        try:
            nickname = self.qzone_client.fetch_target_nickname(target_qq)
        except (QzoneAPIError, requests.RequestException, ValueError) as exc:
            LOGGER.warning("TARGET_NICKNAME_LOOKUP_FAILED qq=%s error=%s", target_qq, exc)
            return

        if not nickname:
            return

        for post in posts:
            if not post.author_qq or post.author_qq == target_qq:
                post.author_name = nickname

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
            LOGGER.info(
                "MEDIA_DOWNLOADED qq=%s post=%s index=%s path=%s",
                post.target_qq,
                post.post_id,
                index,
                local_path,
            )

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
                LOGGER.warning(
                    "PUSH_FAILED type=private target=%s qq=%s post=%s error=%s",
                    user_id,
                    post.target_qq,
                    post.post_id,
                    exc,
                )
                self.db.record_push_result(
                    target_qq=post.target_qq,
                    post_id=post.post_id,
                    push_target_type="private",
                    push_target_id=push_target_id,
                    status="failed",
                    error_message=str(exc),
                )
                continue

            LOGGER.info(
                "PUSH_SENT type=private target=%s qq=%s post=%s",
                user_id,
                post.target_qq,
                post.post_id,
            )
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
                LOGGER.warning(
                    "PUSH_FAILED type=group target=%s qq=%s post=%s error=%s",
                    group_id,
                    post.target_qq,
                    post.post_id,
                    exc,
                )
                self.db.record_push_result(
                    target_qq=post.target_qq,
                    post_id=post.post_id,
                    push_target_type="group",
                    push_target_id=push_target_id,
                    status="failed",
                    error_message=str(exc),
                )
                continue

            LOGGER.info(
                "PUSH_SENT type=group target=%s qq=%s post=%s",
                group_id,
                post.target_qq,
                post.post_id,
            )
            self.db.record_push_result(
                target_qq=post.target_qq,
                post_id=post.post_id,
                push_target_type="group",
                push_target_id=push_target_id,
                status="success",
                error_message=None,
            )
