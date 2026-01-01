from __future__ import annotations

import time
import asyncio
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

import requests
import httpx


class NotionError(RuntimeError):
    pass


@dataclass
class NotionClient:
    token: str
    notion_version: str
    timeout_s: int = 60

    def __post_init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self.token}",
                "Notion-Version": self.notion_version,
                "Content-Type": "application/json",
            }
        )

    def _request(self, method: str, url: str, *, json: Any | None = None) -> Dict[str, Any]:
        backoff_s = 1.0
        for attempt in range(8):
            resp = self._session.request(
                method,
                url,
                json=json,
                timeout=self.timeout_s,
                proxies={"http": None, "https": None},
            )
            if resp.status_code == 400 and "Notion-Version" in (resp.text or "") and self.notion_version != "2022-06-28":
                # Common misconfig: invalid Notion-Version header. Fall back once to a known stable version.
                self.notion_version = "2022-06-28"
                self._session.headers.update({"Notion-Version": self.notion_version})
                continue
            if resp.status_code in (429, 500, 502, 503, 504):
                retry_after = resp.headers.get("retry-after")
                if retry_after:
                    try:
                        backoff_s = max(backoff_s, float(retry_after))
                    except ValueError:
                        pass
                time.sleep(backoff_s)
                backoff_s = min(backoff_s * 2, 30.0)
                continue

            try:
                resp.raise_for_status()
            except requests.HTTPError as e:
                raise NotionError(f"Notion API error {resp.status_code}: {resp.text}") from e

            data = resp.json()
            if not isinstance(data, dict):
                raise NotionError("Unexpected Notion API response (not a JSON object).")
            return data

        raise NotionError(f"Notion API request failed after retries: {method} {url}")

    def search(self, *, object_type: str) -> List[Dict[str, Any]]:
        url = "https://api.notion.com/v1/search"
        start_cursor: Optional[str] = None
        results: List[Dict[str, Any]] = []

        # Notion API now expects "data_source" for databases in search filter.
        filter_value = object_type
        if object_type == "database":
            filter_value = "data_source"

        def do_request() -> Dict[str, Any]:
            payload: Dict[str, Any] = {"page_size": 100, "filter": {"property": "object", "value": filter_value}}
            if start_cursor:
                payload["start_cursor"] = start_cursor
            return self._request("POST", url, json=payload)

        while True:
            try:
                data = do_request()
            except NotionError as e:
                # Backward-compat guard if a cached version still sends "database".
                if object_type == "database" and filter_value != "data_source" and "data_source" in str(e):
                    filter_value = "data_source"
                    data = do_request()
                else:
                    raise
            results.extend(data.get("results", []) or [])
            if not data.get("has_more"):
                break
            start_cursor = data.get("next_cursor")

        return results

    def get_page(self, page_id: str) -> Dict[str, Any]:
        return self._request("GET", f"https://api.notion.com/v1/pages/{page_id}")

    def get_database(self, database_id: str) -> Dict[str, Any]:
        return self._request("GET", f"https://api.notion.com/v1/databases/{database_id}")

    def query_database(self, database_id: str) -> List[Dict[str, Any]]:
        url = f"https://api.notion.com/v1/databases/{database_id}/query"
        start_cursor: Optional[str] = None
        pages: List[Dict[str, Any]] = []

        while True:
            payload: Dict[str, Any] = {"page_size": 100}
            if start_cursor:
                payload["start_cursor"] = start_cursor
            data = self._request("POST", url, json=payload)
            pages.extend(data.get("results", []) or [])
            if not data.get("has_more"):
                break
            start_cursor = data.get("next_cursor")

        return pages

    def list_block_children(self, block_id: str) -> List[Dict[str, Any]]:
        start_cursor: Optional[str] = None
        blocks: List[Dict[str, Any]] = []

        while True:
            url = f"https://api.notion.com/v1/blocks/{block_id}/children?page_size=100"
            if start_cursor:
                url += f"&start_cursor={start_cursor}"
            data = self._request("GET", url)
            blocks.extend(data.get("results", []) or [])
            if not data.get("has_more"):
                break
            start_cursor = data.get("next_cursor")

        return blocks


class AsyncRateLimiter:
    def __init__(self, *, rate_per_sec: int = 3, burst: int = 3) -> None:
        self._rate = max(rate_per_sec, 1)
        self._burst = max(burst, 1)
        self._lock = asyncio.Lock()
        self._timestamps: List[float] = []

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                self._timestamps = [t for t in self._timestamps if now - t < 1.0]
                if len(self._timestamps) < self._burst:
                    self._timestamps.append(now)
                    return
                sleep_for = 1.0 - (now - self._timestamps[0])
            await asyncio.sleep(max(sleep_for, 0.01))


