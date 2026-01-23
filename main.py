import logging
import os
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

import requests
from fastapi import Body, FastAPI, HTTPException
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


class CommandInput(BaseModel):
    action: str = Field(..., examples=["update_page"])
    page_id: Optional[str] = Field(default=None, examples=["a1b2c3d4-5678-90ab-cdef-222222222222"])
    props: Optional[Dict[str, Any]] = Field(
        default=None,
        examples=[
            {
                "Name": "Titre de la page",
                "Done": True,
                "Status": "Done",
                "Tags": ["Crypto", "Trading"],
                "Date": "2026-01-23",
                "Number": 12.5,
                "Relation": ["PAGE_ID_1", "PAGE_ID_2"],
            }
        ],
    )
    content_append: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        examples=[[{"type": "paragraph", "text": "Texte à ajouter"}]],
    )
    content_replace: bool = Field(default=False)
    content_delete_all: bool = Field(default=False)

    class Config:
        json_schema_extra = {
            "example": {
                "action": "update_page",
                "page_id": "a1b2c3d4-5678-90ab-cdef-222222222222",
                "props": {
                    "Name": "Titre de la page",
                    "Done": True,
                    "Status": "Done",
                    "Tags": ["Crypto", "Trading"],
                    "Date": "2026-01-23",
                    "Number": 12.5,
                    "Relation": ["PAGE_ID_1", "PAGE_ID_2"],
                },
                "content_append": [{"type": "paragraph", "text": "Texte à ajouter"}],
                "content_replace": False,
                "content_delete_all": False,
            }
        }


class ResolveInput(BaseModel):
    query: str = Field(..., min_length=1, examples=["Journal"])
    kind: str = Field(..., examples=["database", "page"])


class DatabaseQueryInput(BaseModel):
    database_id: str = Field(..., examples=["d21d4e8b-1b2c-4c6f-9a9c-111111111111"])
    filter: Optional[Dict[str, Any]] = None
    sorts: Optional[List[Dict[str, Any]]] = None
    page_size: int = Field(default=20, ge=1, le=100)
    cursor: Optional[str] = Field(default=None)


class SelfTestReport(BaseModel):
    status: str
    checks: List[Dict[str, Any]]
    notion_errors: List[Dict[str, Any]]


class WriteInput(BaseModel):
    target: Optional[str] = Field(
        default=None,
        examples=["database", "page"],
        description="Target type for the write request (database or page).",
    )
    title: Optional[str] = Field(default=None, min_length=1, examples=["Nouvelle page"])
    content: Optional[str] = Field(default=None, examples=["Contenu de la page"])
    target_name: Optional[str] = Field(default=None, examples=["Objectifs"])
    database_id: Optional[str] = Field(default=None, examples=["d21d4e8b-1b2c-4c6f-9a9c-111111111111"])
    page_id: Optional[str] = Field(default=None, examples=["a1b2c3d4-5678-90ab-cdef-222222222222"])
    properties: Optional[Dict[str, Any]] = Field(
        default=None,
        examples=[
            {
                "status": "In Progress",
                "checkbox": True,
                "date": "2024-10-15",
                "number": 3,
                "text": "Texte",
            }
        ],
    )

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "name": "write_to_database",
                    "summary": "Write to a database",
                    "value": {
                        "target": "database",
                        "database_id": "d21d4e8b-1b2c-4c6f-9a9c-111111111111",
                        "title": "Nouvelle page",
                        "properties": {"Date": "2026-01-19", "Tags": ["Journal"]},
                        "content": "Message dans la note",
                    },
                },
                {
                    "name": "write_to_page",
                    "summary": "Create a child page",
                    "value": {
                        "target": "page",
                        "page_id": "a1b2c3d4-5678-90ab-cdef-222222222222",
                        "title": "Nouvelle page",
                        "content": "Premier paragraphe\nSecond paragraphe",
                    },
                },
            ],
        }


class WriteDatabaseInput(BaseModel):
    title: str = Field(..., min_length=1, examples=["Titre de la page"])
    properties: Dict[str, Any] = Field(
        default_factory=dict,
        examples=[
            {
                "status": "Todo",
                "checkbox": True,
                "date": "2024-10-15",
                "number": 7,
                "text": "Notes",
            }
        ],
    )

    class Config:
        json_schema_extra = {
            "example": {
                "title": "Titre de la page",
                "properties": {
                    "status": "Todo",
                    "checkbox": True,
                    "date": "2024-10-15",
                    "number": 7,
                    "text": "Notes",
                },
            }
        }


