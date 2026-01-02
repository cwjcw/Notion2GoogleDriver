# Notion2GoogleDriver
把Notion里的内容自动抓取到GoogleDriver，确保是最新的mirror

## 使用方法（Windows）

1. 安装依赖：`pip install -r requirements.txt`
2. 配置 `.env`（参考 `.env.example`）
3. 增量构建镜像（不推送到 Google Drive）：`python sync_notion_to_gdrive.py --no-rclone`
4. 增量构建并推送到 Google Drive（会做 mirror 同步）：`python sync_notion_to_gdrive.py`
5. 全量重建并推送到 Google Drive：`python sync_notion_to_gdrive.py --full-rebuild`

## rclone 用法

### Windows

1. 安装 rclone（或直接下载解压），确保能运行 `rclone.exe`
2. 运行 `rclone config` 完成 Google Drive 授权
3. 在 `.env` 中设置：
   - `RCLONE_EXE=Your_path\rclone.exe`
   - `RCLONE_REMOTE=gdrive`（你的 remote 名）
   - `RCLONE_DEST_FOLDER=notion`（要上传的谷歌硬盘中的文件夹名）
4. 运行同步：`python sync_notion_to_gdrive.py`

### Ubuntu

1. 安装 rclone：`sudo apt-get install -y rclone`（或按官网安装）
2. 运行 `rclone config` 完成 Google Drive 授权
3. 在 `.env` 中设置：
   - `RCLONE_EXE=rclone`
   - `RCLONE_REMOTE=gdrive`
   - `RCLONE_DEST_FOLDER=notion`
4. 运行同步：`python sync_notion_to_gdrive.py`

## 全量/增量运行命令

- 增量构建（不推送）：`python sync_notion_to_gdrive.py --no-rclone`
- 增量构建并同步到 Google Drive：`python sync_notion_to_gdrive.py`
- 全量重建并同步到 Google Drive：`python sync_notion_to_gdrive.py --full-rebuild`


同步日志在：`logs\\sync_YYYYMMDD.log`
