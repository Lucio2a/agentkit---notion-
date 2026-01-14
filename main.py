import os
import re
from datetime import datetime, date, timezone
from typing import Any, Dict, Optional

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# =======================
# ENV
# =======================
NOTION_TOKEN = os.getenv("NOTION_TOKEN", "").strip()
NOTION_VERSION = os.getenv("NOTION_VERSION", "2022-06-28").strip()
HABITS_DB_ID = os.getenv("HABITS_DB_ID", "").strip()

NOTION_API_BASE = "https://api.notion.com/v1"

app = FastAPI(title="Notion backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # à restreindre plus tard si tu veux
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =======================
# HELPERS
# =======================
def _headers() -> Dict[str, str]:
    if not NOTION_TOKEN:
        # On ne crash pas le serveur, mais on renverra une erreur claire sur les endpoints Notion.
        return {}
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

def normalize_notion_id(raw: str) -> str:
    """
    Accepte:
    - UUID avec tirets
    - 32 chars sans tirets
    - URL notion contenant l'id
    Retourne UUID avec tirets.
    """
    if not raw:
        return raw

    s = raw.strip()

    # Si URL notion, extraire un bloc de 32 hex
    m = re.search(r"([0-9a-fA-F]{32})", s)
    if m:
        s = m.group(1)

    # Déjà UUID avec tirets
    if re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", s):
        return s.lower()

    # 32 chars => ajouter tirets
    if re.fullmatch(r"[0-9a-fA-F]{32}", s):
        s = s.lower()
        return f"{s[0:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:32]}"

    return s  # fallback

async def notion_get(path: str) -> Dict[str, Any]:
    if not NOTION_TOKEN:
        raise HTTPException(status_code=500, detail="NOTION_TOKEN manquant (variable d'environnement).")
    url = f"{NOTION_API_BASE}{path}"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url, headers=_headers())
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=r.json())
    return r.json()

async def notion_post(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not NOTION_TOKEN:
        raise HTTPException(status_code=500, detail="NOTION_TOKEN manquant (variable d'environnement).")
    url = f"{NOTION_API_BASE}{path}"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, headers=_headers(), json=payload)
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=r.json())
    return r.json()

async def notion_patch(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not NOTION_TOKEN:
        raise HTTPException(status_code=500, detail="NOTION_TOKEN manquant (variable d'environnement).")
    url = f"{NOTION_API_BASE}{path}"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.patch(url, headers=_headers(), json=payload)
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=r.json())
    return r.json()

def today_iso() -> str:
    # Notion date sans heure -> YYYY-MM-DD
    return date.today().isoformat()

# =======================
# MODELS
# =======================
class HabitsUpdate(BaseModel):
    # EXACTEMENT les noms de tes propriétés Notion (comme dans ton JSON)
    Meditation: Optional[bool] = None
    Bonne_Alimentation: Optional[bool] = None
    Sport_Marche: Optional[bool] = None
    Deep_Focus: Optional[bool] = None
    Lecture: Optional[bool] = None
    Jour: Optional[str] = None
    Title: Optional[str] = None  # correspond à la propriété title nommée "."

# =======================
# ROUTES
# =======================
@app.get("/")
async def root():
    return {"status": "Notion backend OK", "habits_db_id": HABITS_DB_ID or None}

@app.get("/notion/test")
async def notion_test():
    # Vérifie juste si le token répond
    data = await notion_get("/users/me")
    return {"ok": True, "user": {"id": data.get("id"), "name": data.get("name"), "type": data.get("type")}, "token_present": True, "notion_version": NOTION_VERSION}