class AppendPageInput(BaseModel):
    content: str = Field(..., min_length=1, examples=["Premier paragraphe\nSecond paragraphe"])

    class Config:
        json_schema_extra = {
            "example": {"content": "Premier paragraphe\nSecond paragraphe"}
        }


class UpdatePageInput(BaseModel):
    properties: Dict[str, Any] = Field(
        default_factory=dict,
        examples=[
            {
                "status": "Done",
                "checkbox": True,
                "date": "2024-10-20",
                "text": "Texte mis à jour",
            }
        ],
    )

    class Config:
        json_schema_extra = {
            "example": {
                "properties": {
                    "status": "Done",
                    "checkbox": True,
                    "date": "2024-10-20",
                    "text": "Texte mis à jour",
                }
            }
        }


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


def _request_with_log(
    method: str,
    url: str,
    request_log: List[Dict[str, Any]],
    payload: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    request_log.append(
        {
            "method": method,
            "url": url,
            "payload": payload,
            "params": params,
        }
    )
    return _request(method, url, payload=payload, params=params)


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
    params: Dict[str, Any] = {"page_size": 100}
    while True:
        data = _request("GET", url, params=params)
        children.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        params = {"page_size": 100, "start_cursor": data.get("next_cursor")}
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
    lines = [line for line in content.splitlines() if line.strip()]
    if not lines:
        return None
    return [
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": line}}],
            },
        }
        for line in lines
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
    data = _get_database_schema(database_id)
    return _get_database_title_property_from_schema(data)


def _get_database_title_property_from_schema(database: Dict[str, Any]) -> str:
    for name, prop in database.get("properties", {}).items():
        if prop.get("type") == "title":
            return name
    raise HTTPException(status_code=500, detail="Database has no title property")


def _get_database_schema(database_id: str) -> Dict[str, Any]:
    return _request("GET", f"https://api.notion.com/v1/databases/{database_id}")


def _get_page_details(page_id: str) -> Dict[str, Any]:
    return _request("GET", f"https://api.notion.com/v1/pages/{page_id}")


def _get_database_schema_for_page(
    page_id: str,
    request_log: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    if request_log is None:
        page = _get_page_details(page_id)
    else:
        page = _request_with_log(
            "GET", f"https://api.notion.com/v1/pages/{page_id}", request_log
        )
    parent = page.get("parent", {})
    if parent.get("type") == "database_id" and parent.get("database_id"):
        if request_log is None:
            database = _get_database_schema(parent["database_id"])
        else:
            database = _request_with_log(
                "GET", f"https://api.notion.com/v1/databases/{parent['database_id']}", request_log
            )
        return page, database
    return page, None


def _map_property_value(
    prop_type: str, value: Any, options: Optional[List[str]] = None
) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if prop_type == "status":
        if options and str(value) not in options:
            return None
        return {"status": {"name": str(value)}}
    if prop_type == "select":
        if options and str(value) not in options:
            return None
        return {"select": {"name": str(value)}}
    if prop_type == "multi_select":
        if isinstance(value, list):
            names = [str(item) for item in value]
        else:
            names = [str(value)]
        if options:
            names = [name for name in names if name in options]
        if not names:
            return None
        return {"multi_select": [{"name": name} for name in names]}
    if prop_type == "checkbox":
        return {"checkbox": value if isinstance(value, bool) else bool(value)}
    if prop_type == "date":
        if isinstance(value, dict):
            return {"date": value}
        date_value = str(value)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_value) is None:
            return None
        return {"date": {"start": date_value}}
    if prop_type == "number":
        return {"number": value}
    if prop_type == "rich_text":
        return {"rich_text": [{"type": "text", "text": {"content": str(value)}}]}
    if prop_type == "title":
        return {"title": [{"type": "text", "text": {"content": str(value)}}]}
    if prop_type == "url":
        return {"url": str(value)}
    if prop_type == "email":
        return {"email": str(value)}
    if prop_type == "phone_number":
        return {"phone_number": str(value)}
    return None


