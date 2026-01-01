from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass(frozen=True)
class RcloneConfig:
    exe: str
    remote: str
    dest_folder: str
    drive_use_trash: str | None = None


def rclone_sync_folder(cfg: RcloneConfig, src_dir: Path) -> None:
    if not src_dir.exists():
        raise FileNotFoundError(f"Local mirror dir not found: {src_dir}")

    dest = f"{cfg.remote}:{cfg.dest_folder}".rstrip(":")
    cmd: List[str] = [
        cfg.exe,
        "sync",
        str(src_dir),
        dest,
        "--create-empty-src-dirs",
        "--delete-during",
        "--transfers",
        "4",
        "--checkers",
        "8",
    ]
    if cfg.drive_use_trash is not None:
        val = cfg.drive_use_trash.strip().lower()
        if val in ("true", "false"):
            cmd.extend(["--drive-use-trash", val])

    subprocess.run(cmd, check=True)

