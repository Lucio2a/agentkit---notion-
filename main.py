import os
from typing import Any, Dict, Optional, List
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
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

# ==================== MODÈLES ====================

class NotionAction(BaseModel):
    action: str = Field(..., description="Action à effectuer: read, create, update, delete, search, get_database, create_database, update_database")
    
    # Pour read/search
    database_id: Optional[str] = None
    page_size: int = Field(default=10, ge=1, le=100)
    filter: Optional[Dict[str, Any]] = None
    sorts: Optional[List[Dict[str, Any]]] = None
    
    # Pour create/update
    page_id: Optional[str] = None
    properties: Optional[Dict[str, Any]] = None
    
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
async def notion_universal(action: NotionAction):
    """
    Endpoint universel pour TOUTES les opérations Notion.
    
    Actions disponibles:
    - read: Lire les pages d'une database
    - create: Créer une page
    - update: Modifier une page
    - delete: Archiver une page
    - search: Rechercher dans tout le workspace
    - get_database: Obtenir les propriétés d'une database
    - create_database: Créer une nouvelle database
    - update_database: Modifier une database
    - get_page: Obtenir une page complète
    - append_blocks: Ajouter du contenu à une page
    """
    
    try:
        # ============ READ DATABASE ============
        if action.action == "read":
            db_id = action.database_id or NOTION_DATABASE_ID
            url = f"https://api.notion.com/v1/databases/{db_id}/query"
            
            payload = {"page_size": action.page_size}
            if action.filter:
                payload["filter"] = action.filter
            if action.sorts:
                payload["sorts"] = action.sorts
            
            response = requests.post(url, headers=_get_headers(), json=payload)
            
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=response.text)
            
            data = response.json()
            
            # Simplifie les résultats
            items = []
            for page in data.get("results", []):
                simplified = {
                    "page_id": page.get("id"),
                    "url": page.get("url"),
                    "created_time": page.get("created_time"),
                    "last_edited_time": page.get("last_edited_time"),
                    "properties": {}
                }
                
                # Extrait les valeurs lisibles des propriétés
                for prop_name, prop_data in page.get("properties", {}).items():
                    prop_type = prop_data.get("type")
                    
                    if prop_type == "title":
                        simplified["properties"][prop_name] = "".join([t.get("plain_text", "") for t in prop_data.get("title", [])])
                    elif prop_type == "rich_text":
                        simplified["properties"][prop_name] = "".join([t.get("plain_text", "") for t in prop_data.get("rich_text", [])])
                    elif prop_type == "number":
                        simplified["properties"][prop_name] = prop_data.get("number")
                    elif prop_type == "select":
                        simplified["properties"][prop_name] = prop_data.get("select", {}).get("name")
                    elif prop_type == "multi_select":
                        simplified["properties"][prop_name] = [s.get("name") for s in prop_data.get("multi_select", [])]
                    elif prop_type == "date":
                        simplified["properties"][prop_name] = prop_data.get("date")
                    elif prop_type == "checkbox":
                        simplified["properties"][prop_name] = prop_data.get("checkbox")
                    elif prop_type == "url":
                        simplified["properties"][prop_name] = prop_data.get("url")
                    elif prop_type == "email":
                        simplified["properties"][prop_name] = prop_data.get("email")
                    elif prop_type == "phone_number":
                        simplified["properties"][prop_name] = prop_data.get("phone_number")
                    elif prop_type == "status":
                        simplified["properties"][prop_name] = prop_data.get("status", {}).get("name")
                    else:
                        simplified["properties"][prop_name] = prop_data
                
                items.append(simplified)
            
            return {
                "status": "success",
                "action": "read",
                "count": len(items),
                "has_more": data.get("has_more"),
                "items": items
            }
        
        # ============ CREATE PAGE ============
        elif action.action == "create":
            db_id = action.database_id or NOTION_DATABASE_ID
            
            if not action.properties:
                raise HTTPException(status_code=400, detail="properties required for create")
            
            url = "https://api.notion.com/v1/pages"
            payload = {
                "parent": {"database_id": db_id},
                "properties": action.properties
            }
            
            response = requests.post(url, headers=_get_headers(), json=payload)
            
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=response.text)
            
            created = response.json()
            
            return {
                "status": "success",
                "action": "create",
                "page_id": created.get("id"),
                "url": created.get("url")
            }
        
        # ============ UPDATE PAGE ============
        elif action.action == "update":
            if not action.page_id:
                raise HTTPException(status_code=400, detail="page_id required for update")
            
            url = f"https://api.notion.com/v1/pages/{action.page_id}"
            payload = {}
            
            if action.properties:
                payload["properties"] = action.properties
            if action.archived is not None:
                payload["archived"] = action.archived
            
            response = requests.patch(url, headers=_get_headers(), json=payload)
            
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=response.text)
            
            updated = response.json()
            
            return {
                "status": "success",
                "action": "update",
                "page_id": updated.get("id"),
                "url": updated.get("url")
            }
        
        # ============ DELETE (ARCHIVE) PAGE ============
        elif action.action == "delete":
            if not action.page_id:
                raise HTTPException(status_code=400, detail="page_id required for delete")
            
            url = f"https://api.notion.com/v1/pages/{action.page_id}"
            payload = {"archived": True}
            
            response = requests.patch(url, headers=_get_headers(), json=payload)
            
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=response.text)
            
            return {
                "status": "success",
                "action": "delete",
                "page_id": action.page_id,
                "archived": True
            }
        
        # ============ SEARCH ============
        elif action.action == "search":
            url = "https://api.notion.com/v1/search"
            payload = {"page_size": action.page_size}
            
            if action.query:
                payload["query"] = action.query
            if action.filter:
                payload["filter"] = action.filter
            if action.sorts:
                payload["sort"] = action.sorts
            
            response = requests.post(url, headers=_get_headers(), json=payload)
            
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=response.text)
            
            data = response.json()
            
            return {
                "status": "success",
                "action": "search",
                "count": len(data.get("results", [])),
                "results": data.get("results", [])
            }
        
        # ============ GET DATABASE ============
        elif action.action == "get_database":
            db_id = action.database_id or NOTION_DATABASE_ID
            url = f"https://api.notion.com/v1/databases/{db_id}"
            
            response = requests.get(url, headers=_get_headers())
            
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=response.text)
            
            return {
                "status": "success",
                "action": "get_database",
                "database": response.json()
            }
        
        # ============ CREATE DATABASE ============
        elif action.action == "create_database":
            if not action.parent_page_id or not action.title or not action.database_properties:
                raise HTTPException(status_code=400, detail="parent_page_id, title, and database_properties required")
            
            url = "https://api.notion.com/v1/databases"
            payload = {
                "parent": {"type": "page_id", "page_id": action.parent_page_id},
                "title": [{"type": "text", "text": {"content": action.title}}],
                "properties": action.database_properties
            }
            
            response = requests.post(url, headers=_get_headers(), json=payload)
            
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=response.text)
            
            created = response.json()
            
            return {
                "status": "success",
                "action": "create_database",
                "database_id": created.get("id"),
                "url": created.get("url")
            }
        
        # ============ UPDATE DATABASE ============
        elif action.action == "update_database":
            db_id = action.database_id or NOTION_DATABASE_ID
            url = f"https://api.notion.com/v1/databases/{db_id}"
            
            payload = {}
            if action.title:
                payload["title"] = [{"type": "text", "text": {"content": action.title}}]
            if action.database_properties:
                payload["properties"] = action.database_properties
            
            response = requests.patch(url, headers=_get_headers(), json=payload)
            
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=response.text)
            
            return {
                "status": "success",
                "action": "update_database",
                "database": response.json()
            }
        
        # ============ GET PAGE ============
        elif action.action == "get_page":
            if not action.page_id:
                raise HTTPException(status_code=400, detail="page_id required")
            
            url = f"https://api.notion.com/v1/pages/{action.page_id}"
            response = requests.get(url, headers=_get_headers())
            
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=response.text)
            
            return {
                "status": "success",
                "action": "get_page",
                "page": response.json()
            }
        
        # ============ APPEND BLOCKS (Ajouter du contenu) ============
        elif action.action == "append_blocks":
            if not action.page_id:
                raise HTTPException(status_code=400, detail="page_id required")
            
            url = f"https://api.notion.com/v1/blocks/{action.page_id}/children"
            
            # action.properties contient les blocks à ajouter
            if not action.properties or "children" not in action.properties:
                raise HTTPException(status_code=400, detail="properties.children with blocks required")
            
            payload = {"children": action.properties["children"]}
            
            response = requests.patch(url, headers=_get_headers(), json=payload)
            
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=response.text)
            
            return {
                "status": "success",
                "action": "append_blocks",
                "result": response.json()
            }
        
        else:
            raise HTTPException(status_code=400, detail=f"Unknown action: {action.action}")
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== ENDPOINTS SIMPLES ====================

@app.get("/")
def root():
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
            "append_blocks - Ajouter du contenu"
        ]
    }


@app.get("/notion/test")
def test():
    return {
        "status": "ok",
        "database_id": NOTION_DATABASE_ID,
        "token_present": bool(NOTION_TOKEN)
    }