def _build_property_payload(
    schema_properties: Dict[str, Any],
    input_properties: Dict[str, Any],
    context: str,
) -> Tuple[Dict[str, Any], List[str], List[str]]:
    payload: Dict[str, Any] = {}
    accepted: List[str] = []
    rejected: List[str] = []
    for name, value in input_properties.items():
        schema = schema_properties.get(name)
        if not schema:
            rejected.append(name)
            logger.warning("Ignoring unknown property %s for %s", name, context)
            continue
        prop_type = schema.get("type")
        if not prop_type:
            rejected.append(name)
            logger.warning("Ignoring property %s with missing type for %s", name, context)
            continue
        options = None
        if prop_type in {"select", "multi_select", "status"}:
            options = [
                option.get("name", "")
                for option in schema.get(prop_type, {}).get("options", [])
                if option.get("name")
            ]
        mapped = _map_property_value(prop_type, value, options)
        if mapped is not None:
            payload[name] = mapped
            accepted.append(name)
        else:
            rejected.append(name)
            logger.warning(
                "Ignoring property %s with unsupported value for %s",
                name,
                context,
            )
    return payload, accepted, rejected


def _extract_schema_options(schema: Dict[str, Any], prop_type: str) -> List[str]:
    options = schema.get(prop_type, {}).get("options", [])
    return [option.get("name", "") for option in options if option.get("name")]


def _map_property_value_strict(
    prop_name: str,
    prop_schema: Dict[str, Any],
    value: Any,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    prop_type = prop_schema.get("type")
    if not prop_type:
        return None, "missing_type"
    if prop_type == "rollup":
        return None, "rollup_not_supported"
    if prop_type in {"select", "multi_select", "status"}:
        options = _extract_schema_options(prop_schema, prop_type)
        if not options:
            return None, "missing_options"
        if prop_type == "select":
            if str(value) not in options:
                return None, "invalid_option"
            return {"select": {"name": str(value)}}, None
        if prop_type == "status":
            if str(value) not in options:
                return None, "invalid_option"
            return {"status": {"name": str(value)}}, None
        if prop_type == "multi_select":
            if not isinstance(value, list):
                return None, "expected_list"
            names = [str(item) for item in value]
            invalid = [name for name in names if name not in options]
            if invalid:
                return None, "invalid_option"
            return {"multi_select": [{"name": name} for name in names]}, None
    if prop_type == "title":
        return {"title": [{"type": "text", "text": {"content": str(value)}}]}, None
    if prop_type == "rich_text":
        return {"rich_text": [{"type": "text", "text": {"content": str(value)}}]}, None
    if prop_type == "checkbox":
        return {"checkbox": bool(value)}, None
    if prop_type == "date":
        date_value = str(value)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_value) is None:
            return None, "invalid_date"
        return {"date": {"start": date_value}}, None
    if prop_type == "number":
        if not isinstance(value, (int, float)):
            return None, "invalid_number"
        return {"number": value}, None
    if prop_type == "relation":
        if not isinstance(value, list):
            return None, "expected_list"
        relation_items = []
        for relation_id in value:
            if not isinstance(relation_id, str) or not relation_id.strip():
                return None, "invalid_relation_id"
            relation_items.append({"id": relation_id})
        return {"relation": relation_items}, None
    if prop_type == "url":
        return {"url": str(value)}, None
    if prop_type == "email":
        return {"email": str(value)}, None
    if prop_type == "phone_number":
        return {"phone_number": str(value)}, None
    return None, "unsupported_type"


