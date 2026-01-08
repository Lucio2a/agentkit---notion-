from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, Optional, Literal
import os
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

def _ensure_config():
    if not NOTION_TOKEN or not NOTION_DATABASE_ID:
        raise HTTPException(status_code=500, detail="Missing NOTION_TOKEN or NOTION_DATABASE_ID")


@app.get("/")
def root():
    return {
        "status": "✅ API Notion en ligne",
        "endpoints": {
            "GET /notion/test": "Teste la connexion",
            "GET /notion/read": "Lit les entrées (param: limit=5)",
            "GET /notion/write": "Crée une entrée (param: title=...)",
            "POST /notion/action": "Endpoint principal pour GPT"
        }
    }


@app.get("/notion/test")
def notion_test():
    _ensure_config()
    try:
        url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
        response = requests.post(url, headers=_get_headers(), json={"page_size": 1})
        
        if response.status_code == 200:
            data = response.json()
            return {
                "status": "✅ Connexion réussie",
                "database_id": NOTION_DATABASE_ID,
                "test_pages_found": len(data.get("results", []))
            }
        else:
            raise HTTPException(status_code=response.status_code, detail=response.text)
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Erreur requête: {str(e)}")


@app.get("/notion/read")
def notion_read(limit: int = 5):
    _ensure_config()
    try:
        url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
        response = requests.post(url, headers=_get_headers(), json={"page_size": limit})
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=response.text)
        
        data = response.json()
        items = []
        
        for page in data.get("results", []):
            props = page.get("properties", {})
            
            # Cherche une propriété title
            title_text = ""
            for prop_name, prop_data in props.items():
                if prop_data.get("type") == "title":
                    title_arr = prop_data.get("title", [])
                    title_text = "".join([t.get("plain_text", "") for t in title_arr])
                    break
            
            # Si pas de title, cherche rich_text
            if not title_text:
                for prop_name, prop_data in props.items():
                    if prop_data.get("type") == "rich_text":
                        rich_arr = prop_data.get("rich_text", [])
                        title_text = "".join([t.get("plain_text", "") for t in rich_arr])
                        if title_text:
                            break
            
            items.append({
                "page_id": page.get("id"),
                "title": title_text or "(sans titre)",
                "url": page.get("url")
            })
        
        return {
            "status": "success",
            "database_id": NOTION_DATABASE_ID,
            "count": len(items),
            "items": items
        }
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Erreur: {str(e)}")


@app.get("/notion/write")
def notion_write(title: str = "Test - création automatique"):
    _ensure_config()
    try:
        # D'abord récupère les propriétés de la base
        db_url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}"
        db_response = requests.get(db_url, headers=_get_headers())
        
        if db_response.status_code != 200:
            raise HTTPException(status_code=db_response.status_code, detail=db_response.text)
        
        db_data = db_response.json()
        props = db_data.get("properties", {})
        
        # Trouve la propriété title
        title_prop = None
        for prop_name, prop in props.items():
            if prop.get("type") == "title":
                title_prop = prop_name
                break
        
        if not title_prop:
            raise HTTPException(status_code=500, detail="Pas de propriété title trouvée")
        
        # Crée la page
        create_url = "https://api.notion.com/v1/pages"
        payload = {
            "parent": {"database_id": NOTION_DATABASE_ID},
            "properties": {
                title_prop: {
                    "title": [{"text": {"content": title}}]
                }
            }
        }
        
        create_response = requests.post(create_url, headers=_get_headers(), json=payload)
        
        if create_response.status_code != 200:
            raise HTTPException(status_code=create_response.status_code, detail=create_response.text)
        
        created = create_response.json()
        
        return {
            "status": "✅ Entrée créée",
            "page_id": created.get("id"),
            "title": title,
            "url": created.get("url")
        }
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Erreur: {str(e)}")


# Endpoint POST pour GPT
ActionType = Literal["read", "create", "update_checkbox", "update_text"]

