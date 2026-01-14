import os
from typing import Any, Dict, Optional, List

import requests
from fastapi import FastAPI, HTTPException

app = FastAPI(title="Notion backend", version="1.0.0")

NOTION_TOKEN = os.getenv("NOTION_TOKEN", "").strip()
NOTION_VERSION = os.getenv("NOTION_VERSION", "2022-06-28").strip()


def _headers() -> Dict[str, str]:
    if not NOTION_TOKEN:
        raise HTTPException(status_code=500, detail="Missing NOTION_TOKEN")
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _notion_request(method: str, url: str, json: Optional[dict] = None) -> dict:
    try:
        r = requests.request(method, url, headers=_headers(), json=json, timeout=30)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"HTTP error: {e}")

    # Notion renvoie souvent du 4xx/5xx avec message utile dans le body
    if r.status_code < 200 or r.status_code >= 300:
        raise HTTPException(status_code=r.status_code, detail=r.text)

    return r.json() if r.text else {}


@app.get("/")
def root():
    return {
        "status": "Notion backend OK",
        "endpoints": [
            "GET  /notion/test",
            "GET  /notion/databases",
            "GET  /notion/database/{db_id}",
        ],
        "notion_version": NOTION_VERSION,
    }


@app.get("/notion/test")
def notion_test():
    """
    Vérifie que le token marche (appel /users/me).
    """
    data = _notion_request("GET", "https://api.notion.com/v1/users/me")
    return {
        "ok": True,
        "user": {
            "id": data.get("id"),
            "name": data.get("name"),
            "type": data.get("type"),
        },
        "token_present": bool(NOTION_TOKEN),
        "notion_version": NOTION_VERSION,
    }


@app.get("/notion/databases")
def list_databases(page_size: int = 100):
    """
    Liste TOUTES les databases visibles par l'intégration.
    IMPORTANT:
    - Notion ne "découvre" que ce qui est partagé à l'intégration.
    - Si une database n'est pas partagée, elle n'apparaîtra pas ici.
    """
    if page_size < 1 or page_size > 100:
        raise HTTPException(status_code=400, detail="page_size must be between 1 and 100")

    url = "https://api.notion.com/v1/search"

    payload = {
        "page_size": page_size,
        "filter": {"property": "object", "value": "database"},
        # tri optionnel
        "sort": {"direction": "descending", "timestamp": "last_edited_time"},
    }

    databases: List[Dict[str, Any]] = []
    has_more = True
    start_cursor = None

    while has_more:
        if start_cursor:
            payload["start_cursor"] = start_cursor

        data = _notion_request("POST", url, json=payload)

        for db in data.get("results", []):
            # titre lisible
            title = ""
            t = db.get("title", [])
            if isinstance(t, list):
                title = "".join([x.get("plain_text", "") for x in t if isinstance(x, dict)])

            databases.append(
                {
                    "id": db.get("id"),
                    "title": title,
                    "url": db.get("url"),
                    "last_edited_time": db.get("last_edited_time"),
                }
            )

        has_more = bool(data.get("has_more"))
        start_cursor = data.get("next_cursor")

        # garde-fou: on ne boucle pas à l’infini
        if start_cursor is None:
            break

    return {
        "count": len(databases),
        "databases": databases,
    }


@app.get("/notion/database/{db_id}")
def get_database(db_id: str):
    """
    Donne le schéma exact (properties) d'une database.
    C'est ça qui permet ensuite de créer une page sans bug (checkbox, date, title, etc.).
    """
    url = f"https://api.notion.com/v1/databases/{db_id}"
    db = _notion_request("GET", url)

    # titre lisible
    title = ""
    t = db.get("title", [])
    if isinstance(t, list):
        title = "".join([x.get("plain_text", "") for x in t if isinstance(x, dict)])

    return {
        "id": db.get("id"),
        "title": title,
        "url": db.get("url"),
        "properties": db.get("properties", {}),
    }