def _map_properties_from_schema(
    schema_properties: Dict[str, Any],
    input_properties: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    payload: Dict[str, Any] = {}
    errors: List[Dict[str, Any]] = []
    for name, value in input_properties.items():
        prop_schema = schema_properties.get(name)
        if not prop_schema:
            errors.append({"property": name, "reason": "unknown_property"})
            continue
        mapped, error = _map_property_value_strict(name, prop_schema, value)
        if error:
            errors.append({"property": name, "reason": error})
            continue
        if mapped is not None:
            payload[name] = mapped
    return payload, errors


def _create_page_in_database(
    database_id: str,
    title: str,
    content: Optional[str],
    properties: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    database = _get_database_schema(database_id)
    title_property = _get_database_title_property_from_schema(database)
    payload_properties: Dict[str, Any] = {
        title_property: {
            "title": [{"type": "text", "text": {"content": title}}],
        }
    }
    if properties:
        mapped_properties, accepted, rejected = _build_property_payload(
            database.get("properties", {}),
            properties,
            f"database {database_id}",
        )
        if accepted or rejected:
            logger.info(
                "Mapped properties for database_id=%s accepted=%s rejected=%s",
                database_id,
                accepted,
                rejected,
            )
        payload_properties.update(mapped_properties)
    payload: Dict[str, Any] = {
        "parent": {"database_id": database_id},
        "properties": payload_properties,
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


def _append_blocks_to_page(page_id: str, content: str) -> Dict[str, Any]:
    children = _build_children(content)
    if not children:
        raise HTTPException(status_code=400, detail="Content must include at least one paragraph")
    payload: Dict[str, Any] = {"children": children}
    return _request("PATCH", f"https://api.notion.com/v1/blocks/{page_id}/children", payload)


def _build_blocks_from_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    for item in items:
        block_type = item.get("type")
        if block_type != "paragraph":
            raise HTTPException(status_code=400, detail=f"Unsupported block type: {block_type}")
        text = item.get("text", "")
        if not isinstance(text, str) or not text.strip():
            raise HTTPException(status_code=400, detail="Paragraph text must be a non-empty string")
        blocks.append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}}]},
            }
        )
    if not blocks:
        raise HTTPException(status_code=400, detail="content_append must include at least one block")
    return blocks


def _delete_all_page_blocks(page_id: str, request_log: Optional[List[Dict[str, Any]]] = None) -> None:
    children = _paginate_block_children(page_id)
    for child in children:
        block_id = child.get("id")
        if not block_id:
            continue
        url = f"https://api.notion.com/v1/blocks/{block_id}"
        if request_log is not None:
            request_log.append({"method": "DELETE", "url": url, "payload": None, "params": None})
        response = _request_raw("DELETE", url)
        if not response.ok:
            error_code, error_message = _parse_notion_error(response)
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Notion API error ({error_code}): {error_message}",
            )


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


def _validate_page_id(page_id: str) -> str:
    candidate = page_id.strip()
    if not candidate:
        raise HTTPException(status_code=400, detail="page_id must be provided")
    if re.fullmatch(r"[0-9a-fA-F-]{32,36}", candidate) is None:
        raise HTTPException(status_code=400, detail="page_id must resemble a UUID")
    try:
        uuid.UUID(candidate.replace("-", ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="page_id must resemble a UUID") from exc
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


def _format_success_response(
    request_log: List[Dict[str, Any]],
    result: Dict[str, Any],
) -> Dict[str, Any]:
    return {"status": "ok", "notion_requests": request_log, "result": result}


def _format_error_response(
    code: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    response = {"status": "error", "code": code, "message": message}
    if details is not None:
        response["details"] = details
    return response


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


@app.post(
    "/write/database/{database_id}",
    tags=["write"],
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {"id": "page-id", "url": "https://www.notion.so/pageid"}
                }
            }
        }
    },
)
def write_database(database_id: str, input_data: WriteDatabaseInput) -> Dict[str, str]:
    validated_id = _validate_database_id(database_id)
    logger.info(
        "Write database request database_id=%s properties=%s",
        validated_id,
        len(input_data.properties),
    )
    created = _create_page_in_database(
        validated_id,
        input_data.title,
        None,
        properties=input_data.properties,
    )
    return {"id": created.get("id", ""), "url": created.get("url", "")}


@app.post(
    "/write/page/{page_id}",
    tags=["write"],
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {"id": "page-id", "url": "https://www.notion.so/pageid"}
                }
            }
        }
    },
)
def write_page(page_id: str, input_data: AppendPageInput) -> Dict[str, str]:
    validated_id = _validate_page_id(page_id)
    logger.info("Append content request page_id=%s", validated_id)
    _append_blocks_to_page(validated_id, input_data.content)
    return {"id": validated_id, "url": _format_notion_url(validated_id)}


