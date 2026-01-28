import logging
import os
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

import requests

TOKEN_ENV_CANDIDATES = (
    "NOTION_TOKEN",
    "NOTION_API_KEY",
    "NOTION_SECRET",
    "NOTION_ACCESS_TOKEN",
)
NOTION_VERSION = "2022-06-28"

logger = logging.getLogger("notion-writer")


class NotionAPIError(Exception):
    def __init__(self, status_code: int, message: str, response_text: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.response_text = response_text


class NotionClient:
    def __init__(self) -> None:
        self._token = self._get_token()

    @staticmethod
    def _get_token() -> str:
        for env_name in TOKEN_ENV_CANDIDATES:
            value = os.getenv(env_name, "").strip()
            if value:
                return value
        raise NotionAPIError(500, "Missing Notion token in environment")

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def request(
        self,
        method: str,
        url: str,
        payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        response = requests.request(
            method,
            url,
            headers=self._headers(),
            json=payload,
            params=params,
            timeout=30,
        )
        if not response.ok:
            message = f"Notion API error ({response.status_code}): {response.text}"
            logger.error("Notion API request failed: %s", message)
            raise NotionAPIError(response.status_code, message, response.text)
        return response.json()

    def request_raw(
        self,
        method: str,
        url: str,
        payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return requests.request(
            method,
            url,
            headers=self._headers(),
            json=payload,
            params=params,
            timeout=30,
        )


class NotionWriter:
    def __init__(self) -> None:
        self.client = NotionClient()

    def read_database_schema(self, database_id: str) -> Dict[str, Any]:
        validated_id = _validate_uuid("database_id", database_id)
        database = self.client.request(
            "GET", f"https://api.notion.com/v1/databases/{validated_id}"
        )
        return _format_database_schema(database)

    def read_page(self, page_id: str) -> Dict[str, Any]:
        validated_id = _validate_uuid("page_id", page_id)
        page = self.client.request("GET", f"https://api.notion.com/v1/pages/{validated_id}")
        blocks = [_build_block_tree(child, self.client) for child in _paginate_block_children(validated_id, self.client)]
        return {"page": page, "blocks": blocks}

    def create_page_in_database(
        self,
        database_id: str,
        title: str,
        properties: Optional[Dict[str, Any]] = None,
        content: Optional[str] = None,
        blocks: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        validated_id = _validate_uuid("database_id", database_id)
        database = self.client.request(
            "GET", f"https://api.notion.com/v1/databases/{validated_id}"
        )
        title_property = _get_database_title_property(database)
        notion_properties: Dict[str, Any] = {
            title_property: {"title": [{"type": "text", "text": {"content": title}}]}
        }
        if properties:
            mapped, errors = _map_properties_from_schema(database.get("properties", {}), properties)
            if errors:
                raise NotionAPIError(400, f"Invalid properties payload: {errors}")
            notion_properties.update(mapped)
        payload: Dict[str, Any] = {
            "parent": {"database_id": validated_id},
            "properties": notion_properties,
        }
        children = _build_children_from_content(content, blocks)
        if children:
            payload["children"] = children
        return self.client.request("POST", "https://api.notion.com/v1/pages", payload)

    def create_child_page(
        self,
        parent_page_id: str,
        title: str,
        content: Optional[str] = None,
        blocks: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        validated_id = _validate_uuid("page_id", parent_page_id)
        payload: Dict[str, Any] = {
            "parent": {"page_id": validated_id},
            "properties": {"title": {"title": [{"type": "text", "text": {"content": title}}]}},
        }
        children = _build_children_from_content(content, blocks)
        if children:
            payload["children"] = children
        return self.client.request("POST", "https://api.notion.com/v1/pages", payload)

    def update_page_properties(self, page_id: str, properties: Dict[str, Any]) -> Dict[str, Any]:
        validated_id = _validate_uuid("page_id", page_id)
        page = self.client.request("GET", f"https://api.notion.com/v1/pages/{validated_id}")
        parent = page.get("parent", {})
        schema_properties: Dict[str, Any]
        if parent.get("type") == "database_id" and parent.get("database_id"):
            database = self.client.request(
                "GET", f"https://api.notion.com/v1/databases/{parent['database_id']}"
            )
            schema_properties = database.get("properties", {})
        else:
            schema_properties = page.get("properties", {})
        mapped, errors = _map_properties_from_schema(schema_properties, properties)
        if errors:
            raise NotionAPIError(400, f"Invalid properties payload: {errors}")
        payload = {"properties": mapped}
        return self.client.request("PATCH", f"https://api.notion.com/v1/pages/{validated_id}", payload)

    def archive_page(self, page_id: str) -> Dict[str, Any]:
        validated_id = _validate_uuid("page_id", page_id)
        payload = {"archived": True}
        return self.client.request("PATCH", f"https://api.notion.com/v1/pages/{validated_id}", payload)

    def append_blocks(self, block_id: str, blocks: List[Dict[str, Any]]) -> Dict[str, Any]:
        validated_id = _validate_uuid("block_id", block_id)
        payload = {"children": _build_blocks_from_items(blocks)}
        return self.client.request(
            "PATCH", f"https://api.notion.com/v1/blocks/{validated_id}/children", payload
        )

    def replace_blocks(self, block_id: str, blocks: List[Dict[str, Any]]) -> Dict[str, Any]:
        validated_id = _validate_uuid("block_id", block_id)
        _delete_all_page_blocks(validated_id, self.client)
        payload = {"children": _build_blocks_from_items(blocks)}
        return self.client.request(
            "PATCH", f"https://api.notion.com/v1/blocks/{validated_id}/children", payload
        )

    def delete_blocks(self, block_ids: List[str]) -> Dict[str, Any]:
        deleted = []
        for block_id in block_ids:
            validated_id = _validate_uuid("block_id", str(block_id))
            response = self.client.request_raw(
                "DELETE", f"https://api.notion.com/v1/blocks/{validated_id}"
            )
            if not response.ok:
                raise NotionAPIError(
                    response.status_code,
                    f"Notion API error ({response.status_code}): {response.text}",
                    response.text,
                )
            deleted.append(validated_id)
        return {"deleted": deleted}

    def update_block_text(self, block_id: str, text: str) -> Dict[str, Any]:
        validated_id = _validate_uuid("block_id", block_id)
        block = self.client.request("GET", f"https://api.notion.com/v1/blocks/{validated_id}")
        block_type = block.get("type")
        if block_type not in {
            "paragraph",
            "heading_1",
            "heading_2",
            "heading_3",
            "bulleted_list_item",
            "numbered_list_item",
            "to_do",
        }:
            raise NotionAPIError(400, f"Unsupported block type for text update: {block_type}")
        payload = {
            block_type: {
                "rich_text": [{"type": "text", "text": {"content": text}}],
            }
        }
        return self.client.request("PATCH", f"https://api.notion.com/v1/blocks/{validated_id}", payload)

    def replace_page_content(self, page_id: str, content: str) -> Dict[str, Any]:
        validated_id = _validate_uuid("page_id", page_id)
        _delete_all_page_blocks(validated_id, self.client)
        payload = {"children": _build_children_from_content(content, None) or []}
        return self.client.request(
            "PATCH", f"https://api.notion.com/v1/blocks/{validated_id}/children", payload
        )


notion_writer = NotionWriter()


def notion_read_database_schema(database_id: str) -> Dict[str, Any]:
    """Read a Notion database schema including property options."""
    return notion_writer.read_database_schema(database_id)


def notion_read_page(page_id: str) -> Dict[str, Any]:
    """Read a Notion page and its block tree."""
    return notion_writer.read_page(page_id)


def notion_create_page_in_database(
    database_id: str,
    title: str,
    properties: Optional[Dict[str, Any]] = None,
    content: Optional[str] = None,
    blocks: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Create a new page inside a database with validated properties."""
    return notion_writer.create_page_in_database(
        database_id=database_id,
        title=title,
        properties=properties,
        content=content,
        blocks=blocks,
    )


def notion_create_child_page(
    parent_page_id: str,
    title: str,
    content: Optional[str] = None,
    blocks: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Create a child page under another page."""
    return notion_writer.create_child_page(
        parent_page_id=parent_page_id,
        title=title,
        content=content,
        blocks=blocks,
    )


def notion_update_page_properties(page_id: str, properties: Dict[str, Any]) -> Dict[str, Any]:
    """Update Notion page properties after validating against schema."""
    return notion_writer.update_page_properties(page_id=page_id, properties=properties)


def notion_archive_page(page_id: str) -> Dict[str, Any]:
    """Archive a Notion page (or database entry)."""
    return notion_writer.archive_page(page_id=page_id)


def notion_append_blocks(block_id: str, blocks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Append blocks to an existing Notion page or block."""
    return notion_writer.append_blocks(block_id=block_id, blocks=blocks)


def notion_replace_blocks(block_id: str, blocks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Replace all blocks under a page or block with new content."""
    return notion_writer.replace_blocks(block_id=block_id, blocks=blocks)


def notion_delete_blocks(block_ids: List[str]) -> Dict[str, Any]:
    """Delete blocks by id."""
    return notion_writer.delete_blocks(block_ids=block_ids)


def notion_update_block_text(block_id: str, text: str) -> Dict[str, Any]:
    """Update the text of a supported Notion block."""
    return notion_writer.update_block_text(block_id=block_id, text=text)


def notion_replace_page_content(page_id: str, content: str) -> Dict[str, Any]:
    """Replace all content in a page with plain text paragraphs."""
    return notion_writer.replace_page_content(page_id=page_id, content=content)


NOTION_TOOLS = [
    notion_read_database_schema,
    notion_read_page,
    notion_create_page_in_database,
    notion_create_child_page,
    notion_update_page_properties,
    notion_archive_page,
    notion_append_blocks,
    notion_replace_blocks,
    notion_delete_blocks,
    notion_update_block_text,
    notion_replace_page_content,
]


def _validate_uuid(field_name: str, value: str) -> str:
    candidate = value.strip()
    if not candidate:
        raise NotionAPIError(400, f"{field_name} must be provided")
    if re.fullmatch(r"[0-9a-fA-F-]{32,36}", candidate) is None:
        raise NotionAPIError(400, f"{field_name} must resemble a UUID")
    try:
        uuid.UUID(candidate.replace("-", ""))
    except ValueError as exc:
        raise NotionAPIError(400, f"{field_name} must resemble a UUID") from exc
    return candidate


def _paginate_block_children(block_id: str, client: NotionClient) -> List[Dict[str, Any]]:
    children: List[Dict[str, Any]] = []
    url = f"https://api.notion.com/v1/blocks/{block_id}/children"
    params: Dict[str, Any] = {"page_size": 100}
    while True:
        data = client.request("GET", url, params=params)
        children.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        params = {"page_size": 100, "start_cursor": data.get("next_cursor")}
    return children


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


def _build_block_tree(block: Dict[str, Any], client: NotionClient) -> Dict[str, Any]:
    block_type = block.get("type", "")
    node = _serialize_block(block)
    children: List[Dict[str, Any]] = []
    if block.get("has_children"):
        children.extend(
            [_build_block_tree(child, client) for child in _paginate_block_children(block.get("id", ""), client)]
        )
    if block_type == "child_database":
        database_id = block.get("id", "")
        for page in _paginate_database_pages(database_id, client):
            page_id = page.get("id", "")
            page_node: Dict[str, Any] = {
                "id": page_id,
                "type": "page",
                "title": _get_page_title(page),
            }
            page_children = [
                _build_block_tree(child, client) for child in _paginate_block_children(page_id, client)
            ]
            if page_children:
                page_node["children"] = page_children
            children.append(page_node)
    if children:
        node["children"] = children
    return node


def _paginate_database_pages(database_id: str, client: NotionClient) -> List[Dict[str, Any]]:
    pages: List[Dict[str, Any]] = []
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    payload: Dict[str, Any] = {"page_size": 100}
    while True:
        data = client.request("POST", url, payload)
        pages.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        payload = {"start_cursor": data.get("next_cursor"), "page_size": 100}
    return pages


def _get_page_title(page: Dict[str, Any]) -> str:
    properties = page.get("properties", {})
    for prop_data in properties.values():
        if prop_data.get("type") == "title":
            return _extract_plain_text(prop_data.get("title", []))
    return ""


def _extract_plain_text(rich_text: List[Dict[str, Any]]) -> str:
    return "".join(part.get("plain_text", "") for part in rich_text)


def _get_database_title(database: Dict[str, Any]) -> str:
    return _extract_plain_text(database.get("title", [])) or "Untitled"


def _format_database_schema(database: Dict[str, Any]) -> Dict[str, Any]:
    properties_list: List[Dict[str, Any]] = []
    for name, prop in database.get("properties", {}).items():
        prop_type = prop.get("type", "")
        entry: Dict[str, Any] = {"name": name, "type": prop_type}
        if prop_type in {"status", "select", "multi_select"}:
            entry["options"] = _extract_schema_options(prop, prop_type)
        properties_list.append(entry)
    return {
        "database_id": database.get("id", ""),
        "title": _get_database_title(database),
        "properties": properties_list,
    }


def _get_database_title_property(database: Dict[str, Any]) -> str:
    for name, prop in database.get("properties", {}).items():
        if prop.get("type") == "title":
            return name
    raise NotionAPIError(500, "Database has no title property")


def _extract_schema_options(schema: Dict[str, Any], prop_type: str) -> List[str]:
    options = schema.get(prop_type, {}).get("options", [])
    return [option.get("name", "") for option in options if option.get("name")]


def _map_property_value_strict(
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
        mapped, error = _map_property_value_strict(prop_schema, value)
        if error:
            error_entry: Dict[str, Any] = {"property": name, "reason": error}
            if error in {"invalid_option", "missing_options"}:
                prop_type = prop_schema.get("type")
                if prop_type in {"select", "multi_select", "status"}:
                    error_entry["options"] = _extract_schema_options(prop_schema, prop_type)
            errors.append(error_entry)
            continue
        if mapped is not None:
            payload[name] = mapped
    return payload, errors


def _build_children_from_content(
    content: Optional[str],
    blocks: Optional[List[Dict[str, Any]]],
) -> Optional[List[Dict[str, Any]]]:
    if blocks:
        return _build_blocks_from_items(blocks)
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


def _build_blocks_from_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    for item in items:
        block_type = item.get("type")
        text = item.get("text", "")
        if not isinstance(text, str) or not text.strip():
            raise NotionAPIError(400, "Block text must be a non-empty string")
        if block_type not in {
            "paragraph",
            "heading_1",
            "heading_2",
            "heading_3",
            "bulleted_list_item",
            "numbered_list_item",
            "to_do",
        }:
            raise NotionAPIError(400, f"Unsupported block type: {block_type}")
        block_payload: Dict[str, Any] = {
            "object": "block",
            "type": block_type,
            block_type: {
                "rich_text": [{"type": "text", "text": {"content": text}}],
            },
        }
        if block_type == "to_do":
            block_payload[block_type]["checked"] = bool(item.get("checked", False))
        blocks.append(block_payload)
    if not blocks:
        raise NotionAPIError(400, "blocks must include at least one item")
    return blocks


def _delete_all_page_blocks(page_id: str, client: NotionClient) -> None:
    children = _paginate_block_children(page_id, client)
    for child in children:
        block_id = child.get("id")
        if not block_id:
            continue
        response = client.request_raw("DELETE", f"https://api.notion.com/v1/blocks/{block_id}")
        if not response.ok:
            raise NotionAPIError(
                response.status_code,
                f"Notion API error ({response.status_code}): {response.text}",
                response.text,
            )
