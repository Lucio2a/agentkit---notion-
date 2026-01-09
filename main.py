import os
from typing import Any, Dict, Optional, Tuple
from fastapi import FastAPI, HTTPException, Query
import requests

app = FastAPI()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
NOTION_VERSION = "2022-06-28"

def _get_headers():
    if not NOTION_TOKEN:
        raise HTTPException(status_code=500, detail="Missing NOTION_TOKEN")
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json"
    }

def _ensure_notion():
    if not NOTION_TOKEN or not NOTION_DATABASE_ID:
        raise HTTPException(
            status_code=500,
            detail="Missing NOTION_TOKEN or NOTION_DATABASE_ID in environment variables",
        )

def _resolve_database_id(raw_database_id: str) -> Tuple[str, str, Dict[str, Any]]:
    """
    Returns (effective_id, mode, db_payload)
    mode:
    - "database" -> normal Notion database with "properties"
    - "data_source" -> Notion returns "data_sources" and might not include "properties"
    """
    _ensure_notion()
    
    url = f"https://api.notion.com/v1/databases/{raw_database_id}"
    response = requests.get(url, headers=_get_headers())
    
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    
    db = response.json()
    
    # Normal database
    if db.get("properties"):
        return raw_database_id, "database", db
    
    # Data-source mode (new Notion behavior in some workspaces)
    data_sources = db.get("data_sources") or []
    if data_sources and isinstance(data_sources, list) and data_sources[0].get("id"):
        effective_id = data_sources[0]["id"]
        # Try retrieving the effective id to get properties (if supported)
        try:
            url2 = f"https://api.notion.com/v1/databases/{effective_id}"
            response2 = requests.get(url2, headers=_get_headers())
            if response2.status_code == 200:
                db2 = response2.json()
                return effective_id, "data_source", db2
        except Exception:
            pass
        return effective_id, "data_source", db
    
    return raw_database_id, "unknown", db

def _get_title_property_name(db_payload: Dict[str, Any]) -> str:
    props = db_payload.get("properties") or {}
    for name, prop in props.items():
        if prop.get("type") == "title":
            return name
    raise ValueError("No title property found in database (API: type 'title')")

def _get_checkbox_property_name(db_payload: Dict[str, Any]) -> str:
    props = db_payload.get("properties") or {}
    for name, prop in props.items():
        if prop.get("type") == "checkbox":
            return name
    raise ValueError("No checkbox property found in database (API: type 'checkbox')")

def _plain_title_from_page(page: Dict[str, Any], title_prop: str) -> str:
    props = page.get("properties", {}) or {}
    title_arr = props.get(title_prop, {}).get("title", []) or []
    text = "".join([t.get("plain_text", "") for t in title_arr])
    return text.strip() if text.strip() else "(untitled)"


@app.get("/")
def root():
    return {"status": "ok", "message": "API Notion opérationnelle"}


@app.get("/notion/test")
def notion_test():
    _ensure_notion()
    try:
        effective_id, mode, db = _resolve_database_id(NOTION_DATABASE_ID)
        title_prop = _get_title_property_name(db)
        return {
            "status": "ok",
            "mode": mode,
            "database_id": NOTION_DATABASE_ID,
            "effective_id": effective_id,
            "title_property": title_prop,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/notion/read")
def notion_read(page_size: int = Query(5, ge=1, le=50)):
    _ensure_notion()
    try:
        effective_id, mode, db = _resolve_database_id(NOTION_DATABASE_ID)
        title_prop = _get_title_property_name(db)
        
        # Query database
        url = f"https://api.notion.com/v1/databases/{effective_id}/query"
        response = requests.post(url, headers=_get_headers(), json={"page_size": page_size})
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=response.text)
        
        res = response.json()
        
        items = []
        for page in res.get("results", []) or []:
            page_id = page.get("id")
            title = _plain_title_from_page(page, title_prop)
            page_url = page.get("url") or f"https://www.notion.so/{page_id.replace('-', '')}"
            items.append({"page_id": page_id, "title": title, "url": page_url})

        return {
            "status": "success",
            "mode": mode,
            "database_id": NOTION_DATABASE_ID,
            "effective_id": effective_id,
            "count": len(items),
            "items": items,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/notion/write")
def notion_write(title: str = "TEST - created via Render"):
    _ensure_notion()
    try:
        effective_id, mode, db = _resolve_database_id(NOTION_DATABASE_ID)
        title_prop = _get_title_property_name(db)
        
        # Create page
        url = "https://api.notion.com/v1/pages"
        payload = {
            "parent": {"database_id": effective_id},
            "properties": {
                title_prop: {"title": [{"text": {"content": title}}]},
            },
        }
        
        response = requests.post(url, headers=_get_headers(), json=payload)
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=response.text)
        
        created = response.json()
        
        return {
            "status": "created",
            "mode": mode,
            "page_id": created.get("id"),
            "title": title,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/notion/checkbox")
def notion_set_checkbox(
    page_id: str,
    checked: bool = True,
    checkbox_name: Optional[str] = None,
):
    """
    Set a checkbox property on a page.
    - page_id: Notion page id (with or without dashes)
    - checked: true/false
    - checkbox_name: optional, if not provided we auto-pick the first checkbox property in the DB
    """
    _ensure_notion()
    try:
        effective_id, mode, db = _resolve_database_id(NOTION_DATABASE_ID)
        cb_prop = checkbox_name or _get_checkbox_property_name(db)
        
        # Update page
        url = f"https://api.notion.com/v1/pages/{page_id}"
        payload = {
            "properties": {cb_prop: {"checkbox": checked}}
        }
        
        response = requests.patch(url, headers=_get_headers(), json=payload)
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=response.text)
        
        updated = response.json()
        
        return {
            "status": "updated",
            "mode": mode,
            "page_id": updated.get("id"),
            "checkbox_property": cb_prop,
            "checked": checked,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