@app.patch(
    "/update/page/{page_id}",
    tags=["write"],
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {"id": "page-id", "url": "https://www.notion.so/pageid"}
                }
            }
        }
    },
)
def update_page(page_id: str, input_data: UpdatePageInput) -> Dict[str, str]:
    validated_id = _validate_page_id(page_id)
    logger.info("Update page request page_id=%s properties=%s", validated_id, len(input_data.properties))
    page = _request("GET", f"https://api.notion.com/v1/pages/{validated_id}")
    schema_properties = page.get("properties", {})
    mapped_properties, accepted, rejected = _build_property_payload(
        schema_properties,
        input_data.properties,
        f"page {validated_id}",
    )
    if accepted or rejected:
        logger.info(
            "Mapped properties for page_id=%s accepted=%s rejected=%s",
            validated_id,
            accepted,
            rejected,
        )
    if not mapped_properties:
        raise HTTPException(status_code=400, detail="No valid properties to update")
    payload = {"properties": mapped_properties}
    updated = _request("PATCH", f"https://api.notion.com/v1/pages/{validated_id}", payload)
    return {"id": updated.get("id", ""), "url": updated.get("url", "")}


@app.get(
    "/schema/database/{database_id}",
    tags=["schema"],
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "database_id": "database-id",
                        "properties": [
                            {"name": "Status", "type": "status", "options": ["Todo", "Done"]},
                            {"name": "Date", "type": "date"},
                            {"name": "Tags", "type": "multi_select", "options": ["Journal", "Work"]},
                        ],
                    }
                }
            }
        }
    },
)
def read_database_schema(database_id: str) -> Dict[str, Any]:
    validated_id = _validate_database_id(database_id)
    logger.info("Schema request database_id=%s", validated_id)
    database = _get_database_schema(validated_id)
    properties_list: List[Dict[str, Any]] = []
    for name, prop in database.get("properties", {}).items():
        prop_type = prop.get("type", "")
        entry: Dict[str, Any] = {"name": name, "type": prop_type}
        if prop_type == "status":
            options = prop.get("status", {}).get("options", [])
            entry["options"] = [option.get("name", "") for option in options if option.get("name")]
        if prop_type == "select":
            options = prop.get("select", {}).get("options", [])
            entry["options"] = [option.get("name", "") for option in options if option.get("name")]
        if prop_type == "multi_select":
            options = prop.get("multi_select", {}).get("options", [])
            entry["options"] = [option.get("name", "") for option in options if option.get("name")]
        properties_list.append(entry)
    return {"database_id": validated_id, "properties": properties_list}


@app.post(
    "/write",
    tags=["write"],
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "status": "ok",
                        "page_id": "page-id",
                        "page_url": "https://www.notion.so/pageid",
                    }
                }
            }
        }
    },
)
def write_note(input_data: WriteInput = Body(...)) -> Dict[str, str]:
    logger.info(
        "Write request title=%s target=%s target_name=%s has_content=%s",
        input_data.title,
        input_data.target,
        input_data.target_name,
        bool(input_data.content),
    )
    if input_data.target not in {"database", "page"}:
        raise HTTPException(
            status_code=400,
            detail='target must be provided and set to either "database" or "page"',
        )
    if input_data.database_id and input_data.page_id:
        raise HTTPException(status_code=400, detail="Provide database_id or page_id, not both")
    if input_data.target == "database":
        if not input_data.database_id:
            raise HTTPException(status_code=400, detail="database_id must be provided for database write")
        if not input_data.title or not input_data.title.strip():
            raise HTTPException(status_code=400, detail="title must be provided for database write")
        validated_id = _validate_database_id(input_data.database_id)
        created = _create_page_in_database(
            validated_id,
            input_data.title.strip(),
            input_data.content,
            properties=input_data.properties,
        )
        return {
            "status": "ok",
            "page_id": created.get("id", ""),
            "page_url": created.get("url", ""),
        }
    if input_data.target == "page":
        if not input_data.page_id:
            raise HTTPException(status_code=400, detail="page_id must be provided for page write")
        if not input_data.title or not input_data.title.strip():
            raise HTTPException(status_code=400, detail="title must be provided for page write")
        validated_id = _validate_page_id(input_data.page_id)
        created = _create_child_page(validated_id, input_data.title.strip(), input_data.content)
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


@app.get("/health", tags=["health"])
def healthcheck() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/notion/ping", tags=["health"])
def notion_ping() -> Dict[str, Any]:
    logger.info("Notion ping request")
    request_log: List[Dict[str, Any]] = []
    try:
        data = _request_with_log("GET", "https://api.notion.com/v1/users/me", request_log)
        return _format_success_response(request_log, {"user": data})
    except HTTPException as exc:
        logger.error("Notion ping failed: %s", exc.detail)
        return _format_error_response(
            "NOTION",
            "Notion ping failed",
            {"detail": exc.detail},
        )


