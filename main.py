diff --git a/main.py b/main.py
index 9c94e3f45a73ab6ba41dfe2e4baa38cd1be70b9f..2af62eccf230c7879ec20c68bfd961f5b3c7910e 100644
--- a/main.py
+++ b/main.py
@@ -1,61 +1,63 @@
 import os
 from typing import Any, Dict, Optional, List
 from fastapi import FastAPI, HTTPException
 from pydantic import BaseModel, Field
 import requests
+from notion_client import Client
 
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
     block_id: Optional[str] = None
     page_size: int = Field(default=10, ge=1, le=100)
     filter: Optional[Dict[str, Any]] = None
     sorts: Optional[List[Dict[str, Any]]] = None
     
     # Pour create/update
     page_id: Optional[str] = None
     properties: Optional[Dict[str, Any]] = None
+    children: Optional[List[Dict[str, Any]]] = None
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
 async def notion_universal(action: NotionAction):
     """
     Endpoint universel pour TOUTES les opérations Notion.
     
     Actions disponibles:
     - read: Lire les pages d'une database
     - create: Créer une page
     - update: Modifier une page
     - delete: Archiver une page
@@ -140,68 +142,73 @@ async def notion_universal(action: NotionAction):
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
+            if not isinstance(action.properties, dict):
+                raise HTTPException(status_code=400, detail="properties must be a dict")
             
-            url = "https://api.notion.com/v1/pages"
-            payload = {
-                "parent": {"database_id": db_id},
-                "properties": action.properties
-            }
-            
-            response = requests.post(url, headers=_get_headers(), json=payload)
-            
-            if response.status_code != 200:
-                raise HTTPException(status_code=response.status_code, detail=response.text)
-            
-            created = response.json()
+            if not NOTION_TOKEN:
+                raise HTTPException(status_code=500, detail="Missing NOTION_TOKEN")
+
+            notion = Client(auth=NOTION_TOKEN)
+
+            if action.children:
+                created = notion.pages.create(
+                    parent={"database_id": db_id},
+                    properties=action.properties,
+                    children=action.children,
+                )
+            else:
+                created = notion.pages.create(
+                    parent={"database_id": db_id},
+                    properties=action.properties,
+                )
             
             return {
-                "status": "success",
-                "action": "create",
-                "page_id": created.get("id"),
+                "status": "ok",
+                "created_page_id": created.get("id"),
                 "url": created.get("url")
             }
         
         # ============ UPDATE PAGE ============
         elif action.action == "update":
             if action.block_id:
                 if not action.block:
                     raise HTTPException(status_code=400, detail="block payload required for block update")
                 
                 url = f"https://api.notion.com/v1/blocks/{action.block_id}"
                 response = requests.patch(url, headers=_get_headers(), json=action.block)
                 
                 if response.status_code != 200:
                     raise HTTPException(status_code=response.status_code, detail=response.text)
                 
                 updated = response.json()
                 
                 return {
                     "status": "success",
                     "action": "update",
                     "block_id": updated.get("id"),
                     "result": updated
                 }
             
             if not action.page_id:
@@ -397,25 +404,30 @@ def root():
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
+
+
+@app.get("/health")
+def health():
+    return {"status": "ok"}
