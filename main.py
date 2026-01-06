import os
from fastapi import FastAPI, HTTPException
from notion_client import Client

app = FastAPI()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

notion = Client(auth=NOTION_TOKEN) if (NOTION_TOKEN and NOTION_DATABASE_ID) else None

def get_title_property_name(database_id: str) -> str:
    """Trouve la propriété titre dans la base de données Notion"""
    if notion is None:
        raise ValueError("Missing NOTION_TOKEN or NOTION_DATABASE_ID")
    
    db = notion.databases.retrieve(database_id=database_id)
    props = db.get("properties", {})
    
    # Cherche d'abord une propriété de type "title"
    for prop_name, prop in props.items():
        if prop.get("type") == "title":
            return prop_name
    
    # Si pas trouvé, cherche les noms communs
    common_names = ["Name", "Nom", "Title", "Titre", "name", "title"]
    for name in common_names:
        if name in props:
            return name
    
    # En dernier recours, prend la première propriété
    if props:
        return list(props.keys())[0]
    
    raise ValueError("Aucune propriété trouvée dans la base de données")

@app.get("/")
def root():
    """Page d'accueil pour vérifier que l'API fonctionne"""
    return {
        "status": "API Notion est en ligne",
        "endpoints": [
            "/notion/test - Teste la connexion",
            "/notion/properties - Affiche toutes les propriétés",
            "/notion/read - Lit les entrées",
            "/notion/write?text=votre_texte - Crée une entrée"
        ]
    }

@app.get("/notion/debug")
def notion_debug():
    """Debug complet de la connexion Notion"""
    if notion is None:
        raise HTTPException(status_code=500, detail="Missing NOTION_TOKEN or NOTION_DATABASE_ID")
    
    try:
        # Test 1: Récupère la base
        db = notion.databases.retrieve(database_id=NOTION_DATABASE_ID)
        
        # Affiche TOUTE la réponse pour débugger
        return {
            "status": "retrieved",
            "database_id": NOTION_DATABASE_ID,
            "database_title": db.get("title", []),
            "full_response": db
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "error_type": type(e).__name__
        }

@app.get("/notion/properties")
def notion_properties():
    """Affiche TOUTES les propriétés de la base pour débugger"""
    if notion is None:
        raise HTTPException(status_code=500, detail="Missing NOTION_TOKEN or NOTION_DATABASE_ID")
    
    try:
        db = notion.databases.retrieve(database_id=NOTION_DATABASE_ID)
        props = db.get("properties", {})
        
        properties_info = {}
        for prop_name, prop in props.items():
            properties_info[prop_name] = {
                "type": prop.get("type"),
                "id": prop.get("id")
            }
        
        return {
            "database_id": NOTION_DATABASE_ID,
            "total_properties": len(properties_info),
            "properties": properties_info
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/notion/test")
def notion_test():
    """Teste la connexion à Notion"""
    if notion is None:
        raise HTTPException(status_code=500, detail="Missing NOTION_TOKEN or NOTION_DATABASE_ID")
    
    try:
        title_prop = get_title_property_name(NOTION_DATABASE_ID)
        return {
            "status": "✅ Connexion réussie",
            "database_id": NOTION_DATABASE_ID,
            "title_property": title_prop
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur: {str(e)}")

@app.get("/notion/read")
def notion_read(limit: int = 5):
    """Lit les entrées de la base Notion"""
    if notion is None:
        raise HTTPException(status_code=500, detail="Missing NOTION_TOKEN or NOTION_DATABASE_ID")
    
    try:
        title_prop = get_title_property_name(NOTION_DATABASE_ID)
        res = notion.databases.query(database_id=NOTION_DATABASE_ID, page_size=limit)
        
        items = []
        for page in res.get("results", []):
            props = page.get("properties", {})
            title_data = props.get(title_prop, {})
            
            # Gère différents types de propriétés
            title_text = ""
            if title_data.get("type") == "title":
                title_obj = title_data.get("title", [])
                title_text = "".join([t.get("plain_text", "") for t in title_obj])
            elif title_data.get("type") == "rich_text":
                rich_text = title_data.get("rich_text", [])
                title_text = "".join([t.get("plain_text", "") for t in rich_text])
            else:
                title_text = str(title_data)
            
            items.append({
                "page_id": page.get("id"),
                "title": title_text,
                "url": page.get("url")
            })
        
        return {
            "status": "success",
            "database_id": NOTION_DATABASE_ID,
            "title_property": title_prop,
            "count": len(items),
            "items": items
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/notion/write")
def notion_write(text: str = "Test - création automatique"):
    """Crée une nouvelle entrée dans Notion"""
    if notion is None:
        raise HTTPException(status_code=500, detail="Missing NOTION_TOKEN or NOTION_DATABASE_ID")
    
    try:
        title_prop = get_title_property_name(NOTION_DATABASE_ID)
        
        created = notion.pages.create(
            parent={"database_id": NOTION_DATABASE_ID},
            properties={
                title_prop: {
                    "title": [
                        {
                            "text": {
                                "content": text
                            }
                        }
                    ]
                }
            }
        )
        
        return {
            "status": "✅ Entrée créée",
            "page_id": created.get("id"),
            "title": text,
            "title_property": title_prop,
            "url": created.get("url")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Pour Render : ajoute ce fichier requirements.txt
# fastapi
# notion-client
# uvicorn[standard]
