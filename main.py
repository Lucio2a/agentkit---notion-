from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional, Literal
import os
from notion_client import Client

app = FastAPI()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

if not NOTION_TOKEN or not NOTION_DATABASE_ID:
    notion = None
else:
    notion = Client(auth=NOTION_TOKEN)


# -----------------------------
# Helpers
# -----------------------------
def _ensure_notion():
    if notion is None:
        raise HTTPException(status_code=500, detail="Missing NOTION_TOKEN or NOTION_DATABASE_ID")


def _get_title_prop_name(database_id: str) -> str:
    """
    Returns the property name whose type is 'title' (e.g. 'Nom').
    """
    db = notion.databases.retrieve(database_id=database_id)
    props = db.get("properties", {}) or {}
    for prop_name, prop in props.items():
        if prop.get("type") == "title":
            return prop_name
    raise ValueError("No title property found in database (API: type 'title')")


def _resolve_db_id(initial_id: str) -> Dict[str, str]:
    """
    Some Notion DB pages return data_sources but no properties. In that case,
    use the first data_source id (works with query/create in your setup).
    Returns: {"mode": "...", "database_id": "..."}.
    """
    db = notion.databases.retrieve(database_id=initial_id)

    # Normal database (has properties)
    if db.get("properties"):
        return {"mode": "database", "database_id": initial_id}

    # Inline / data_source case
    data_sources = db.get("data_sources") or []
    if data_sources:
        return {"mode": "data_source", "database_id": data_sources[0]["id"]}

    return {"mode": "unknown", "database_id": initial_id}


def _make_simple_properties(title_prop: str, title: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Build a minimal Notion properties payload.
    extra expects already-Notion-shaped property values if provided.
    """
    props = {
        title_prop: {"title": [{"text": {"content": title}}]}
    }
    if extra:
        props.update(extra)
    return props


# -----------------------------
# Existing basic routes
# -----------------------------
@app.get("/notion/test")
def notion_test():
    _ensure_notion()
    try:
        resolved = _resolve_db_id(NOTION_DATABASE_ID)
        title_prop = _get_title_prop_name(resolved["database_id"])
        return {
            "status": "ok",
            "id": NOTION_DATABASE_ID,
            "mode": resolved["mode"],
            "database_id_used": resolved["database_id"],
            "title_property": title_prop,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/notion/read")
def notion_read(page_size: int = 5):
    _ensure_notion()
    try:
        resolved = _resolve_db_id(NOTION_DATABASE_ID)
        db_id = resolved["database_id"]
        title_prop = _get_title_prop_name(db_id)

        res = notion.databases.query(database_id=db_id, page_size=page_size)

        items = []
        for page in res.get("results", []):
            props = page.get("properties", {}) or {}
            title_obj = props.get(title_prop, {}).get("title", []) or []
            title_text = "".join([t.get("plain_text", "") for t in title_obj]) if title_obj else ""
            items.append({"page_id": page.get("id"), "title": title_text})

        return {"mode": resolved["mode"], "title_property": title_prop, "items": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/notion/write")
def notion_write(title: str = "TEST - creation via Render"):
    _ensure_notion()
    try:
        resolved = _resolve_db_id(NOTION_DATABASE_ID)
        db_id = resolved["database_id"]
        title_prop = _get_title_prop_name(db_id)

        created = notion.pages.create(
            parent={"database_id": db_id},
            properties=_make_simple_properties(title_prop, title),
        )
        return {"status": "created", "mode": resolved["mode"], "page_id": created.get("id"), "title": title}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -----------------------------
# ONE central endpoint for your Coach
# -----------------------------
ActionType = Literal["read", "create", "update_checkbox", "update_text"]


class NotionAction(BaseModel):
    action: ActionType

    # read
    page_size: int = 5

    # create
    title: Optional[str] = None
    extra_properties: Optional[Dict[str, Any]] = None  # Notion-shaped values

    # update
    page_id: Optional[str] = None
    property_name: Optional[str] = None

    # checkbox
    checked: Optional[bool] = None

    # text
    text: Optional[str] = None


@app.post("/notion/action")
def notion_action(payload: NotionAction):
    """
    Single endpoint for your GPT Coach.
    - action=read: returns latest items
    - action=create: creates page with title (+ optional extra properties)
    - action=update_checkbox: set a checkbox property
    - action=update_text: set a rich_text property
    """
    _ensure_notion()

    try:
        resolved = _resolve_db_id(NOTION_DATABASE_ID)
        db_id = resolved["database_id"]
        mode = resolved["mode"]

        # Always find title property (needed for create, also useful for read)
        title_prop = _get_title_prop_name(db_id)

        if payload.action == "read":
            res = notion.databases.query(database_id=db_id, page_size=payload.page_size)
            items = []
            for page in res.get("results", []):
                props = page.get("properties", {}) or {}
                title_obj = props.get(title_prop, {}).get("title", []) or []
                title_text = "".join([t.get("plain_text", "") for t in title_obj]) if title_obj else ""
                items.append({"page_id": page.get("id"), "title": title_text})
            return {"mode": mode, "title_property": title_prop, "items": items}

        if payload.action == "create":
            if not payload.title:
                raise HTTPException(status_code=400, detail="Missing 'title' for create")

            created = notion.pages.create(
                parent={"database_id": db_id},
                properties=_make_simple_properties(title_prop, payload.title, payload.extra_properties),
            )
            return {"status": "created", "mode": mode, "page_id": created.get("id"), "title": payload.title}

        if payload.action == "update_checkbox":
            if not payload.page_id or not payload.property_name or payload.checked is None:
                raise HTTPException(status_code=400, detail="Need page_id, property_name, checked")

            notion.pages.update(
                page_id=payload.page_id,
                properties={
                    payload.property_name: {"checkbox": payload.checked}
                },
            )
            return {"status": "updated", "mode": mode, "page_id": payload.page_id, "property": payload.property_name, "checked": payload.checked}

        if payload.action == "update_text":
            if not payload.page_id or not payload.property_name or payload.text is None:
                raise HTTPException(status_code=400, detail="Need page_id, property_name, text")

            notion.pages.update(
                page_id=payload.page_id,
                properties={
                    payload.property_name: {"rich_text": [{"text": {"content": payload.text}}]}
                },
            )
            return {"status": "updated", "mode": mode, "page_id": payload.page_id, "property": payload.property_name, "text": payload.text}

        raise HTTPException(status_code=400, detail="Unknown action")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
