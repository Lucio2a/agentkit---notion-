import logging
import os
from typing import Any, Dict, List, Optional

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_VERSION = "2022-06-28"
ROOT_PAGE_TITLE = "Liberté financières"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("notion-writer")


class WriteInput(BaseModel):
    title: str = Field(..., min_length=1)
    content: Optional[str] = None
    target_name: Optional[str] = None


def _get_headers() -> Dict[str, str]:
    if not NOTION_TOKEN:
        raise HTTPException(status_code=500, detail="Missing NOTION_TOKEN")
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _request(
    method: str,
    url: str,
    payload: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    response = requests.request(
        method,
        url,
        headers=_get_headers(),
        json=payload,
        params=params,
        timeout=30,
    )
    if not response.ok:
        detail = f"Notion API error ({response.status_code}): {response.text}"
        logger.error("Notion API request failed: %s", detail)
        raise HTTPException(status_code=response.status_code, detail=detail)
    return response.json()


def _paginate_search(query: str, object_type: str) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    payload: Dict[str, Any] = {"query": query, "filter": {"property": "object", "value": object_type}}
    while True:
        data = _request("POST", "https://api.notion.com/v1/search", payload)
        results.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        payload["start_cursor"] = data.get("next_cursor")
    return results


def _get_page_title(page: Dict[str, Any]) -> str:
    properties = page.get("properties", {})
    for prop_data in properties.values():
        if prop_data.get("type") == "title":
            return "".join(part.get("plain_text", "") for part in prop_data.get("title", []))
    return ""


def _find_root_page() -> Dict[str, Any]:
    pages = _paginate_search(ROOT_PAGE_TITLE, "page")
    for page in pages:
        if _get_page_title(page) == ROOT_PAGE_TITLE:
            return page
    raise HTTPException(status_code=404, detail=f'Root page "{ROOT_PAGE_TITLE}" not found')


def _paginate_block_children(block_id: str) -> List[Dict[str, Any]]:
    children: List[Dict[str, Any]] = []
    url = f"https://api.notion.com/v1/blocks/{block_id}/children"
    params: Dict[str, Any] = {}
    while True:
        data = _request("GET", url, params=params or None)
        children.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        params = {"start_cursor": data.get("next_cursor")}
    return children


def _list_child_databases(page_id: str) -> Dict[str, Dict[str, Any]]:
    databases: Dict[str, Dict[str, Any]] = {}
    for child in _paginate_block_children(page_id):
        if child.get("type") == "child_database":
            title = child.get("child_database", {}).get("title", "")
            databases[title] = child
    return databases


def _build_children(content: Optional[str]) -> Optional[List[Dict[str, Any]]]:
    if not content:
        return None
    return [
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": content}}],
            },
        }
    ]


def _get_database_title_property(database_id: str) -> str:
    data = _request("GET", f"https://api.notion.com/v1/databases/{database_id}")
    for name, prop in data.get("properties", {}).items():
        if prop.get("type") == "title":
            return name
    raise HTTPException(status_code=500, detail="Database has no title property")


def _create_page_in_database(database_id: str, title: str, content: Optional[str]) -> Dict[str, Any]:
    title_property = _get_database_title_property(database_id)
    payload: Dict[str, Any] = {
        "parent": {"database_id": database_id},
        "properties": {
            title_property: {
                "title": [{"type": "text", "text": {"content": title}}],
            }
        },
    }
    children = _build_children(content)
    if children:
        payload["children"] = children
    return _request("POST", "https://api.notion.com/v1/pages", payload)


def _create_child_page(parent_page_id: str, title: str, content: Optional[str]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "parent": {"page_id": parent_page_id},
        "properties": {
            "title": {"title": [{"type": "text", "text": {"content": title}}]}
        },
    }
    children = _build_children(content)
    if children:
        payload["children"] = children
    return _request("POST", "https://api.notion.com/v1/pages", payload)


@app.post("/write")
def write_note(input_data: WriteInput) -> Dict[str, str]:
    logger.info(
        "Write request title=%s target_name=%s has_content=%s",
        input_data.title,
        input_data.target_name,
        bool(input_data.content),
    )
    root_page = _find_root_page()
    root_page_id = root_page.get("id")
    if not root_page_id:
        raise HTTPException(status_code=500, detail="Root page missing id")

    target_database_id: Optional[str] = None
    if input_data.target_name:
        child_databases = _list_child_databases(root_page_id)
        target = child_databases.get(input_data.target_name)
        if target:
            target_database_id = target.get("id")

    if target_database_id:
        created = _create_page_in_database(target_database_id, input_data.title, input_data.content)
    else:
        created = _create_child_page(root_page_id, input_data.title, input_data.content)

    return {
        "status": "ok",
        "page_id": created.get("id", ""),
        "page_url": created.get("url", ""),
    }
    children = _build_children(content)
    if children:
        payload["children"] = children
    return _request("POST", "https://api.notion.com/v1/pages", payload)


def _create_child_page(parent_page_id: str, title: str, content: Optional[str]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "parent": {"page_id": parent_page_id},
        "properties": {
            "title": {"title": [{"type": "text", "text": {"content": title}}]}
        },
    }
    children = _build_children(content)
    if children:
        payload["children"] = children
    return _request("POST", "https://api.notion.com/v1/pages", payload)


@app.post("/write")
def write_note(input_data: WriteInput) -> Dict[str, str]:
    logger.info(
        "Write request title=%s target_name=%s has_content=%s",
        input_data.title,
        input_data.target_name,
        bool(input_data.content),
    )
    root_page = _find_root_page()
    root_page_id = root_page.get("id")
    if not root_page_id:
        raise HTTPException(status_code=500, detail="Root page missing id")

    target_database_id: Optional[str] = None
    if input_data.target_name:
        child_databases = _list_child_databases(root_page_id)
        target = child_databases.get(input_data.target_name)
        if target:
            target_database_id = target.get("id")

    if target_database_id:
        created = _create_page_in_database(target_database_id, input_data.title, input_data.content)
    else:
        created = _create_child_page(root_page_id, input_data.title, input_data.content)


@app.get("/read")
def read_root() -> Dict[str, Any]:
    logger.info("Read request for root page")
    root_page = _find_root_page()
    root_page_id = root_page.get("id")
    if not root_page_id:
        raise HTTPException(status_code=500, detail="Root page missing id")
    child_databases = _list_child_databases(root_page_id)
    return {
        "status": "ok",
        "root": {
            "id": root_page_id,
            "title": _get_page_title(root_page),
            "type": "page",
        },
        "children": [
            {"id": db.get("id", ""), "title": name, "type": "database"}
            for name, db in child_databases.items()
        ],
    return {
        "status": "ok",
        "page_id": created.get("id", ""),
        "page_url": created.get("url", ""),
    }


@app.get("/read")
def read_root() -> Dict[str, Any]:
    logger.info("Read request for root page")
    root_page = _find_root_page()
    root_page_id = root_page.get("id")
    if not root_page_id:
        raise HTTPException(status_code=500, detail="Root page missing id")
    child_databases = _list_child_databases(root_page_id)
    response = {
        "status": "ok",
        "root": {
            "id": root_page_id,
            "title": _get_page_title(root_page),
            "type": "page",
        },
        "children": [
            {"id": db.get("id", ""), "title": name, "type": "database"}
            for name, db in child_databases.items()
        ],
    }
    return response
