from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .notion_client import AsyncNotionClient
from .notion_markdown import block_to_md, rich_text_to_md


def _now_utc_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


_INVALID_WIN_CHARS = re.compile(r'[<>:"/\\\\|?*]')


def safe_name(name: str, *, fallback: str) -> str:
    name = (name or "").strip()
    name = _INVALID_WIN_CHARS.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip()
    name = name.rstrip(". ")
    if not name:
        return fallback
    return name[:160]


def _indent(depth: int) -> str:
    return "  " * max(depth, 0)


def page_title(page: Dict[str, Any]) -> str:
    if page.get("object") != "page":
        return "untitled_page"
    props = page.get("properties") or {}
    for _, v in props.items():
        if (v or {}).get("type") == "title":
            return rich_text_to_md((v or {}).get("title")) or "untitled_page"
    return "untitled_page"


def database_title(db: Dict[str, Any]) -> str:
    if db.get("object") != "database":
        return "untitled_db"
    return rich_text_to_md(db.get("title")) or "untitled_db"


def _id8(notion_id: str) -> str:
    return (notion_id or "").replace("-", "")[:8] or "unknown"


@dataclass
class MirrorResult:
    local_dir: Path
    pages_written: int
    databases_written: int


class NotionMirror:
    def __init__(self, client: AsyncNotionClient, output_dir: Path, page_concurrency: Optional[int] = None) -> None:
        self.client = client
        self.output_dir = output_dir

        self._page_cache: Dict[str, Dict[str, Any]] = {}
        self._db_cache: Dict[str, Dict[str, Any]] = {}
        self._page_path_cache: Dict[str, Path] = {}
        self._inaccessible_blocks: List[Tuple[str, str, str]] = []
        env_conc = os.getenv("NOTION_PAGE_CONCURRENCY")
        self._page_concurrency = max(int(env_conc or page_concurrency or 4), 1)

    def build(self, *, incremental: bool = True) -> MirrorResult:
        return asyncio.run(self.build_async(incremental=incremental))

    async def build_async(self, *, incremental: bool = True) -> MirrorResult:
        if incremental:
            return await self._build_incremental_async()
        return await self._build_full_async()

    async def _build_full_async(self) -> MirrorResult:
        print("[Mirror] Start")
        tmp_dir = self.output_dir.with_name(self.output_dir.name + ".tmp")
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)

        print("[Mirror] Search pages")
        pages = await self.client.search(object_type="page")
        print("[Mirror] Search databases")
        dbs = await self.client.search(object_type="database")

        self._populate_caches(pages, dbs)
        print("[Mirror] Fetch database metadata")
        await self._prefetch_databases()
        print("[Mirror] Fetch page metadata")
        await self._prefetch_pages()

        print("[Mirror] Write pages")
        pages_written, pages_index = await self._write_pages_async(
            root=tmp_dir, incremental=False, prev_pages=None
        )

        print("[Mirror] Write databases")
        databases_written, dbs_index = await self._write_databases_async(
            root=tmp_dir, incremental=False, prev_dbs=None
        )

        print("[Mirror] Write index")
        await self._write_root_index_async(tmp_dir, pages, dbs)
        await self._write_access_report_async(tmp_dir)
        await self._save_index_to_async(tmp_dir, pages_index, dbs_index)
        print("[Mirror] Replace output folder")
        self._atomic_replace(tmp_dir, self.output_dir)

        return MirrorResult(local_dir=self.output_dir, pages_written=pages_written, databases_written=databases_written)

    async def _build_incremental_async(self) -> MirrorResult:
        print("[Mirror] Start (incremental)")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        print("[Mirror] Search pages")
        pages = await self.client.search(object_type="page")
        print("[Mirror] Search databases")
        dbs = await self.client.search(object_type="database")

        self._populate_caches(pages, dbs)
        print("[Mirror] Fetch database metadata")
        await self._prefetch_databases()
        print("[Mirror] Fetch page metadata")
        await self._prefetch_pages()

        index = self._load_index()
        prev_pages = index.get("pages", {})
        prev_dbs = index.get("databases", {})

        print("[Mirror] Write pages (incremental)")
        pages_written, pages_index = await self._write_pages_async(
            root=self.output_dir, incremental=True, prev_pages=prev_pages
        )
        self._cleanup_removed(prev_pages, pages_index)

        print("[Mirror] Write databases (incremental)")
        databases_written, dbs_index = await self._write_databases_async(
            root=self.output_dir, incremental=True, prev_dbs=prev_dbs
        )
        self._cleanup_removed(prev_dbs, dbs_index)

        print("[Mirror] Write index")
        await self._write_root_index_async(self.output_dir, pages, dbs)
        await self._write_access_report_async(self.output_dir)
        await self._save_index_async(pages_index, dbs_index)

        return MirrorResult(local_dir=self.output_dir, pages_written=pages_written, databases_written=databases_written)

    def _populate_caches(self, pages: List[Dict[str, Any]], dbs: List[Dict[str, Any]]) -> None:
        for p in pages:
            pid = p.get("id")
            if pid:
                self._page_cache[pid] = p
        for d in dbs:
            did = d.get("id")
            if did:
                self._db_cache[did] = d

    async def _prefetch_pages(self) -> None:
        sem = asyncio.Semaphore(self._page_concurrency)

        async def fetch(pid: str) -> None:
            async with sem:
                try:
                    self._page_cache[pid] = await self.client.get_page(pid)
                except Exception:
                    pass

        await asyncio.gather(*(fetch(pid) for pid in self._page_cache.keys()))

    async def _prefetch_databases(self) -> None:
        sem = asyncio.Semaphore(self._page_concurrency)

        async def fetch(did: str) -> None:
            async with sem:
                try:
                    self._db_cache[did] = await self.client.get_database(did)
                except Exception:
                    pass

        await asyncio.gather(*(fetch(did) for did in self._db_cache.keys()))

    async def _write_pages_async(
        self, *, root: Path, incremental: bool, prev_pages: Optional[Dict[str, Any]]
    ) -> Tuple[int, Dict[str, Any]]:
        sem = asyncio.Semaphore(self._page_concurrency)
        results: List[Tuple[str, Optional[Dict[str, Any]], int]] = []
        page_ids = sorted(self._page_cache.keys())
        total = len(page_ids)
        progress = {"done": 0}
        progress_lock = asyncio.Lock()

        async def bump_progress() -> None:
            async with progress_lock:
                progress["done"] += 1
                print(f"[Mirror] Pages {progress['done']}/{total}")

        async def handle(pid: str) -> None:
            async with sem:
                try:
                    page = self._ensure_page(pid)
                    if page.get("archived"):
                        return
                    dest = self._page_output_path(pid, root=root)
                    dest.parent.mkdir(parents=True, exist_ok=True)

                    last_edited = page.get("last_edited_time") or ""
                    rel_path = dest.relative_to(root).as_posix()
                    if incremental and prev_pages is not None:
                        prev = prev_pages.get(pid, {})
                        if (
                            prev.get("last_edited_time") == last_edited
                            and prev.get("path") == rel_path
                            and dest.exists()
                        ):
                            results.append((pid, {"last_edited_time": last_edited, "path": rel_path}, 0))
                            return
                        old_path = prev.get("path")
                        if old_path and old_path != rel_path:
                            old_abs = root / Path(old_path)
                            if old_abs.exists():
                                old_abs.unlink()
                                self._cleanup_empty_dirs(old_abs.parent, root=root)

                    await self._write_page_markdown_async(dest, page)
                    results.append((pid, {"last_edited_time": last_edited, "path": rel_path}, 1))
                finally:
                    await bump_progress()

        await asyncio.gather(*(handle(pid) for pid in page_ids))
        pages_index = {pid: meta for pid, meta, _ in results if meta is not None}
        written = sum(count for _, _, count in results)
        return written, pages_index

    async def _write_databases_async(
        self, *, root: Path, incremental: bool, prev_dbs: Optional[Dict[str, Any]]
    ) -> Tuple[int, Dict[str, Any]]:
        sem = asyncio.Semaphore(self._page_concurrency)
        results: List[Tuple[str, Optional[Dict[str, Any]], int]] = []
        db_ids = sorted(self._db_cache.keys())
        total = len(db_ids)
        progress = {"done": 0}
        progress_lock = asyncio.Lock()

        async def bump_progress() -> None:
            async with progress_lock:
                progress["done"] += 1
                print(f"[Mirror] Databases {progress['done']}/{total}")

        async def handle(did: str) -> None:
            async with sem:
                try:
                    db = self._ensure_database(did)
                    if db.get("archived"):
                        return
                    folder = self._database_folder_path(did, root=root)
                    folder.mkdir(parents=True, exist_ok=True)
                    dest = folder / "__database.md"

                    last_edited = db.get("last_edited_time") or ""
                    rel_path = dest.relative_to(root).as_posix()
                    if incremental and prev_dbs is not None:
                        prev = prev_dbs.get(did, {})
                        if (
                            prev.get("last_edited_time") == last_edited
                            and prev.get("path") == rel_path
                            and dest.exists()
                        ):
                            results.append((did, {"last_edited_time": last_edited, "path": rel_path}, 0))
                            return
                        old_path = prev.get("path")
                        if old_path and old_path != rel_path:
                            old_abs = root / Path(old_path)
                            if old_abs.exists():
                                old_abs.unlink()
                                self._cleanup_empty_dirs(old_abs.parent, root=root)

                    await self._write_database_index_async(dest, db, did)
                    results.append((did, {"last_edited_time": last_edited, "path": rel_path}, 1))
                finally:
                    await bump_progress()

        await asyncio.gather(*(handle(did) for did in db_ids))
        dbs_index = {did: meta for did, meta, _ in results if meta is not None}
        written = sum(count for _, _, count in results)
        return written, dbs_index

    def _cleanup_removed(self, prev_index: Dict[str, Any], new_index: Dict[str, Any]) -> None:
        for item_id, meta in list(prev_index.items()):
            if item_id not in new_index:
                old_path = meta.get("path")
                if old_path:
                    old_abs = self.output_dir / Path(old_path)
                    if old_abs.exists():
                        old_abs.unlink()
                        self._cleanup_empty_dirs(old_abs.parent, root=self.output_dir)

    def _atomic_replace(self, tmp_dir: Path, final_dir: Path) -> None:
        if final_dir.exists():
            shutil.rmtree(final_dir, ignore_errors=True)
        tmp_dir.replace(final_dir)

    def _ensure_page(self, page_id: str) -> Dict[str, Any]:
        return self._page_cache.get(page_id) or {"id": page_id, "object": "page", "properties": {}}

    def _ensure_database(self, database_id: str) -> Dict[str, Any]:
        return self._db_cache.get(database_id) or {"id": database_id, "object": "database", "title": []}

    def _database_folder_path(self, database_id: str, *, root: Path) -> Path:
        db = self._ensure_database(database_id)
        title = safe_name(database_title(db), fallback="database")
        return root / f"DB_{title}_{_id8(database_id)}"

    def _page_folder_name(self, page: Dict[str, Any]) -> str:
        title = safe_name(page_title(page), fallback="page")
        return f"{title}_{_id8(page.get('id') or '')}"

    def _page_file_name(self, page: Dict[str, Any]) -> str:
        title = safe_name(page_title(page), fallback="page")
        return f"{title}_{_id8(page.get('id') or '')}.md"

    def _page_output_path(self, page_id: str, *, root: Path, _stack: Optional[Set[str]] = None) -> Path:
        if page_id in self._page_path_cache and str(self._page_path_cache[page_id]).startswith(str(root)):
            return self._page_path_cache[page_id]

        if _stack is None:
            _stack = set()
        if page_id in _stack:
            page = self._ensure_page(page_id)
            p = root / "_cycles" / self._page_file_name(page)
            self._page_path_cache[page_id] = p
            return p
        _stack.add(page_id)

        page = self._ensure_page(page_id)
        parent = page.get("parent") or {}
        parent_type = parent.get("type")

        if parent_type == "workspace":
            p = root / "_workspace" / self._page_file_name(page)
        elif parent_type == "database_id":
            folder = self._database_folder_path(parent.get("database_id"), root=root)
            p = folder / self._page_file_name(page)
        elif parent_type == "page_id":
            parent_id = parent.get("page_id")
            try:
                parent_dir = self._page_output_path(parent_id, root=root, _stack=_stack).with_suffix("")
                p = parent_dir / self._page_file_name(page)
            except Exception:
                p = root / "_orphans" / self._page_file_name(page)
        else:
            p = root / "_other" / self._page_file_name(page)

        self._page_path_cache[page_id] = p
        return p

    def _page_properties_md(self, page: Dict[str, Any]) -> List[str]:
        props = page.get("properties") or {}
        lines: List[str] = []
        for name, v in props.items():
            t = (v or {}).get("type")
            if t == "title":
                continue
            if t == "rich_text":
                lines.append(f"- {name}: {rich_text_to_md((v or {}).get('rich_text'))}")
            elif t == "select":
                sel = (v or {}).get("select") or {}
                lines.append(f"- {name}: {sel.get('name','')}")
            elif t == "multi_select":
                items = (v or {}).get("multi_select") or []
                lines.append(f"- {name}: {', '.join([i.get('name','') for i in items if i])}")
            elif t == "checkbox":
                lines.append(f"- {name}: {bool((v or {}).get('checkbox'))}")
            elif t == "number":
                lines.append(f"- {name}: {(v or {}).get('number')}")
            elif t == "url":
                lines.append(f"- {name}: {(v or {}).get('url') or ''}")
            elif t == "email":
                lines.append(f"- {name}: {(v or {}).get('email') or ''}")
            elif t == "phone_number":
                lines.append(f"- {name}: {(v or {}).get('phone_number') or ''}")
            elif t == "date":
                d = (v or {}).get("date") or {}
                lines.append(f"- {name}: {d.get('start','')}")
            elif t == "people":
                ppl = (v or {}).get("people") or []
                lines.append(f"- {name}: {', '.join([p.get('name','') for p in ppl if p])}")
            elif t == "files":
                files = (v or {}).get("files") or []
                lines.append(f"- {name}: {', '.join([f.get('name','') for f in files if f])}")
            elif t == "relation":
                rel = (v or {}).get("relation") or []
                lines.append(f"- {name}: {len(rel)} related")
            elif t == "status":
                st = (v or {}).get("status") or {}
                lines.append(f"- {name}: {st.get('name','')}")
        return lines

    async def _write_page_markdown_async(self, dest: Path, page: Dict[str, Any]) -> None:
        page_id = page.get("id") or ""
        title = page_title(page)
        url = page.get("url") or ""
        last_edited_time = page.get("last_edited_time") or ""

        lines: List[str] = []
        lines.append("---")
        lines.append(f"id: {page_id}")
        lines.append(f"url: {url}")
        lines.append(f"last_edited_time: {last_edited_time}")
        lines.append(f"mirror_generated_at: {_now_utc_iso()}")
        lines.append("---")
        lines.append("")
        lines.append(f"# {title}")
        lines.append("")

        props_lines = self._page_properties_md(page)
        if props_lines:
            lines.append("## Properties")
            lines.extend(props_lines)
            lines.append("")

        lines.append("## Content")
        lines.append("")
        try:
            blocks = await self.client.list_block_children(page_id)
            lines.extend(await self._render_blocks_async(blocks, depth=0, page_id=page_id))
        except Exception as e:
            # If the page itself is not accessible, keep the file and record the issue.
            self._inaccessible_blocks.append((page_id, page_id, str(e)))
            lines.append("- (content not accessible; check access report)")
        lines.append("")

        await asyncio.to_thread(dest.write_text, "\n".join(lines), encoding="utf-8")

    async def _render_blocks_async(self, blocks: List[Dict[str, Any]], *, depth: int, page_id: str) -> List[str]:
        lines: List[str] = []
        for b in blocks:
            lines.extend(block_to_md(b, depth=depth))
            if b.get("has_children"):
                try:
                    child_blocks = await self.client.list_block_children(b.get("id"))
                    lines.extend(await self._render_blocks_async(child_blocks, depth=depth + 1, page_id=page_id))
                except Exception as e:
                    block_id = b.get("id") or ""
                    self._inaccessible_blocks.append((page_id, block_id, str(e)))
                    lines.append(_indent(depth + 1) + "- (children not accessible; check access report)")
            lines.append("")
        while lines and lines[-1] == "":
            lines.pop()
        return lines

    async def _write_database_index_async(self, dest: Path, db: Dict[str, Any], database_id: str) -> None:
        title = database_title(db)
        url = db.get("url") or ""

        lines: List[str] = []
        lines.append("---")
        lines.append(f"id: {database_id}")
        lines.append(f"url: {url}")
        lines.append(f"mirror_generated_at: {_now_utc_iso()}")
        lines.append("---")
        lines.append("")
        lines.append(f"# {title}")
        lines.append("")

        try:
            pages = await self.client.query_database(database_id)
        except Exception:
            pages = []

        if pages:
            lines.append("## Entries")
            lines.append("")
            for p in pages:
                pid = p.get("id")
                if not pid:
                    continue
                self._page_cache.setdefault(pid, p)
                p_title = page_title(p)
                out_path = self._page_output_path(pid, root=dest.parent.parent)
                rel = out_path.relative_to(dest.parent)
                lines.append(f"- [{p_title}]({rel.as_posix()})")
        else:
            lines.append("## Entries")
            lines.append("")
            lines.append("- (no access or empty)")

        lines.append("")
        await asyncio.to_thread(dest.write_text, "\n".join(lines), encoding="utf-8")

    async def _write_root_index_async(self, root: Path, pages: List[Dict[str, Any]], dbs: List[Dict[str, Any]]) -> None:
        lines: List[str] = []
        lines.append("# Notion Mirror")
        lines.append("")
        lines.append(f"- Generated: {_now_utc_iso()}")
        lines.append(f"- Pages: {len(pages)}")
        lines.append(f"- Databases: {len(dbs)}")
        lines.append("")
        lines.append("## Top-level folders")
        lines.append("")
        lines.append("- `_workspace/` workspace pages")
        lines.append("- `DB_*` databases")
        lines.append("- `_orphans/` missing parents")
        lines.append("- `_other/` unknown parent types")
        lines.append("")

        await asyncio.to_thread((root / "index.md").write_text, "\n".join(lines), encoding="utf-8")

    async def _write_access_report_async(self, root: Path) -> None:
        if not self._inaccessible_blocks:
            return
        lines: List[str] = []
        lines.append("Notion access report")
        lines.append(f"Generated: {_now_utc_iso()}")
        lines.append("")
        lines.append("Blocks not accessible (likely not shared with integration):")
        lines.append("")
        for page_id, block_id, err in self._inaccessible_blocks:
            page = self._page_cache.get(page_id) or {}
            title = safe_name(page_title(page), fallback="page")
            lines.append(f"- page: {title} ({page_id})")
            lines.append(f"  block: {block_id}")
            lines.append(f"  error: {err}")
        await asyncio.to_thread((root / "access_issues.txt").write_text, "\n".join(lines), encoding="utf-8")

    def _index_path(self) -> Path:
        return self.output_dir / ".mirror_index.json"

    def _load_index(self) -> Dict[str, Any]:
        path = self._index_path()
        if not path.exists():
            return {"pages": {}, "databases": {}}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {"pages": {}, "databases": {}}

    async def _save_index_async(self, pages_index: Dict[str, Any], dbs_index: Dict[str, Any]) -> None:
        await self._save_index_to_async(self.output_dir, pages_index, dbs_index)

    async def _save_index_to_async(self, root: Path, pages_index: Dict[str, Any], dbs_index: Dict[str, Any]) -> None:
        payload = {
            "generated_at": _now_utc_iso(),
            "pages": pages_index,
            "databases": dbs_index,
        }
        await asyncio.to_thread(
            (root / ".mirror_index.json").write_text,
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _cleanup_empty_dirs(self, start_dir: Path, *, root: Path) -> None:
        cur = start_dir
        while cur != root and cur.exists():
            try:
                cur.rmdir()
            except OSError:
                break
            cur = cur.parent