@app.get("/notion/databases")
async def list_databases(page_size: int = 50):
    """
    Liste les databases accessibles au bot (search).
    """
    payload = {"filter": {"value": "database", "property": "object"}, "page_size": page_size}
    data = await notion_post("/search", payload)

    dbs = []
    for item in data.get("results", []):
        title = ""
        tarr = item.get("title", [])
        if tarr and isinstance(tarr, list):
            title = "".join([x.get("plain_text", "") for x in tarr if isinstance(x, dict)])
        dbs.append({
            "id": item.get("id"),
            "title": title,
            "url": item.get("url"),
            "last_edited_time": item.get("last_edited_time"),
        })
    return {"count": len(dbs), "databases": dbs}

@app.get("/notion/database/{db_id}")
async def get_database(db_id: str):
    """
    GET via path param (Swagger parfois relou). On garde quand même.
    """
    nid = normalize_notion_id(db_id)
    data = await notion_get(f"/databases/{nid}")

    # Titre lisible
    title = ""
    tarr = data.get("title", [])
    if tarr and isinstance(tarr, list):
        title = "".join([x.get("plain_text", "") for x in tarr if isinstance(x, dict)])

    # Properties brutes
    return {
        "id": data.get("id"),
        "title": title,
        "url": data.get("url"),
        "properties": data.get("properties", {}),
    }

@app.get("/notion/database")
async def get_database_q(db_id: str = Query(..., description="ID ou URL notion")):
    """
    Même chose, mais en query param pour éviter les soucis Swagger.
    Exemple: /notion/database?db_id=17631dd2-...
    """
    return await get_database(db_id)

async def find_or_create_today_page(db_id: str) -> str:
    """
    Cherche la page dont la propriété 'Date' == aujourd'hui.
    Si absente, la crée. Retourne page_id.
    """
    today = today_iso()
    payload = {
        "filter": {
            "property": "Date",
            "date": {"equals": today}
        }
    }
    res = await notion_post(f"/databases/{db_id}/query", payload)
    results = res.get("results", [])
    if results:
        return results[0]["id"]

    # Créer une page du jour
    create_payload = {
        "parent": {"database_id": db_id},
        "properties": {
            "Date": {"date": {"start": today}},
            ".": {"title": [{"type": "text", "text": {"content": today}}]},
        },
    }
    created = await notion_post("/pages", create_payload)
    return created["id"]

@app.post("/habits/today")
async def update_habits_today(body: HabitsUpdate):
    """
    Crée/charge la ligne du jour dans HABITS_DB_ID puis coche les cases.
    """
    if not HABITS_DB_ID:
        raise HTTPException(status_code=500, detail="HABITS_DB_ID manquant (variable d'environnement).")

    db_id = normalize_notion_id(HABITS_DB_ID)
    page_id = await find_or_create_today_page(db_id)

    props: Dict[str, Any] = {}

    # mapping Pydantic -> noms Notion exacts
    if body.Meditation is not None:
        props["Méditation"] = {"checkbox": body.Meditation}
    if body.Bonne_Alimentation is not None:
        props["Bonne Alimentation"] = {"checkbox": body.Bonne_Alimentation}
    if body.Sport_Marche is not None:
        props["Sport / Marche"] = {"checkbox": body.Sport_Marche}
    if body.Deep_Focus is not None:
        props["Deep Focus"] = {"checkbox": body.Deep_Focus}
    if body.Lecture is not None:
        props["Lecture"] = {"checkbox": body.Lecture}
    if body.Jour is not None:
        props["Jour "] = {"rich_text": [{"type": "text", "text": {"content": body.Jour}}]}
    if body.Title is not None:
        props["."] = {"title": [{"type": "text", "text": {"content": body.Title}}]}

    if not props:
        return {"ok": True, "page_id": page_id, "message": "Aucune propriété à mettre à jour."}

    updated = await notion_patch(f"/pages/{page_id}", {"properties": props})
    return {"ok": True, "page_id": updated.get("id")}

# Optionnel: health endpoint
@app.get("/health")
async def health():
    return {"ok": True, "token_present": bool(NOTION_TOKEN), "habits_db_id": HABITS_DB_ID or None}
