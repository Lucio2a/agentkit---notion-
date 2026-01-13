import os
import requests
from fastapi import FastAPI, HTTPException

app = FastAPI()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_VERSION = "2022-06-28"
ROOT_PAGE_ID = "529fa9d192114d6e8c85be07e17c5cfc"

def notion_headers():
    if not NOTION_TOKEN:
        raise HTTPException(status_code=500, detail="Missing NOTION_TOKEN")
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }

@app.get("/")
def root():
    return {"status": "Notion backend OK"}

@app.get("/notion/databases")
def list_databases_under_root():
    """
    Liste toutes les databases du workspace
    (Notion ne permet PAS de lister uniquement par page parent,
    donc on filtre côté backend).
    """
    url = "https://api.notion.com/v1/search"
    payload = {
        "filter": {"property": "object", "value": "database"},
        "page_size": 100
    }

    res = requests.post(url, headers=notion_headers(), json=payload)
    if res.status_code != 200:
        raise HTTPException(status_code=res.status_code, detail=res.text)

    data = res.json()["results"]

    databases = []
    for db in data:
        parent = db.get("parent", {})
        if parent.get("page_id") == ROOT_PAGE_ID:
            databases.append({
                "id": db["id"],
                "title": "".join(
                    t["plain_text"]
                    for t in db["title"]
                ),
                "url": db["url"]
            })

    return {
        "root_page_id": ROOT_PAGE_ID,
        "count": len(databases),
        "databases": databases
    }
