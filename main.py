from fastapi import FastAPI, HTTPException
import os, requests

app = FastAPI()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_VERSION = "2022-06-28"

def notion_headers():
    if not NOTION_TOKEN:
        raise HTTPException(status_code=500, detail="Missing NOTION_TOKEN")
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json"
    }

@app.get("/")
def root():
    return {"status": "Notion backend OK"}

@app.get("/notion/databases")
def list_all_databases():
    url = "https://api.notion.com/v1/search"
    payload = {
        "filter": {
            "property": "object",
            "value": "database"
        }
    }

    r = requests.post(url, headers=notion_headers(), json=payload)

    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)

    results = r.json().get("results", [])

    databases = []
    for db in results:
        databases.append({
            "id": db["id"],
            "title": "".join(
                t["plain_text"]
                for t in db.get("title", [])
            ),
            "url": db["url"]
        })

    return {
        "count": len(databases),
        "databases": databases
    }
