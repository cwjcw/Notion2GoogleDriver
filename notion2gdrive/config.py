from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    notion_token: str
    notion_version: str
    local_mirror_dir: Path
    rclone_exe: str
    rclone_remote: str
    rclone_dest_folder: str
    rclone_drive_use_trash: str | None


def load_config(repo_root: Path) -> Config:
    load_dotenv(repo_root / ".env")

    notion_token = os.getenv("NOTION_TOKEN")
    if not notion_token:
        raise RuntimeError("Missing NOTION_TOKEN in .env or environment.")

    notion_version = os.getenv("NOTION_VERSION", "2022-06-28").strip()
    local_mirror_dir = Path(os.getenv("LOCAL_MIRROR_DIR", "notion_mirror"))

    rclone_exe = os.getenv("RCLONE_EXE", "rclone").strip()
    rclone_remote = os.getenv("RCLONE_REMOTE", "gdrive").strip()
    rclone_dest_folder = os.getenv("RCLONE_DEST_FOLDER", "notion").strip().strip("/").strip("\\")
    rclone_drive_use_trash = os.getenv("RCLONE_DRIVE_USE_TRASH")

    return Config(
        notion_token=notion_token,
        notion_version=notion_version,
        local_mirror_dir=(repo_root / local_mirror_dir).resolve(),
        rclone_exe=rclone_exe,
        rclone_remote=rclone_remote,
        rclone_dest_folder=rclone_dest_folder,
        rclone_drive_use_trash=rclone_drive_use_trash,
    )

