import logging
import os
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_VERSION = "2022-06-28"
ROOT_PAGE_TITLE = "Liberté financières"
ROOT_PAGE_ID = os.getenv("ROOT_PAGE_ID", "").strip()

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


def _request_raw(
    method: str,
    url: str,
    payload: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> requests.Response:
    return requests.request(
        method,
        url,
        headers=_get_headers(),
        json=payload,
        params=params,
        timeout=30,
    )


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
        data = _request("GET", url, payload=None, params=params or None)
        children.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        params = {"start_cursor": data.get("next_cursor")}
    return children


def _paginate_database_pages(database_id: str, page_size: int = 100) -> List[Dict[str, Any]]:
    pages: List[Dict[str, Any]] = []
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    payload: Dict[str, Any] = {"page_size": min(page_size, 100)}
    while True:
        data = _request("POST", url, payload if payload else None)
        pages.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        payload = {"start_cursor": data.get("next_cursor"), "page_size": min(page_size, 100)}
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
    name_property = properties.get("Name")
    if isinstance(name_property, dict) and name_property.get("type") == "title":
        title_text = _extract_plain_text(name_property.get("title", []))
        if title_text:
            return title_text
    for prop_data in properties.values():
        if prop_data.get("type") == "title":
            title_text = _extract_plain_text(prop_data.get("title", []))
            if title_text:
                return title_text
    return "Untitled"


def _get_database_title(database: Dict[str, Any]) -> str:
    title = _extract_plain_text(database.get("title", []))
    return title or "Untitled"


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


def _build_parent_info(parent: Dict[str, Any]) -> Optional[Dict[str, str]]:
    parent_type = parent.get("type") if isinstance(parent, dict) else None
    if not parent_type:
        return None
    parent_id = parent.get(parent_type)
    if not parent_id:
        return None
    return {"type": parent_type, "id": parent_id}


def _format_notion_url(notion_id: str, fallback_url: Optional[str] = None) -> str:
    if fallback_url:
        return fallback_url
    normalized = notion_id.replace("-", "")
    return f"https://www.notion.so/{normalized}"


def _parse_notion_error(response: requests.Response) -> Tuple[Optional[str], str]:
    try:
        payload = response.json()
    except ValueError:
        return None, response.text
    return payload.get("code"), payload.get("message", response.text)


def _get_root_page_id_for_catalog() -> str:
    if ROOT_PAGE_ID:
        return ROOT_PAGE_ID
    root_page = _find_root_page()
    root_page_id = root_page.get("id")
    if not root_page_id:
        raise HTTPException(status_code=500, detail="Root page missing id")
    return root_page_id


def _scan_workspace(root_page_id: str) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    databases: Dict[str, Dict[str, Any]] = {}
    pages: Dict[str, Dict[str, Any]] = {}
    block_queue = [root_page_id]
    seen_block_ids = set()
    database_queue: List[str] = []
    seen_database_pages = set()

    while block_queue or database_queue:
        while block_queue:
            block_id = block_queue.pop()
            if not block_id or block_id in seen_block_ids:
                continue
            seen_block_ids.add(block_id)
            for block in _paginate_block_children(block_id):
                block_type = block.get("type")
                if block_type == "child_database":
                    database_id = block.get("id", "")
                    if database_id:
                        parent_info = _build_parent_info(block.get("parent", {}))
                        title = block.get("child_database", {}).get("title") or "Untitled"
                        existing = databases.get(database_id, {})
                        databases[database_id] = {
                            "id": database_id,
                            "title": title or existing.get("title") or "Untitled",
                            "parent": parent_info or existing.get("parent"),
                        }
                        if database_id not in seen_database_pages:
                            database_queue.append(database_id)
                if block_type == "child_page":
                    page_id = block.get("id", "")
                    if page_id:
                        parent_info = _build_parent_info(block.get("parent", {}))
                        pages.setdefault(
                            page_id,
                            {
                                "id": page_id,
                                "title": block.get("child_page", {}).get("title") or "Untitled",
                                "parent": parent_info,
                            },
                        )
                        block_queue.append(page_id)
                if block.get("has_children"):
                    child_id = block.get("id")
                    if child_id:
                        block_queue.append(child_id)

        if database_queue:
            database_id = database_queue.pop()
            if database_id in seen_database_pages:
                continue
            seen_database_pages.add(database_id)
            try:
                database_pages = _paginate_database_pages(database_id, page_size=50)
            except HTTPException as exc:
                if exc.status_code in {403, 404}:
                    logger.info("Skipping database %s pages due to access error", database_id)
                    continue
                raise
            for page in database_pages:
                page_id = page.get("id", "")
                if not page_id:
                    continue
                parent_info = _build_parent_info(page.get("parent", {}))
                pages.setdefault(
                    page_id,
                    {
                        "id": page_id,
                        "title": extract_title(page.get("properties", {})),
                        "parent": parent_info,
                    },
                )
                block_queue.append(page_id)

    return databases, pages


def _get_database_access(database_id: str) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str], str]:
    response = _request_raw("GET", f"https://api.notion.com/v1/databases/{database_id}")
    if response.ok:
        return True, response.json(), None, ""
    error_code, error_message = _parse_notion_error(response)
    return False, None, error_code, error_message


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