class NotionAction(BaseModel):
    action: ActionType
    page_size: int = 5
    title: Optional[str] = None
    extra_properties: Optional[Dict[str, Any]] = None
    page_id: Optional[str] = None
    property_name: Optional[str] = None
    checked: Optional[bool] = None
    text: Optional[str] = None


@app.post("/notion/action")
def notion_action(payload: NotionAction):
    """Endpoint unique pour GPT Coach"""
    _ensure_config()
    
    try:
        if payload.action == "read":
            url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
            response = requests.post(url, headers=_get_headers(), json={"page_size": payload.page_size})
            
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=response.text)
            
            data = response.json()
            items = []
            
            for page in data.get("results", []):
                props = page.get("properties", {})
                
                title_text = ""
                for prop_name, prop_data in props.items():
                    if prop_data.get("type") == "title":
                        title_arr = prop_data.get("title", [])
                        title_text = "".join([t.get("plain_text", "") for t in title_arr])
                        break
                
                items.append({
                    "page_id": page.get("id"),
                    "title": title_text or "(sans titre)"
                })
            
            return {"status": "success", "items": items}
        
        elif payload.action == "create":
            if not payload.title:
                raise HTTPException(status_code=400, detail="Missing 'title' for create")
            
            # Récupère les propriétés
            db_url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}"
            db_response = requests.get(db_url, headers=_get_headers())
            
            if db_response.status_code != 200:
                raise HTTPException(status_code=db_response.status_code, detail=db_response.text)
            
            db_data = db_response.json()
            props = db_data.get("properties", {})
            
            title_prop = None
            for prop_name, prop in props.items():
                if prop.get("type") == "title":
                    title_prop = prop_name
                    break
            
            if not title_prop:
                raise HTTPException(status_code=500, detail="No title property found")
            
            properties = {
                title_prop: {"title": [{"text": {"content": payload.title}}]}
            }
            
            if payload.extra_properties:
                properties.update(payload.extra_properties)
            
            create_url = "https://api.notion.com/v1/pages"
            create_payload = {
                "parent": {"database_id": NOTION_DATABASE_ID},
                "properties": properties
            }
            
            create_response = requests.post(create_url, headers=_get_headers(), json=create_payload)
            
            if create_response.status_code != 200:
                raise HTTPException(status_code=create_response.status_code, detail=create_response.text)
            
            created = create_response.json()
            
            return {
                "status": "created",
                "page_id": created.get("id"),
                "title": payload.title
            }
        
        elif payload.action == "update_checkbox":
            if not payload.page_id or not payload.property_name or payload.checked is None:
                raise HTTPException(status_code=400, detail="Need page_id, property_name, checked")
            
            update_url = f"https://api.notion.com/v1/pages/{payload.page_id}"
            update_payload = {
                "properties": {
                    payload.property_name: {"checkbox": payload.checked}
                }
            }
            
            update_response = requests.patch(update_url, headers=_get_headers(), json=update_payload)
            
            if update_response.status_code != 200:
                raise HTTPException(status_code=update_response.status_code, detail=update_response.text)
            
            return {
                "status": "updated",
                "page_id": payload.page_id,
                "property": payload.property_name,
                "checked": payload.checked
            }
        
        elif payload.action == "update_text":
            if not payload.page_id or not payload.property_name or payload.text is None:
                raise HTTPException(status_code=400, detail="Need page_id, property_name, text")
            
            update_url = f"https://api.notion.com/v1/pages/{payload.page_id}"
            update_payload = {
                "properties": {
                    payload.property_name: {"rich_text": [{"text": {"content": payload.text}}]}
                }
            }
            
            update_response = requests.patch(update_url, headers=_get_headers(), json=update_payload)
            
            if update_response.status_code != 200:
                raise HTTPException(status_code=update_response.status_code, detail=update_response.text)
            
            return {
                "status": "updated",
                "page_id": payload.page_id,
                "property": payload.property_name,
                "text": payload.text
            }
        
        raise HTTPException(status_code=400, detail="Unknown action")
    
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Erreur requête: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
