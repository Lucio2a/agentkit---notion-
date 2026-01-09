import os
from typing import Any, Dict, Optional, Tuple

from fastapi import FastAPI, HTTPException, Query
from notion_client import Client


app = FastAPI()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

if not NOTION_TOKEN or not NOTION_DATABASE_ID:
    notion = None
else:
    notion = Client(auth=NOTION_TOKEN)


def _ensure_notion():
    if notion is None:
        raise HTTPException(
            status_code=500,
            detail="Missing NOTION_TOKEN or NOTION_DATABASE_ID in environment variables",
        )


def _resolve_database_id(raw_database_id: str) -> Tuple[str, str, Dict[str, Any]]:
    """
    Returns (effective_id, mode, db_payload)

    mode:
      - "database"     -> normal Notion database with "properties"
      - "data_source"  -> Notion returns "data_sources" and might not include "properties"
    """
    _ensure_notion()
    db = notion.databases.retrieve(database_id=raw_database_id)

    # Normal database
    if db.get("properties"):
        return raw_database_id, "database", db

    # Data-source mode (new Notion behavior in some workspaces)
    data_sources = db.get("data_sources") or []
    if data_sources and isinstance(data_sources, list) and data_sources[0].get("id"):
        effective_id = data_sources[0]["id"]
        # Try retrieving the effective id to get properties (if supported)
        try:
            db2 = notion.databases.retrieve(database_id=effective_id)
            return effective_id, "data_source", db2 if isinstance(db2, dict) else db
        except Exception:
            # Even if retrieve fails, query may still work with effective_id
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
    return {"status": "ok"}


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

        res = notion.databases.query(database_id=effective_id, page_size=page_size)

        items = []
        for page in res.get("results", []) or []:
            page_id = page.get("id")
            title = _plain_title_from_page(page, title_prop)
            url = page.get("url") or f"https://www.notion.so/{page_id.replace('-', '')}"
            items.append({"page_id": page_id, "title": title, "url": url})

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

        created = notion.pages.create(
            parent={"database_id": effective_id},
            properties={
                title_prop: {"title": [{"text": {"content": title}}]},
            },
        )

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

        updated = notion.pages.update(
            page_id=page_id,
            properties={cb_prop: {"checkbox": checked}},
        )

        return {
            "status": "updated",
            "mode": mode,
            "page_id": updated.get("id"),
            "checkbox_property": cb_prop,
            "checked": checked,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
