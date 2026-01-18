import logging
import os
import re
import uuid
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


def _paginate_database_pages(database_id: str) -> List[Dict[str, Any]]:
    pages: List[Dict[str, Any]] = []
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    payload: Dict[str, Any] = {}
    while True:
        data = _request("POST", url, payload if payload else None)
        pages.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        payload = {"start_cursor": data.get("next_cursor")}
    return pages


def _list_child_databases(page_id: str) -> Dict[str, Dict[str, Any]]:
    databases: Dict[str, Dict[str, Any]] = {}
    for child in _paginate_block_children(page_id):
        if child.get("type") == "child_database":
            title = child.get("child_database", {}).get("title", "")
            databases[title] = child
    return databases


def _extract_plain_text(rich_text: List[Dict[str, Any]]) -> str:
    return "".join(part.get("plain_text", "") for part in rich_text)


def extract_title(properties: Dict[str, Any]) -> str:
    for prop_data in properties.values():
        if prop_data.get("type") == "title":
            return _extract_plain_text(prop_data.get("title", []))
    return ""


def _get_database_title(database: Dict[str, Any]) -> str:
    return _extract_plain_text(database.get("title", []))


def _find_database_by_title(title: str) -> Dict[str, Any]:
    databases = _paginate_search(title, "database")
    for database in databases:
        if _get_database_title(database) == title:
            return database
    raise HTTPException(status_code=404, detail=f'Database "{title}" not found')


def _serialize_block(block: Dict[str, Any]) -> Dict[str, Any]:
    block_type = block.get("type", "")
    result: Dict[str, Any] = {"id": block.get("id", ""), "type": block_type}
    if block_type == "child_page":
        result["title"] = block.get("child_page", {}).get("title", "")
        return result
    if block_type == "child_database":
        result["title"] = block.get("child_database", {}).get("title", "")
        return result
    block_value = block.get(block_type, {})
    if isinstance(block_value, dict):
        if "rich_text" in block_value:
            text = _extract_plain_text(block_value.get("rich_text", []))
            if text:
                result["text"] = text
        if "title" in block_value and isinstance(block_value.get("title"), list):
            title = _extract_plain_text(block_value.get("title", []))
            if title:
                result["title"] = title
    return result


def _build_block_tree(block: Dict[str, Any]) -> Dict[str, Any]:
    block_type = block.get("type", "")
    node = _serialize_block(block)
    children: List[Dict[str, Any]] = []
    if block.get("has_children"):
        children.extend(
            [_build_block_tree(child) for child in _paginate_block_children(block.get("id", ""))]
        )
    if block_type == "child_database":
        database_id = block.get("id", "")
        for page in _paginate_database_pages(database_id):
            page_id = page.get("id", "")
            page_node: Dict[str, Any] = {
                "id": page_id,
                "type": "page",
                "title": _get_page_title(page),
            }
            page_children = [
                _build_block_tree(child) for child in _paginate_block_children(page_id)
            ]
            if page_children:
                page_node["children"] = page_children
            children.append(page_node)
    if children:
        node["children"] = children
    return node


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


def _scan_databases_recursively(block_id: str) -> List[Dict[str, Any]]:
    if not block_id:
        return []
    databases: Dict[str, Dict[str, Any]] = {}
    for block in _paginate_block_children(block_id):
        if block.get("type") == "child_database":
            database_id = block.get("id", "")
            title = block.get("child_database", {}).get("title", "")
            if database_id:
                databases[database_id] = {"id": database_id, "title": title}
        if block.get("has_children"):
            for database in _scan_databases_recursively(block.get("id", "")):
                databases[database["id"]] = database
    return list(databases.values())


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


def _validate_database_id(database_id: str) -> str:
    candidate = database_id.strip()
    if not candidate:
        raise HTTPException(status_code=400, detail="database_id must be provided")
    if re.fullmatch(r"[0-9a-fA-F-]{32,36}", candidate) is None:
        raise HTTPException(status_code=400, detail="database_id must resemble a UUID")
    try:
        uuid.UUID(candidate.replace("-", ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="database_id must resemble a UUID") from exc
    return candidate


def _read_database_entries(database_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    payload: Dict[str, Any] = {"page_size": min(limit, 50)}
    while len(results) < limit:
        data = _request("POST", url, payload)
        for page in data.get("results", []):
            properties = page.get("properties", {})
            results.append(
                {
                    "id": page.get("id", ""),
                    "title": extract_title(properties),
                    "created_time": page.get("created_time", ""),
                    "last_edited_time": page.get("last_edited_time", ""),
                }
            )
            if len(results) >= limit:
                break
        if not data.get("has_more") or len(results) >= limit:
            break
        payload = {"page_size": min(limit - len(results), 50), "start_cursor": data.get("next_cursor")}
    return results


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


@app.get("/read")
def read_root() -> Dict[str, Any]:
    logger.info("Read request for root page")
    root_page = _find_root_page()
    root_page_id = root_page.get("id")
    if not root_page_id:
        raise HTTPException(status_code=500, detail="Root page missing id")
    content = [
        _build_block_tree(child) for child in _paginate_block_children(root_page_id)
    ]
    response = {
        "status": "ok",
        "root": {
            "id": root_page_id,
            "title": _get_page_title(root_page),
            "type": "page",
        },
        "content": content,
    }
    return response


@app.get("/diagnostic")
def diagnostic_databases() -> Dict[str, Any]:
    logger.info("Diagnostic request for Notion databases")
    root_page = _find_root_page()
    root_page_id = root_page.get("id")
    if not root_page_id:
        raise HTTPException(status_code=500, detail="Root page missing id")

    databases = _scan_databases_recursively(root_page_id)
    unauthorized_databases: List[Dict[str, str]] = []
    accessible_databases: List[Dict[str, str]] = []

    for database in databases:
        database_id = database.get("id", "")
        if not database_id:
            continue
        try:
            _request("GET", f"https://api.notion.com/v1/databases/{database_id}")
            accessible_databases.append(database)
        except HTTPException as exc:
            if exc.status_code in {400, 403}:
                unauthorized_databases.append(database)
            else:
                raise

    return {
        "status": "ok",
        "root_page_id": root_page_id,
        "unauthorized_databases": unauthorized_databases,
        "accessible_databases": accessible_databases,
    }


@app.get("/read/database/{database_id}")
def read_database(database_id: str) -> Dict[str, Any]:
    logger.info("Read request for database %s", database_id)
    validated_id = _validate_database_id(database_id)
    _request("GET", f"https://api.notion.com/v1/databases/{validated_id}")
    entries = _read_database_entries(validated_id, limit=50)
    return {"status": "ok", "database_id": validated_id, "entries": entries}


@app.get("/read/quicknote")
def read_quicknote() -> Dict[str, Any]:
    logger.info("Read request for QuickNote database")
    database_id = os.getenv("QUICKNOTES_DATABASE_ID", "").strip()
    if not database_id:
        raise HTTPException(
            status_code=404,
            detail="Missing QUICKNOTES_DATABASE_ID environment variable for QuickNote database",
        )
    validated_id = _validate_database_id(database_id)
    _request("GET", f"https://api.notion.com/v1/databases/{validated_id}")
    entries = _read_database_entries(validated_id, limit=50)
    return {"status": "ok", "database_id": validated_id, "entries": entries}