@dataclass
class AsyncNotionClient:
    token: str
    notion_version: str
    timeout_s: int = 60
    rate_limit_per_sec: int = 3
    max_in_flight: int = 8

    def __post_init__(self) -> None:
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {self.token}",
                "Notion-Version": self.notion_version,
                "Content-Type": "application/json",
            },
            timeout=self.timeout_s,
            trust_env=False,
        )
        self._limiter = AsyncRateLimiter(rate_per_sec=self.rate_limit_per_sec, burst=self.rate_limit_per_sec)
        self._semaphore = asyncio.Semaphore(max(self.max_in_flight, 1))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, url: str, *, json: Any | None = None) -> Dict[str, Any]:
        backoff_s = 1.0
        for attempt in range(8):
            await self._limiter.acquire()
            async with self._semaphore:
                resp = await self._client.request(method, url, json=json)
            if resp.status_code == 400 and "Notion-Version" in (resp.text or "") and self.notion_version != "2022-06-28":
                self.notion_version = "2022-06-28"
                self._client.headers.update({"Notion-Version": self.notion_version})
                continue
            if resp.status_code in (429, 500, 502, 503, 504):
                retry_after = resp.headers.get("retry-after")
                if retry_after:
                    try:
                        backoff_s = max(backoff_s, float(retry_after))
                    except ValueError:
                        pass
                await asyncio.sleep(backoff_s)
                backoff_s = min(backoff_s * 2, 30.0)
                continue

            try:
                resp.raise_for_status()
            except httpx.HTTPError as e:
                raise NotionError(f"Notion API error {resp.status_code}: {resp.text}") from e

            data = resp.json()
            if not isinstance(data, dict):
                raise NotionError("Unexpected Notion API response (not a JSON object).")
            return data

        raise NotionError(f"Notion API request failed after retries: {method} {url}")

    async def search(self, *, object_type: str) -> List[Dict[str, Any]]:
        url = "https://api.notion.com/v1/search"
        start_cursor: Optional[str] = None
        results: List[Dict[str, Any]] = []

        filter_value = object_type
        if object_type == "database":
            filter_value = "data_source"

        async def do_request() -> Dict[str, Any]:
            payload: Dict[str, Any] = {"page_size": 100, "filter": {"property": "object", "value": filter_value}}
            if start_cursor:
                payload["start_cursor"] = start_cursor
            return await self._request("POST", url, json=payload)

        while True:
            try:
                data = await do_request()
            except NotionError as e:
                if object_type == "database" and filter_value != "data_source" and "data_source" in str(e):
                    filter_value = "data_source"
                    data = await do_request()
                else:
                    raise
            results.extend(data.get("results", []) or [])
            if not data.get("has_more"):
                break
            start_cursor = data.get("next_cursor")

        return results

    async def get_page(self, page_id: str) -> Dict[str, Any]:
        return await self._request("GET", f"https://api.notion.com/v1/pages/{page_id}")

    async def get_database(self, database_id: str) -> Dict[str, Any]:
        return await self._request("GET", f"https://api.notion.com/v1/databases/{database_id}")

    async def query_database(self, database_id: str) -> List[Dict[str, Any]]:
        url = f"https://api.notion.com/v1/databases/{database_id}/query"
        start_cursor: Optional[str] = None
        pages: List[Dict[str, Any]] = []

        while True:
            payload: Dict[str, Any] = {"page_size": 100}
            if start_cursor:
                payload["start_cursor"] = start_cursor
            data = await self._request("POST", url, json=payload)
            pages.extend(data.get("results", []) or [])
            if not data.get("has_more"):
                break
            start_cursor = data.get("next_cursor")

        return pages

    async def list_block_children(self, block_id: str) -> List[Dict[str, Any]]:
        start_cursor: Optional[str] = None
        blocks: List[Dict[str, Any]] = []

        while True:
            url = f"https://api.notion.com/v1/blocks/{block_id}/children?page_size=100"
            if start_cursor:
                url += f"&start_cursor={start_cursor}"
            data = await self._request("GET", url)
            blocks.extend(data.get("results", []) or [])
            if not data.get("has_more"):
                break
            start_cursor = data.get("next_cursor")

        return blocks