@app.get("/schema", tags=["schema"])
def schema(database_id: str) -> Dict[str, Any]:
    validated_id = _validate_database_id(database_id)
    logger.info("Schema request database_id=%s", validated_id)
    request_log: List[Dict[str, Any]] = []
    try:
        database = _request_with_log(
            "GET", f"https://api.notion.com/v1/databases/{validated_id}", request_log
        )
        properties_list: List[Dict[str, Any]] = []
        for name, prop in database.get("properties", {}).items():
            prop_type = prop.get("type", "")
            entry: Dict[str, Any] = {"name": name, "type": prop_type}
            if prop_type in {"status", "select", "multi_select"}:
                entry["options"] = _extract_schema_options(prop, prop_type)
            properties_list.append(entry)
        return _format_success_response(
            request_log,
            {"database_id": validated_id, "properties": properties_list},
        )
    except HTTPException as exc:
        logger.error("Schema request failed: %s", exc.detail)
        return _format_error_response(
            "NOTION",
            "Failed to read database schema",
            {"detail": exc.detail},
        )


@app.post("/resolve", tags=["resolve"])
def resolve(input_data: ResolveInput) -> Dict[str, Any]:
    query = input_data.query.strip()
    kind = input_data.kind.strip().lower()
    if kind not in {"database", "page"}:
        return _format_error_response("VALIDATION", "kind must be database or page")
    root_page_id = _get_root_page_id_for_catalog()
    databases, pages = _scan_workspace(root_page_id)
    items = databases.values() if kind == "database" else pages.values()
    candidates: List[Dict[str, Any]] = []
    for item in items:
        title = (item.get("title") or "").strip()
        if not title:
            continue
        if query.lower() in title.lower():
            candidates.append(
                {
                    "id": item.get("id", ""),
                    "type": kind,
                    "title": title,
                }
            )
    candidates.sort(key=lambda entry: entry.get("title", "").lower())
    best_match = None
    for candidate in candidates:
        title = candidate.get("title", "").lower()
        if title == query.lower():
            best_match = candidate
            break
    if not best_match and candidates:
        best_match = candidates[0]
    return _format_success_response(
        [],
        {"best_match": best_match, "candidates": candidates},
    )


@app.post("/database_query", tags=["database"])
def database_query(input_data: DatabaseQueryInput) -> Dict[str, Any]:
    validated_id = _validate_database_id(input_data.database_id)
    logger.info("Database query request database_id=%s", validated_id)
    payload: Dict[str, Any] = {"page_size": min(input_data.page_size, 100)}
    if input_data.filter:
        payload["filter"] = input_data.filter
    if input_data.sorts:
        payload["sorts"] = input_data.sorts
    if input_data.cursor:
        payload["start_cursor"] = input_data.cursor
    request_log: List[Dict[str, Any]] = []
    try:
        data = _request_with_log(
            "POST",
            f"https://api.notion.com/v1/databases/{validated_id}/query",
            request_log,
            payload,
        )
        return _format_success_response(
            request_log,
            {"results": data.get("results", []), "next_cursor": data.get("next_cursor")},
        )
    except HTTPException as exc:
        logger.error("Database query failed: %s", exc.detail)
        return _format_error_response(
            "NOTION",
            "Failed to query database",
            {"detail": exc.detail},
        )


