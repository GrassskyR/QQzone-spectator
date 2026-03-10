# QQzone-spectator

QQzone-spectator is a Python project for automatically collecting QQZone posts from specific QQ users, storing text and images in a local SQLite database, and optionally pushing new posts to QQ users or groups through a OneBot-compatible bot.

## Features

- Poll QQZone posts for configured target QQ accounts.
- Save post text, metadata, and source payload into SQLite.
- Download post images to local disk and keep path mapping in the database.
- Push newly discovered posts to private chats or groups through OneBot API.
- Run once or in a timed loop.

## Project layout

```
QQzone-spectator/
  AGENTS.md
  pyproject.toml
  .env.example
  src/qqzone_spectator/
    collector/
    push/
    cli.py
    scheduler.py
    db.py
```

## Quick start

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -e .
```

3. Copy env template and fill values:

```bash
copy .env.example .env
```

4. Initialize database schema:

```bash
qqzone-spectator init-db
```

5. Crawl once:

```bash
qqzone-spectator crawl-once
```

6. Run continuously (default interval from env):

```bash
qqzone-spectator run
```

## Commands

- `qqzone-spectator init-db`
- `qqzone-spectator list-targets`
- `qqzone-spectator crawl-once [--no-push]`
- `qqzone-spectator run [--interval SECONDS] [--no-push]`

## OneBot / NoneBot integration notes

- Configure your QQ bot stack (for example NoneBot2 + OneBot adapter with go-cqhttp or NapCat).
- Set `ONEBOT_BASE_URL` to the action API endpoint.
- Set `PUSH_PRIVATE_USERS` and/or `PUSH_GROUPS`.
- The project sends actions `send_private_msg` and `send_group_msg`.

## Legal and risk notes

- QQZone collection relies on login cookies and unofficial interfaces.
- Only collect content that your account is authorized to access.
- Add reasonable polling intervals to reduce account risk.
