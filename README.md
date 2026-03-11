# QQzone-spectator

语言切换：简体中文 | [English](README.en.md)

`QQzone-spectator` 是一个 Python 项目，用于自动化采集指定 QQ 用户的 QQ 空间动态，保存文字与图片到本地数据库，并可选通过 OneBot 推送到 QQ 私聊或群聊。

## 功能特性

- 自动拉取指定目标 QQ 的空间动态。
- 严格校验动态发布者 QQ，若与目标 QQ 不一致则跳过，避免误采集。
- 本地 SQLite 持久化保存动态文本、发布时间、原始载荷。
- 自动下载动态图片到本地目录并记录文件映射。
- 支持将单个目标账号的动态导出为 A4 PDF 时间线（可嵌入本地图片）。
- 可选对接 OneBot（推荐 NoneBot2 + OneBot v11 生态）推送新动态。
- 支持单次执行和循环轮询两种模式。

## 项目结构

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

## 运行环境

- Python 3.10+
- 可用的 QQ 登录 Cookie（用于访问 QQ 空间）
- 可选：OneBot 服务端（如 go-cqhttp / NapCat）

## 快速开始

1. 创建并激活虚拟环境。
2. 安装项目依赖：

```bash
pip install -e .
```

3. 复制环境变量模板：

```bash
# Linux / macOS
cp .env.example .env

# Windows
copy .env.example .env
```

4. 编辑 `.env`，至少填写：`QZONE_UIN`、`QZONE_COOKIE`、`TARGET_QQS`。
5. 初始化数据库：

```bash
qqzone-spectator init-db
```

6. 查看当前启用的目标账号：

```bash
qqzone-spectator list-targets
```

7. 执行一次采集：

```bash
qqzone-spectator crawl-once
```

8. 启动循环采集（间隔默认读取 `.env`）：

```bash
qqzone-spectator run
```

9. 导出单目标动态为 PDF（A4 时间线模板）：

```bash
qqzone-spectator export-pdf --target-qq 1224944928
```

## 配置项说明

`.env.example` 中主要变量如下：

- `QZONE_UIN`：你的 QQ 号（用于请求参数）。
- `QZONE_COOKIE`：登录后的完整 Cookie，至少包含 `p_skey` 或 `skey`。
- `TARGET_QQS`：要采集的目标 QQ，多个用逗号分隔。
- `DB_PATH`：SQLite 文件路径，默认 `data/qqzone.db`。
- `MEDIA_DIR`：图片下载目录，默认 `data/media`。
- `FETCH_LIMIT`：每次请求的动态条数。
- `POLL_INTERVAL_SECONDS`：循环模式轮询间隔（秒）。
- `REQUEST_TIMEOUT`：网络请求超时时间（秒）。
- `ONEBOT_BASE_URL`：OneBot HTTP API 地址。
- `ONEBOT_ACCESS_TOKEN`：OneBot 鉴权 Token（若启用）。
- `PUSH_PRIVATE_USERS`：私聊推送目标 QQ，逗号分隔。
- `PUSH_GROUPS`：群推送目标群号，逗号分隔。

## 命令说明

- `qqzone-spectator init-db`：初始化数据库并同步目标账号。
- `qqzone-spectator list-targets`：列出已启用采集目标。
- `qqzone-spectator crawl-once [--no-push]`：执行一次采集。
- `qqzone-spectator run [--interval SECONDS] [--no-push]`：循环采集。
- `qqzone-spectator export-pdf --target-qq QQ号 [--output 路径] [--limit N] [--no-images]`：导出单目标 PDF。
- 全局参数：`--log-level {DEBUG,INFO,WARNING,ERROR,CRITICAL}`，默认 `INFO`。

## PDF 导出说明

- 导出模板：A4 纵向时间线卡片，默认按时间倒序。
- 图片来源：使用 `media.local_path` 本地图片并嵌入 PDF。
- 依赖要求：首次使用需安装 Chromium：

```bash
playwright install chromium
```

## OneBot 集成说明

1. 准备 QQ 机器人协议端（如 NapCat 或 go-cqhttp）。
2. 确保 OneBot HTTP API 可访问。
3. 在 `.env` 配置 `ONEBOT_BASE_URL`、`ONEBOT_ACCESS_TOKEN`（如有）。
4. 配置推送目标 `PUSH_PRIVATE_USERS` / `PUSH_GROUPS`。

项目会调用以下 OneBot 动作：

- `send_private_msg`
- `send_group_msg`

## 数据库存储说明

默认使用 SQLite，主要表：

- `targets`：采集目标账号。
- `posts`：动态主记录（含内容、时间、原始载荷）。
- `media`：动态图片链接与本地文件路径映射。
- `crawl_runs`：采集任务执行日志。
- `push_records`：消息推送成功/失败记录。

## 注意事项

- QQ 空间采集依赖 Cookie 和非官方接口，存在失效与风控风险。
- 仅采集你有权限查看的内容，勿用于未授权场景。
- 建议设置合理轮询间隔，避免请求过于频繁。
- 本项目仅供学习和技术研究用途，请遵守相关平台规则与法律法规。
