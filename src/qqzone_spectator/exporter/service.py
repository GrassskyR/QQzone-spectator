from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from ..db import Database

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ExportMediaRecord:
    post_id: str
    media_url: str
    local_path: str


@dataclass(slots=True)
class ExportPostRecord:
    target_qq: str
    author_qq: str
    post_id: str
    content: str
    created_at: str
    inserted_at: str
    media: list[ExportMediaRecord] = field(default_factory=list)


@dataclass(slots=True)
class ExportResult:
    output_path: Path
    target_qq: str
    post_count: int
    embedded_image_count: int


class PdfExportService:
    def __init__(self, *, db: Database, project_root: Path) -> None:
        self.db = db
        self.project_root = Path(project_root)

    def export_target_timeline_pdf(
        self,
        *,
        target_qq: str,
        output_path: Path,
        include_images: bool = True,
        limit: int = 0,
    ) -> ExportResult:
        posts = self._load_posts(target_qq=target_qq, limit=limit)
        if not posts:
            raise RuntimeError(f"No posts found for target QQ: {target_qq}")

        media_map = self._load_media_map(target_qq=target_qq)
        for post in posts:
            post.media = media_map.get(post.post_id, [])

        html_content, embedded_count = self._render_html(
            target_qq=target_qq,
            posts=posts,
            include_images=include_images,
        )

        output = Path(output_path)
        if not output.is_absolute():
            output = self.project_root / output
        output.parent.mkdir(parents=True, exist_ok=True)

        self._render_pdf(html_content=html_content, output_path=output)

        return ExportResult(
            output_path=output,
            target_qq=target_qq,
            post_count=len(posts),
            embedded_image_count=embedded_count,
        )

    def _load_posts(self, *, target_qq: str, limit: int) -> list[ExportPostRecord]:
        params: list[object] = [target_qq]
        sql = (
            """
            SELECT target_qq, author_qq, post_id, content, created_at, inserted_at
            FROM posts
            WHERE target_qq = ?
            ORDER BY created_at DESC, id DESC
            """
        )
        if limit > 0:
            sql += " LIMIT ?"
            params.append(limit)

        rows = self.db.conn.execute(sql, tuple(params)).fetchall()
        return [
            ExportPostRecord(
                target_qq=str(row["target_qq"]),
                author_qq=str(row["author_qq"]),
                post_id=str(row["post_id"]),
                content=str(row["content"]),
                created_at=str(row["created_at"]),
                inserted_at=str(row["inserted_at"]),
            )
            for row in rows
        ]

    def _load_media_map(self, *, target_qq: str) -> dict[str, list[ExportMediaRecord]]:
        rows = self.db.conn.execute(
            """
            SELECT post_id, media_url, local_path
            FROM media
            WHERE target_qq = ?
            ORDER BY id ASC
            """,
            (target_qq,),
        ).fetchall()

        result: dict[str, list[ExportMediaRecord]] = {}
        for row in rows:
            post_id = str(row["post_id"])
            result.setdefault(post_id, []).append(
                ExportMediaRecord(
                    post_id=post_id,
                    media_url=str(row["media_url"] or ""),
                    local_path=str(row["local_path"] or ""),
                )
            )
        return result

    def _render_html(
        self,
        *,
        target_qq: str,
        posts: list[ExportPostRecord],
        include_images: bool,
    ) -> tuple[str, int]:
        cards: list[str] = []
        embedded_image_count = 0

        for index, post in enumerate(posts, start=1):
            text = post.content.strip()
            text_html = escape(text).replace("\n", "<br/>") if text else "<span class=\"empty\">(no text content)</span>"

            image_html = ""
            if include_images and post.media:
                image_items: list[str] = []
                for media in post.media:
                    image_src = self._build_image_src(media.local_path)
                    if not image_src:
                        continue
                    embedded_image_count += 1
                    image_items.append(
                        """
                        <figure class="image-item">
                          <img src="{src}" alt="{alt}">
                        </figure>
                        """.format(
                            src=image_src,
                            alt=escape(f"{post.post_id} image"),
                        )
                    )

                if image_items:
                    image_html = f"<div class=\"image-grid\">{''.join(image_items)}</div>"

            cards.append(
                """
                <section class="post-card">
                  <div class="post-head">
                    <div class="post-index">#{index}</div>
                    <div class="post-meta">
                      <div><strong>Created:</strong> {created_at}</div>
                      <div><strong>Post ID:</strong> {post_id}</div>
                      <div><strong>Author QQ:</strong> {author_qq}</div>
                    </div>
                  </div>
                  <div class="post-content">{text_html}</div>
                  {image_html}
                </section>
                """.format(
                    index=index,
                    created_at=escape(post.created_at),
                    post_id=escape(post.post_id),
                    author_qq=escape(post.author_qq),
                    text_html=text_html,
                    image_html=image_html,
                )
            )

        generated_at = datetime.now(timezone.utc).isoformat()
        html_content = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>QQZone Timeline Export</title>
  <style>
    :root {
      --bg: #f5f7fb;
      --card: #ffffff;
      --line: #d6deeb;
      --muted: #5f6b85;
      --text: #1f2b46;
      --accent: #2b6df8;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      color: var(--text);
      background: var(--bg);
      font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif;
      line-height: 1.55;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }

    .container {
      max-width: 820px;
      margin: 0 auto;
      padding: 10mm 0;
    }

    .cover {
      background: linear-gradient(160deg, #1f3d8f, #2b6df8);
      color: #fff;
      border-radius: 10px;
      padding: 10mm;
      margin-bottom: 8mm;
      page-break-inside: avoid;
    }

    .cover h1 {
      margin: 0 0 2mm 0;
      font-size: 24px;
      letter-spacing: 0.2px;
    }

    .cover p {
      margin: 0;
      opacity: 0.92;
      font-size: 13px;
    }

    .stats {
      margin-top: 6mm;
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 3mm;
    }

    .stats div {
      background: rgba(255, 255, 255, 0.16);
      border: 1px solid rgba(255, 255, 255, 0.35);
      border-radius: 8px;
      padding: 3mm;
      font-size: 12px;
    }

    .timeline {
      border-left: 2px solid var(--line);
      padding-left: 6mm;
    }

    .post-card {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 5mm;
      margin-bottom: 5mm;
      page-break-inside: avoid;
      box-shadow: 0 1px 3px rgba(18, 25, 42, 0.06);
    }

    .post-head {
      display: flex;
      gap: 4mm;
      align-items: flex-start;
      margin-bottom: 3mm;
    }

    .post-index {
      min-width: 11mm;
      height: 11mm;
      border-radius: 999px;
      background: var(--accent);
      color: #fff;
      font-size: 11px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 600;
    }

    .post-meta {
      color: var(--muted);
      font-size: 12px;
      display: grid;
      gap: 1mm;
    }

    .post-content {
      font-size: 14px;
      margin-top: 1mm;
      white-space: normal;
      word-break: break-word;
    }

    .empty {
      color: #8390aa;
      font-style: italic;
    }

    .image-grid {
      margin-top: 4mm;
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 3mm;
    }

    .image-item {
      margin: 0;
      border: 1px solid var(--line);
      border-radius: 6px;
      overflow: hidden;
      background: #f9fbff;
      page-break-inside: avoid;
    }

    .image-item img {
      display: block;
      width: 100%;
      height: auto;
      max-height: 95mm;
      object-fit: contain;
      background: #fff;
    }

    @media print {
      .container { padding-top: 0; }
    }
  </style>
</head>
<body>
  <main class="container">
    <section class="cover">
      <h1>QQZone Timeline Export</h1>
      <p>Target QQ: __TARGET_QQ__</p>
      <p>Generated at: __GENERATED_AT__</p>
      <div class="stats">
        <div><strong>Posts</strong><br>__POST_COUNT__</div>
        <div><strong>Embedded Images</strong><br>__EMBEDDED_COUNT__</div>
        <div><strong>Page Size</strong><br>A4</div>
      </div>
    </section>
    <section class="timeline">
      __CARDS_HTML__
    </section>
  </main>
</body>
</html>
        """
        html_content = (
            html_content.replace("__TARGET_QQ__", escape(target_qq))
            .replace("__GENERATED_AT__", escape(generated_at))
            .replace("__POST_COUNT__", str(len(posts)))
            .replace("__EMBEDDED_COUNT__", str(embedded_image_count))
            .replace("__CARDS_HTML__", "".join(cards))
        )
        return html_content, embedded_image_count

    def _build_image_src(self, local_path: str) -> str | None:
        if not local_path:
            return None

        image_path = self._resolve_media_path(local_path)
        if image_path is None:
            LOGGER.warning("EXPORT_IMAGE_MISSING path=%s", local_path)
            return None

        try:
            return image_path.resolve().as_uri()
        except ValueError:
            LOGGER.warning("EXPORT_IMAGE_URI_FAIL path=%s", image_path)
            return None

    def _resolve_media_path(self, raw_path: str) -> Path | None:
        path = Path(raw_path)
        candidates: list[Path]
        if path.is_absolute():
            candidates = [path]
        else:
            candidates = [
                self.project_root / path,
                Path.cwd() / path,
                path,
            ]

        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return candidate
        return None

    def _render_pdf(self, *, html_content: str, output_path: Path) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "playwright is required for export-pdf. "
                "Install with 'pip install playwright' and then run 'playwright install chromium'."
            ) from exc

        with tempfile.TemporaryDirectory(prefix="qqzone_export_") as tmpdir:
            html_path = Path(tmpdir) / "timeline.html"
            html_path.write_text(html_content, encoding="utf-8")

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True,
                    args=["--disable-dev-shm-usage"],
                )
                try:
                    page = browser.new_page()
                    page.set_default_timeout(300000)
                    page.goto(html_path.resolve().as_uri(), wait_until="networkidle")
                    page.emulate_media(media="print")
                    page.pdf(
                        path=str(output_path),
                        format="A4",
                        print_background=True,
                        margin={
                            "top": "12mm",
                            "right": "10mm",
                            "bottom": "14mm",
                            "left": "10mm",
                        },
                        display_header_footer=True,
                        header_template="<div></div>",
                        footer_template=(
                            "<div style='width:100%;font-size:9px;color:#64748b;"
                            "padding:0 12mm;display:flex;justify-content:flex-end;'>"
                            "<span class='pageNumber'></span>/<span class='totalPages'></span>"
                            "</div>"
                        ),
                    )
                finally:
                    browser.close()
