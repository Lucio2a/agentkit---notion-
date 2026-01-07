from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, Optional, Literal
import os
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
        raise HTTPException(status_code=500, detail="Missing NOTION_TOKEN or NOTION_DATABASE_ID")


def _get_title_prop_name(database_id: str) -> str:
    """Trouve la propriété de type 'title'"""
    try:
        db = notion.databases.retrieve(database_id=database_id)
        props = db.get("properties", {}) or {}
        
        # Cherche une propriété de type title
        for prop_name, prop in props.items():
            if prop.get("type") == "title":
                return prop_name
        
        # Si pas trouvé, prend la première propriété
        if props:
            return list(props.keys())[0]
            
        raise ValueError("No properties found in database")
    except Exception as e:
        raise ValueError(f"Error retrieving database: {str(e)}")


@app.get("/")
def root():
    return {
        "status": "✅ API Notion en ligne",
        "endpoints": {
            "GET /notion/test": "Teste la connexion",
            "GET /notion/read": "Lit les entrées (param: page_size)",
            "GET /notion/write": "Crée une entrée (param: title)",
            "POST /notion/action": "Endpoint principal pour GPT"
        }
    }


@app.get("/notion/test")
def notion_test():
    _ensure_notion()
    try:
        # Test direct sans résolution
        res = notion.databases.query(database_id=NOTION_DATABASE_ID, page_size=1)
        
        return {
            "status": "✅ Connexion réussie",
            "database_id": NOTION_DATABASE_ID,
            "can_read": True,
            "test_pages_found": len(res.get("results", []))
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur: {str(e)}")


@app.get("/notion/read")
def notion_read(page_size: int = 5):
    _ensure_notion()
    try:
        # Lecture directe sur l'ID donné
        res = notion.databases.query(database_id=NOTION_DATABASE_ID, page_size=page_size)
        
        items = []
        for page in res.get("results", []):
            props = page.get("properties", {}) or {}
            
            # Cherche la première propriété avec du texte
            title_text = ""
            for prop_name, prop_data in props.items():
                if prop_data.get("type") == "title":
                    title_obj = prop_data.get("title", [])
                    title_text = "".join([t.get("plain_text", "") for t in title_obj])
                    break
            
            if not title_text:
                # Essaie rich_text si pas de title
                for prop_name, prop_data in props.items():
                    if prop_data.get("type") == "rich_text":
                        rich_text = prop_data.get("rich_text", [])
                        title_text = "".join([t.get("plain_text", "") for t in rich_text])
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/notion/write")
def notion_write(title: str = "Test - création automatique"):
    _ensure_notion()
    try:
        # Trouve d'abord quelle propriété utiliser
        db = notion.databases.retrieve(database_id=NOTION_DATABASE_ID)
        props = db.get("properties", {}) or {}
        
        title_prop = None
        for prop_name, prop in props.items():
            if prop.get("type") == "title":
                title_prop = prop_name
                break
        
        if not title_prop:
            raise HTTPException(status_code=500, detail="Pas de propriété title trouvée")
        
        created = notion.pages.create(
            parent={"database_id": NOTION_DATABASE_ID},
            properties={
                title_prop: {
                    "title": [{"text": {"content": title}}]
                }
            }
        )
        
        return {
            "status": "✅ Entrée créée",
            "page_id": created.get("id"),
            "title": title,
            "url": created.get("url")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
    _ensure_notion()
    
    try:
        if payload.action == "read":
            res = notion.databases.query(database_id=NOTION_DATABASE_ID, page_size=payload.page_size)
            
            items = []
            for page in res.get("results", []):
                props = page.get("properties", {}) or {}
                
                title_text = ""
                for prop_name, prop_data in props.items():
                    if prop_data.get("type") == "title":
                        title_obj = prop_data.get("title", [])
                        title_text = "".join([t.get("plain_text", "") for t in title_obj])
                        break
                
                items.append({
                    "page_id": page.get("id"),
                    "title": title_text or "(sans titre)"
                })
            
            return {"status": "success", "items": items}
        
        elif payload.action == "create":
            if not payload.title:
                raise HTTPException(status_code=400, detail="Missing 'title' for create")
            
            # Trouve la propriété title
            db = notion.databases.retrieve(database_id=NOTION_DATABASE_ID)
            props = db.get("properties", {}) or {}
            
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
            
            created = notion.pages.create(
                parent={"database_id": NOTION_DATABASE_ID},
                properties=properties
            )
            
            return {
                "status": "created",
                "page_id": created.get("id"),
                "title": payload.title
            }
        
        elif payload.action == "update_checkbox":
            if not payload.page_id or not payload.property_name or payload.checked is None:
                raise HTTPException(status_code=400, detail="Need page_id, property_name, checked")
            
            notion.pages.update(
                page_id=payload.page_id,
                properties={
                    payload.property_name: {"checkbox": payload.checked}
                }
            )
            
            return {
                "status": "updated",
                "page_id": payload.page_id,
                "property": payload.property_name,
                "checked": payload.checked
            }
        
        elif payload.action == "update_text":
            if not payload.page_id or not payload.property_name or payload.text is None:
                raise HTTPException(status_code=400, detail="Need page_id, property_name, text")
            
            notion.pages.update(
                page_id=payload.page_id,
                properties={
                    payload.property_name: {"rich_text": [{"text": {"content": payload.text}}]}
                }
            )
            
            return {
                "status": "updated",
                "page_id": payload.page_id,
                "property": payload.property_name,
                "text": payload.text
            }
        
        raise HTTPException(status_code=400, detail="Unknown action")
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
