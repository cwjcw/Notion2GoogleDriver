# Notion2GoogleDriver
把Notion里的内容自动抓取到GoogleDriver，确保是最新的mirror

## 使用方法（Windows）

1. 安装依赖：`pip install -r requirements.txt`
2. 配置 `.env`（参考 `.env.example`）
3. 先本地生成镜像（不推送到 Google Drive）：`python sync_notion_to_gdrive.py --no-rclone`
4. 推送到 Google Drive（会做 mirror 同步）：`python sync_notion_to_gdrive.py`

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
4. 运行同步：`python3 sync_notion_to_gdrive.py`


同步日志在：`logs\\sync_YYYYMMDD.log`
