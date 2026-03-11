# QQzone-spectator

Language: [简体中文](README.md) | English

`QQzone-spectator` is a Python project that automatically collects QQZone posts from specified QQ users, stores text and images in a local SQLite database, and can optionally push new posts to QQ users or groups through OneBot.

## Features

- Pull QQZone posts for configured target QQ accounts.
- Enforce strict owner verification and skip posts whose author QQ does not match the target QQ.
- Persist post text, publish time, and raw payload in SQLite.
- Download post images to local storage and keep file mappings.
- Export one target QQ timeline to an A4 PDF with embedded local images.
- Optionally push new posts through OneBot (recommended stack: NoneBot2 + OneBot v11).
- Support both one-shot mode and scheduled loop mode.

## Project Layout

```text
QQzone-spectator/
  AGENTS.md
  pyproject.toml
  .env.example
  src/qqzone_spectator/
    config.py
    db.py
    models.py
    collector/
      client.py
      parser.py
      downloader.py
    push/
      onebot.py
    exporter/
      service.py
    scheduler.py
    cli.py
  data/
```

## Requirements

- Python 3.10+
- Valid QQ login cookie (for QQZone access)
- Optional: a OneBot backend (such as go-cqhttp or NapCat)

## Quick Start

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -e .
```

3. Copy the environment template:

```bash
# Linux / macOS
cp .env.example .env

# Windows
copy .env.example .env
```

4. Edit `.env` and fill at least: `QZONE_UIN`, `QZONE_COOKIE`, `TARGET_QQS`.
5. Initialize database schema:

```bash
qqzone-spectator init-db
```

6. List enabled targets:

```bash
qqzone-spectator list-targets
```

7. Run one crawl cycle:

```bash
qqzone-spectator crawl-once
```

8. Run continuously (interval from `.env` by default):

```bash
qqzone-spectator run
```

9. Export one target timeline as PDF (A4 template):

```bash
qqzone-spectator export-pdf --target-qq 1224944928
```

## Configuration

Main variables in `.env.example`:

- `QZONE_UIN`: your QQ number used in request parameters.
- `QZONE_COOKIE`: full login cookie, must include `p_skey` or `skey`.
- `TARGET_QQS`: target QQ accounts to crawl, comma-separated.
- `DB_PATH`: SQLite path, default `data/qqzone.db`.
- `MEDIA_DIR`: image download directory, default `data/media`.
- `FETCH_LIMIT`: number of posts per request.
- `POLL_INTERVAL_SECONDS`: loop mode interval in seconds.
- `REQUEST_TIMEOUT`: network timeout in seconds.
- `ONEBOT_BASE_URL`: OneBot HTTP API base URL.
- `ONEBOT_ACCESS_TOKEN`: OneBot access token (if enabled).
- `PUSH_PRIVATE_USERS`: private push targets, comma-separated.
- `PUSH_GROUPS`: group push targets, comma-separated.

## Commands

- `qqzone-spectator init-db`: initialize schema and sync targets.
- `qqzone-spectator list-targets`: list enabled target QQ accounts.
- `qqzone-spectator crawl-once [--no-push]`: run one crawl cycle.
- `qqzone-spectator run [--interval SECONDS] [--no-push]`: run in loop mode.
- `qqzone-spectator export-pdf --target-qq <qq> [--output path] [--limit N] [--no-images]`: export one target PDF.
- Global option: `--log-level {DEBUG,INFO,WARNING,ERROR,CRITICAL}` (default: `INFO`).

## PDF Export Notes

- Template: A4 portrait timeline cards, latest posts first.
- Image source: embeds local files from `media.local_path`.
- One-time setup: install Chromium for Playwright before first export:

```bash
playwright install chromium
```

## OneBot Integration

1. Prepare a QQ bot backend (for example NapCat or go-cqhttp).
2. Ensure the OneBot HTTP API endpoint is reachable.
3. Configure `ONEBOT_BASE_URL` and `ONEBOT_ACCESS_TOKEN` (if needed) in `.env`.
4. Configure push destinations in `PUSH_PRIVATE_USERS` / `PUSH_GROUPS`.

Used OneBot actions:

- `send_private_msg`
- `send_group_msg`

## Database Notes

Default storage is SQLite. Main tables:

- `targets`: target QQ accounts.
- `posts`: post records (content, time, raw payload).
- `media`: image URL and local file path mapping.
- `crawl_runs`: crawl execution logs.
- `push_records`: push success/failure records.

## Disclaimer

- QQZone collection depends on cookies and unofficial interfaces, with potential risk of expiration or anti-abuse restrictions.
- Only collect content that your account is authorized to access.
- Use a reasonable polling interval to avoid overly frequent requests.
- This project is for learning and research purposes. Please comply with platform rules and applicable laws.