def _build_database_catalog(root_page_id: str) -> Dict[str, Any]:
    databases, _pages = _scan_workspace(root_page_id)
    database_entries: List[Dict[str, Any]] = []
    authorized_count = 0
    unauthorized_count = 0
    error_count = 0
    for database_id, stub in databases.items():
        authorized, data, error_code, error_message = _get_database_access(database_id)
        if authorized and data:
            parent_info = _build_parent_info(data.get("parent", {})) or stub.get("parent")
            database_entries.append(
                {
                    "id": database_id,
                    "title": _get_database_title(data),
                    "parent": parent_info,
                    "notion_url": _format_notion_url(database_id, data.get("url")),
                    "authorized": True,
                }
            )
            authorized_count += 1
        else:
            entry: Dict[str, Any] = {
                "id": database_id,
                "title": stub.get("title") or "Untitled",
                "parent": stub.get("parent"),
                "notion_url": _format_notion_url(database_id),
                "authorized": False,
            }
            if error_code:
                entry["error_code"] = error_code
            if error_message:
                entry["error_message"] = error_message
            database_entries.append(entry)
            unauthorized_count += 1
            error_count += 1

    logger.info(
        "Catalog databases scanned=%s authorized=%s unauthorized=%s errors=%s",
        len(database_entries),
        authorized_count,
        unauthorized_count,
        error_count,
    )
    return {
        "status": "ok",
        "root_page_id": root_page_id,
        "total": len(database_entries),
        "authorized": authorized_count,
        "unauthorized": unauthorized_count,
        "databases": database_entries,
    }


def _build_pages_catalog(root_page_id: str) -> Dict[str, Any]:
    _databases, pages = _scan_workspace(root_page_id)
    page_entries = []
    for page_id, page in pages.items():
        page_entries.append(
            {
                "id": page_id,
                "title": page.get("title") or "Untitled",
                "parent": page.get("parent"),
                "url": _format_notion_url(page_id),
            }
        )
    logger.info("Catalog pages scanned=%s", len(page_entries))
    return {
        "status": "ok",
        "root_page_id": root_page_id,
        "total": len(page_entries),
        "pages": page_entries,
    }


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


@app.get(
    "/catalog/databases",
    tags=["catalog"],
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "status": "ok",
                        "root_page_id": "root-page-id",
                        "total": 1,
                        "authorized": 1,
                        "unauthorized": 0,
                        "databases": [
                            {
                                "id": "database-id",
                                "title": "Vos objectifs",
                                "parent": {"type": "page_id", "id": "parent-page-id"},
                                "notion_url": "https://www.notion.so/databaseid",
                                "authorized": True,
                            }
                        ],
                    }
                }
            }
        }
    },
)
def catalog_databases() -> Dict[str, Any]:
    logger.info("Catalog databases request")
    root_page_id = _get_root_page_id_for_catalog()
    return _build_database_catalog(root_page_id)


@app.get(
    "/catalog/pages",
    tags=["catalog"],
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "status": "ok",
                        "root_page_id": "root-page-id",
                        "total": 2,
                        "pages": [
                            {
                                "id": "page-id",
                                "title": "Project Alpha",
                                "parent": {"type": "page_id", "id": "parent-page-id"},
                                "url": "https://www.notion.so/pageid",
                            }
                        ],
                    }
                }
            }
        }
    },
)
def catalog_pages() -> Dict[str, Any]:
    logger.info("Catalog pages request")
    root_page_id = _get_root_page_id_for_catalog()
    return _build_pages_catalog(root_page_id)


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
    response = _request_raw("GET", f"https://api.notion.com/v1/databases/{validated_id}")
    if response.status_code in {403, 404}:
        raise HTTPException(status_code=403, detail="Database access forbidden")
    if not response.ok:
        detail = f"Notion API error ({response.status_code}): {response.text}"
        logger.error("Notion API request failed: %s", detail)
        raise HTTPException(status_code=response.status_code, detail=detail)
    try:
        entries = _read_database_entries(validated_id, limit=50)
    except HTTPException as exc:
        if exc.status_code in {403, 404}:
            raise HTTPException(status_code=403, detail="Database access forbidden") from exc
        raise
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
