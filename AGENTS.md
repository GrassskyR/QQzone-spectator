# AGENTS

This project separates responsibilities into small runtime "agents" implemented as Python modules.

## Collector Agent

- Module: `src/qqzone_spectator/collector/client.py`
- Responsibility: authenticate with QQZone via cookie and fetch raw post data.

## Parser Agent

- Module: `src/qqzone_spectator/collector/parser.py`
- Responsibility: normalize raw QQZone payload into internal post/media models.

## Storage Agent

- Module: `src/qqzone_spectator/db.py`
- Responsibility: initialize schema, deduplicate posts, persist text/media metadata, and track push records.

## Media Agent

- Module: `src/qqzone_spectator/collector/downloader.py`
- Responsibility: download image assets and bind local file paths to media records.

## Push Agent

- Module: `src/qqzone_spectator/push/onebot.py`
- Responsibility: send post notifications to QQ private users or groups via OneBot actions.

## Scheduler Agent

- Module: `src/qqzone_spectator/scheduler.py`
- Responsibility: orchestrate crawl, persistence, download, and push workflow; supports one-shot and loop mode.

## Export Agent

- Module: `src/qqzone_spectator/exporter/service.py`
- Responsibility: load stored posts/media for a target QQ and export an A4 timeline PDF with embedded images.

## Branch Workflow

- Active development happens on `dev`.
- `main` stays releasable and only receives changes that were already verified on `dev`.
- Before merging `dev` into `main`, run the current validation flow locally, including `pytest` and `pytest --cov=src/qqzone_spectator --cov-report=term-missing` when behavior or test coverage changes.

## Release Workflow

- Make code and test changes on `dev`.
- Verify the feature or fix locally, including any required runtime smoke tests.
- Commit the verified work on `dev`.
- Merge `dev` into `main` only after verification is complete.
- Push `main` to GitHub, then create release tags from `main`.
- Alpha or pre-release notes should mention branch-tested behavior changes, required env updates, and any migration or re-init steps.
