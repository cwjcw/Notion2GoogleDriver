import os, requests
from pathlib import Path
from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parent / ".env")
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_VERSION = os.getenv("NOTION_VERSION", "2022-06-28")

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type": "application/json",
}

def notion_search_all():
    url = "https://api.notion.com/v1/search"
    start_cursor = None
    pages, dbs, others = [], [], []

    while True:
        payload = {"page_size": 100}
        if start_cursor:
            payload["start_cursor"] = start_cursor

        r = requests.post(
        url,
        headers=HEADERS,
        json=payload,
        timeout=60,
        proxies={"http": None, "https": None},
)

        r.raise_for_status()
        data = r.json()

        for item in data.get("results", []):
            obj = item.get("object")
            if obj == "page":
                pages.append(item)
            elif obj == "database":
                dbs.append(item)
            else:
                others.append(item)

        if not data.get("has_more"):
            break
        start_cursor = data.get("next_cursor")

    return pages, dbs, others

def title_of(item):
    # page/database 标题字段形态略不同，这里做个兜底展示
    if item.get("object") == "database":
        t = item.get("title", [])
        return "".join([x.get("plain_text","") for x in t]) or "untitled_db"
    if item.get("object") == "page":
        props = item.get("properties", {})
        for _, v in props.items():
            if v.get("type") == "title":
                return "".join([x.get("plain_text","") for x in v.get("title", [])]) or "untitled_page"
        return "untitled_page"
    return "unknown"

if __name__ == "__main__":
    pages, dbs, others = notion_search_all()
    print(f"Pages: {len(pages)}")
    print(f"Databases: {len(dbs)}")
    print(f"Others: {len(others)}")
    print("\nSample Pages:")
    for p in pages[:20]:
        print("-", title_of(p), p.get("id"))
    print("\nSample Databases:")
    for d in dbs[:20]:
        print("-", title_of(d), d.get("id"))