@app.post("/command", tags=["command"])
def command(input_data: CommandInput) -> Dict[str, Any]:
    logger.info(
        "Command request action=%s page_id=%s has_props=%s has_append=%s replace=%s delete_all=%s",
        input_data.action,
        input_data.page_id,
        bool(input_data.props),
        bool(input_data.content_append),
        input_data.content_replace,
        input_data.content_delete_all,
    )
    if input_data.action != "update_page":
        return _format_error_response("VALIDATION", "Unsupported action")
    if not input_data.page_id:
        return _format_error_response("VALIDATION", "page_id is required")
    validated_page_id = _validate_page_id(input_data.page_id)
    request_log: List[Dict[str, Any]] = []
    try:
        page, database = _get_database_schema_for_page(validated_page_id, request_log)
        schema_properties = (
            database.get("properties", {}) if database else page.get("properties", {})
        )
        if not schema_properties:
            return _format_error_response(
                "NOTION",
                "No schema available for page",
                {"page_id": validated_page_id},
            )
        notion_payload: Dict[str, Any] = {}
        if input_data.props:
            mapped, errors = _map_properties_from_schema(schema_properties, input_data.props)
            if errors:
                logger.info("Command validation errors: %s", errors)
                return _format_error_response(
                    "VALIDATION",
                    "Invalid properties payload",
                    {"errors": errors},
                )
            if mapped:
                notion_payload["properties"] = mapped
        if notion_payload:
            _request_with_log(
                "PATCH",
                f"https://api.notion.com/v1/pages/{validated_page_id}",
                request_log,
                notion_payload,
            )
        if input_data.content_delete_all or input_data.content_replace:
            _delete_all_page_blocks(validated_page_id, request_log=request_log)
        if input_data.content_append:
            blocks = _build_blocks_from_items(input_data.content_append)
            _request_with_log(
                "PATCH",
                f"https://api.notion.com/v1/blocks/{validated_page_id}/children",
                request_log,
                {"children": blocks},
            )
        return _format_success_response(
            request_log,
            {"page_id": validated_page_id, "page_url": _format_notion_url(validated_page_id)},
        )
    except HTTPException as exc:
        logger.error("Command failed: %s", exc.detail)
        code = "VALIDATION" if exc.status_code in {400, 422} else "NOTION"
        return _format_error_response(code, "Command failed", {"detail": exc.detail})


@app.post("/selftest", response_model=SelfTestReport, tags=["health"])
def selftest() -> Dict[str, Any]:
    logger.info("Selftest requested")
    database_id = os.getenv("DATABASE_ID_TEST", "").strip()
    page_id = os.getenv("PAGE_ID_TEST", "").strip()
    checkbox_prop = os.getenv("PROP_CHECKBOX_TEST", "").strip()

    checks: List[Dict[str, Any]] = []
    notion_errors: List[Dict[str, Any]] = []
    status = "PASS"

    if not database_id or not page_id or not checkbox_prop:
        return {
            "status": "FAIL",
            "checks": [
                {
                    "name": "env_vars",
                    "status": "FAIL",
                    "message": "DATABASE_ID_TEST, PAGE_ID_TEST, PROP_CHECKBOX_TEST must be set",
                }
            ],
            "notion_errors": [],
        }

    try:
        _validate_database_id(database_id)
        _validate_page_id(page_id)
    except HTTPException as exc:
        return {
            "status": "FAIL",
            "checks": [{"name": "env_vars", "status": "FAIL", "message": exc.detail}],
            "notion_errors": [],
        }

    try:
        _request("GET", f"https://api.notion.com/v1/databases/{database_id}")
        checks.append({"name": "schema", "status": "PASS"})
    except HTTPException as exc:
        checks.append({"name": "schema", "status": "FAIL", "message": exc.detail})
        notion_errors.append({"step": "schema", "detail": exc.detail})
        status = "FAIL"

    try:
        _request(
            "POST",
            f"https://api.notion.com/v1/databases/{database_id}/query",
            {"page_size": 1},
        )
        checks.append({"name": "database_query", "status": "PASS"})
    except HTTPException as exc:
        checks.append({"name": "database_query", "status": "FAIL", "message": exc.detail})
        notion_errors.append({"step": "database_query", "detail": exc.detail})
        status = "FAIL"

    try:
        page = _request("GET", f"https://api.notion.com/v1/pages/{page_id}")
        properties = page.get("properties", {})
        prop_schema = properties.get(checkbox_prop)
        if not prop_schema or prop_schema.get("type") != "checkbox":
            raise HTTPException(
                status_code=400,
                detail=f"Property {checkbox_prop} is not a checkbox on test page",
            )
        payload = {"properties": {checkbox_prop: {"checkbox": True}}}
        _request("PATCH", f"https://api.notion.com/v1/pages/{page_id}", payload)
        checks.append({"name": "update_checkbox", "status": "PASS"})
    except HTTPException as exc:
        checks.append({"name": "update_checkbox", "status": "FAIL", "message": exc.detail})
        notion_errors.append({"step": "update_checkbox", "detail": exc.detail})
        status = "FAIL"

    return {"status": status, "checks": checks, "notion_errors": notion_errors}


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
