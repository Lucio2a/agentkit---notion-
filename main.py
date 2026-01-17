import os
from typing import Any, Dict, List, Optional

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
NOTION_VERSION = "2022-06-28"


def _get_headers() -> Dict[str, str]:
    if not NOTION_TOKEN:
        raise HTTPException(status_code=500, detail="Missing NOTION_TOKEN")
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _request(method: str, url: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    response = requests.request(method, url, headers=_get_headers(), json=payload)
    if not response.ok:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    return response.json()


def _simplify_properties(properties: Dict[str, Any]) -> Dict[str, Any]:
    simplified: Dict[str, Any] = {}
    for prop_name, prop_data in properties.items():
        prop_type = prop_data.get("type")
        if prop_type == "title":
            simplified[prop_name] = "".join(
                part.get("plain_text", "") for part in prop_data.get("title", [])
            )
        elif prop_type == "rich_text":
            simplified[prop_name] = "".join(
                part.get("plain_text", "") for part in prop_data.get("rich_text", [])
            )
        elif prop_type == "number":
            simplified[prop_name] = prop_data.get("number")
        elif prop_type == "select":
            simplified[prop_name] = (prop_data.get("select") or {}).get("name")
        elif prop_type == "multi_select":
            simplified[prop_name] = [item.get("name") for item in prop_data.get("multi_select", [])]
        elif prop_type == "date":
            simplified[prop_name] = prop_data.get("date")
        elif prop_type == "people":
            simplified[prop_name] = [person.get("name") for person in prop_data.get("people", [])]
        elif prop_type == "files":
            simplified[prop_name] = prop_data.get("files")
        elif prop_type == "checkbox":
            simplified[prop_name] = prop_data.get("checkbox")
        elif prop_type == "url":
            simplified[prop_name] = prop_data.get("url")
        elif prop_type == "email":
            simplified[prop_name] = prop_data.get("email")
        elif prop_type == "phone_number":
            simplified[prop_name] = prop_data.get("phone_number")
        elif prop_type == "status":
            simplified[prop_name] = (prop_data.get("status") or {}).get("name")
        else:
            simplified[prop_name] = prop_data
    return simplified


# ==================== MODÈLES ====================


class NotionAction(BaseModel):
    action: str = Field(
        ...,
        description=(
            "Action à effectuer: read, create, update, delete, search, get_database, "
            "create_database, update_database, get_page, append_blocks"
        ),
    )

    # Pour read/search
    database_id: Optional[str] = None
    block_id: Optional[str] = None
    page_size: int = Field(default=10, ge=1, le=100)
    filter: Optional[Dict[str, Any]] = None
    sorts: Optional[List[Dict[str, Any]]] = None

    # Pour create/update
    page_id: Optional[str] = None
    properties: Optional[Dict[str, Any]] = None
    children: Optional[List[Dict[str, Any]]] = None
    block: Optional[Dict[str, Any]] = None

    # Pour search
    query: Optional[str] = None

    # Pour create_database
    parent_page_id: Optional[str] = None
    title: Optional[str] = None
    database_properties: Optional[Dict[str, Any]] = None

    # Pour archives/delete
    archived: Optional[bool] = None


# ==================== ENDPOINT UNIVERSEL ====================


@app.post("/notion/universal")
async def notion_universal(action: NotionAction) -> Dict[str, Any]:
    """
    Endpoint universel pour TOUTES les opérations Notion.

    Actions disponibles:
    - read: Lire les pages d'une database
    - create: Créer une page
    - update: Modifier une page
    - delete: Archiver une page
    - search: Rechercher
    - get_database: Infos database
    - create_database: Créer database
    - update_database: Modifier database
    - get_page: Obtenir une page
    - append_blocks: Ajouter du contenu
    """
    try:
        if action.action == "read":
            db_id = action.database_id or NOTION_DATABASE_ID
            if not db_id:
                raise HTTPException(status_code=400, detail="database_id required")
            payload: Dict[str, Any] = {"page_size": action.page_size}
            if action.filter:
                payload["filter"] = action.filter
            if action.sorts:
                payload["sorts"] = action.sorts
            data = _request("POST", f"https://api.notion.com/v1/databases/{db_id}/query", payload)
            items = []
            for item in data.get("results", []):
                items.append(
                    {
                        "id": item.get("id"),
                        "url": item.get("url"),
                        "properties": _simplify_properties(item.get("properties", {})),
                    }
                )
            return {
                "status": "success",
                "action": "read",
                "count": len(items),
                "has_more": data.get("has_more"),
                "items": items,
            }

        if action.action == "create":
            db_id = action.database_id or NOTION_DATABASE_ID
            if not db_id:
                raise HTTPException(status_code=400, detail="database_id required")
            if not action.properties or not isinstance(action.properties, dict):
                raise HTTPException(status_code=400, detail="properties must be a dict")
            payload: Dict[str, Any] = {
                "parent": {"database_id": db_id},
                "properties": action.properties,
            }
            if action.children:
                payload["children"] = action.children
            created = _request("POST", "https://api.notion.com/v1/pages", payload)
            return {
                "status": "ok",
                "created_page_id": created.get("id"),
                "url": created.get("url"),
            }

        if action.action == "update":
            if action.block_id:
                if not action.block:
                    raise HTTPException(status_code=400, detail="block payload required")
                updated = _request(
                    "PATCH", f"https://api.notion.com/v1/blocks/{action.block_id}", action.block
                )
                return {
                    "status": "success",
                    "action": "update",
                    "block_id": updated.get("id"),
                    "result": updated,
                }
            if not action.page_id:
                raise HTTPException(status_code=400, detail="page_id required for update")
            if not action.properties:
                raise HTTPException(status_code=400, detail="properties required for update")
            updated = _request(
                "PATCH",
                f"https://api.notion.com/v1/pages/{action.page_id}",
                {"properties": action.properties},
            )
            return {
                "status": "success",
                "action": "update",
                "page_id": updated.get("id"),
                "result": updated,
            }

        if action.action == "delete":
            if not action.page_id:
                raise HTTPException(status_code=400, detail="page_id required for delete")
            archived = True if action.archived is None else action.archived
            deleted = _request(
                "PATCH",
                f"https://api.notion.com/v1/pages/{action.page_id}",
                {"archived": archived},
            )
            return {
                "status": "success",
                "action": "delete",
                "page_id": deleted.get("id"),
                "archived": deleted.get("archived"),
            }

        if action.action == "search":
            payload: Dict[str, Any] = {"page_size": action.page_size}
            if action.query:
                payload["query"] = action.query
            if action.filter:
                payload["filter"] = action.filter
            if action.sorts:
                payload["sorts"] = action.sorts
            data = _request("POST", "https://api.notion.com/v1/search", payload)
            return {
                "status": "success",
                "action": "search",
                "count": len(data.get("results", [])),
                "has_more": data.get("has_more"),
                "results": data.get("results"),
            }

        if action.action == "get_database":
            db_id = action.database_id or NOTION_DATABASE_ID
            if not db_id:
                raise HTTPException(status_code=400, detail="database_id required")
            data = _request("GET", f"https://api.notion.com/v1/databases/{db_id}")
            return {"status": "success", "action": "get_database", "database": data}

        if action.action == "create_database":
            if not action.parent_page_id:
                raise HTTPException(status_code=400, detail="parent_page_id required")
            if not action.title:
                raise HTTPException(status_code=400, detail="title required")
            if not action.database_properties:
                raise HTTPException(status_code=400, detail="database_properties required")
            payload = {
                "parent": {"type": "page_id", "page_id": action.parent_page_id},
                "title": [{"type": "text", "text": {"content": action.title}}],
                "properties": action.database_properties,
            }
            created = _request("POST", "https://api.notion.com/v1/databases", payload)
            return {
                "status": "success",
                "action": "create_database",
                "database_id": created.get("id"),
                "url": created.get("url"),
            }

        if action.action == "update_database":
            db_id = action.database_id or NOTION_DATABASE_ID
            if not db_id:
                raise HTTPException(status_code=400, detail="database_id required")
            payload: Dict[str, Any] = {}
            if action.title:
                payload["title"] = [{"type": "text", "text": {"content": action.title}}]
            if action.database_properties:
                payload["properties"] = action.database_properties
            if not payload:
                raise HTTPException(status_code=400, detail="title or database_properties required")
            updated = _request("PATCH", f"https://api.notion.com/v1/databases/{db_id}", payload)
            return {
                "status": "success",
                "action": "update_database",
                "database_id": updated.get("id"),
                "result": updated,
            }

        if action.action == "get_page":
            if not action.page_id:
                raise HTTPException(status_code=400, detail="page_id required")
            data = _request("GET", f"https://api.notion.com/v1/pages/{action.page_id}")
            return {"status": "success", "action": "get_page", "page": data}

        if action.action == "append_blocks":
            if not action.block_id:
                raise HTTPException(status_code=400, detail="block_id required")
            if not action.children:
                raise HTTPException(status_code=400, detail="children required")
            payload = {"children": action.children}
            data = _request(
                "PATCH",
                f"https://api.notion.com/v1/blocks/{action.block_id}/children",
                payload,
            )
            return {"status": "success", "action": "append_blocks", "result": data}

        raise HTTPException(status_code=400, detail=f"Unknown action: {action.action}")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/")
def root() -> Dict[str, Any]:
    return {
        "status": "✅ API Notion Universelle",
        "endpoint": "POST /notion/universal",
        "actions": [
            "read - Lire une database",
            "create - Créer une page",
            "update - Modifier une page",
            "delete - Archiver une page",
            "search - Rechercher",
            "get_database - Infos database",
            "create_database - Créer database",
            "update_database - Modifier database",
            "get_page - Obtenir une page",
            "append_blocks - Ajouter du contenu",
        ],
    }


@app.get("/notion/test")
def test() -> Dict[str, Any]:
    return {
        "status": "ok",
        "database_id": NOTION_DATABASE_ID,
        "token_present": bool(NOTION_TOKEN),
    }


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}
