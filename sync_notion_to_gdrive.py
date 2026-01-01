from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from notion2gdrive.config import load_config
from notion2gdrive.mirror import NotionMirror
from notion2gdrive.notion_client import AsyncNotionClient
from notion2gdrive.rclone_sync import RcloneConfig, rclone_sync_folder


async def main_async() -> int:
    repo_root = Path(__file__).resolve().parent
    print("Step 1/5: Load config")
    cfg = load_config(repo_root)

    parser = argparse.ArgumentParser(description="Mirror Notion (API) to local folder and rclone sync to Google Drive.")
    parser.add_argument("--no-rclone", action="store_true", help="Only build local mirror, do not run rclone sync.")
    parser.add_argument("--full-rebuild", action="store_true", help="Rebuild the local mirror from scratch.")
    args = parser.parse_args()

    print("Step 2/5: Init Notion client (async)")
    client = AsyncNotionClient(token=cfg.notion_token, notion_version=cfg.notion_version)
    print("Step 3/5: Build local mirror")
    mirror = NotionMirror(client=client, output_dir=cfg.local_mirror_dir)
    try:
        result = await mirror.build_async(incremental=not args.full_rebuild)
    finally:
        await client.aclose()

    if not args.no_rclone:
        print("Step 4/5: rclone sync to Google Drive")
        rclone_sync_folder(
            RcloneConfig(
                exe=cfg.rclone_exe,
                remote=cfg.rclone_remote,
                dest_folder=cfg.rclone_dest_folder,
                drive_use_trash=cfg.rclone_drive_use_trash,
            ),
            src_dir=result.local_dir,
        )
    else:
        print("Step 4/5: rclone sync skipped (--no-rclone)")

    print("Step 5/5: Done")
    print(f"OK: pages={result.pages_written} dbs={result.databases_written} local={result.local_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
