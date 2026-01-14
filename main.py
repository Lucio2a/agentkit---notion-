import os
import json
from typing import Any, Dict, List, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from notion_client import Client


# -----------------------
# Config
# -----------------------
NOTION_TOKEN = os.getenv("NOTION_TOKEN", "").strip()
NOTION_VERSION = os.getenv("NOTION_VERSION", "2022-06-28").strip()

DB_REGISTRY_PATH = os.getenv("DB_REGISTRY_PATH", "db_registry.json").strip()

app = FastAPI(title="Notion backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ajuste si besoin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if not NOTION_TOKEN:
    # On laisse l'app démarrer, mais les routes notion renverront une erreur claire
    notion = None
else:
    notion = Client(auth=NOTION_TOKEN, notion_version=NOTION_VERSION)


# -----------------------
# Helpers
# -----------------------
def _ensure_notion():
    if notion is None:
        raise HTTPException(
            status_code=500,
            detail="NOTION_TOKEN manquant. Configure NOTION_TOKEN côté Render.",
        )


def _load_registry() -> Dict[str, Any]:
    if not os.path.exists(DB_REGISTRY_PATH):
        return {
            "generated_at": None,
            "count": 0,
            "databases": [],
            "by_id": {},
            "by_title": {},
        }
    try:
        with open(DB_REGISTRY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Registry illisible: {e}")


def _save_registry(reg: Dict[str, Any]) -> None:
    try:
        with open(DB_REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(reg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Impossible de sauver registry: {e}")


def _extract_title(db_obj: Dict[str, Any]) -> str:
    # Notion database title = list of rich_text fragments
    title_parts = db_obj.get("title", [])
    if not title_parts:
        return ""
    return "".join([t.get("plain_text", "") for t in title_parts]).strip()


def _normalize(s: str) -> str:
    return (s or "").strip().lower()


def _search_all_databases() -> List[Dict[str, Any]]:
    """
    Stratégie robuste: utiliser notion.search pour récupérer les databases accessibles
    (toutes celles partagées à l'intégration).
    """
    _ensure_notion()

    results: List[Dict[str, Any]] = []
    start_cursor: Optional[str] = None

    while True:
        payload: Dict[str, Any] = {
            "page_size": 100,
            "filter": {"property": "object", "value": "database"},
        }
        if start_cursor:
            payload["start_cursor"] = start_cursor

        resp = notion.search(**payload)
        batch = resp.get("results", [])
        results.extend(batch)

        if not resp.get("has_more"):
            break
        start_cursor = resp.get("next_cursor")

    return results


# -----------------------
# Routes
# -----------------------
@app.get("/")
def root():
    reg = _load_registry()
    return {
        "status": "Notion backend OK",
        "notion_version": NOTION_VERSION,
        "registry_count": reg.get("count", 0),
        "registry_generated_at": reg.get("generated_at"),
    }


@app.get("/notion/test")
def notion_test():
    _ensure_notion()
    me = notion.users.me()
    return {
        "ok": True,
        "user": {
            "id": me.get("id"),
            "name": me.get("name"),
            "type": me.get("type"),
        },
        "token_present": True,
        "notion_version": NOTION_VERSION,
    }


@app.post("/notion/bootstrap")
def notion_bootstrap():
    """
    Scanne toutes les databases accessibles par l'intégration et construit un registre local.
    """
    _ensure_notion()

    dbs = _search_all_databases()

    items: List[Dict[str, Any]] = []
    by_id: Dict[str, Dict[str, Any]] = {}
    by_title: Dict[str, List[str]] = {}

    for db in dbs:
        db_id = db.get("id")
        title = _extract_title(db)
        url = db.get("url")
        last_edited_time = db.get("last_edited_time")

        item = {
            "id": db_id,
            "title": title,
            "url": url,
            "last_edited_time": last_edited_time,
        }
        items.append(item)
        by_id[db_id] = item

        tkey = _normalize(title)
        if tkey not in by_title:
            by_title[tkey] = []
        by_title[tkey].append(db_id)

    reg = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "count": len(items),
        "databases": items,
        "by_id": by_id,
        "by_title": by_title,
    }

    _save_registry(reg)
    return reg


@app.get("/notion/registry")
def notion_registry():
    return _load_registry()


@app.get("/notion/resolve")
def notion_resolve(
    title: str = Query(..., description="Titre exact ou partiel de la database"),
    contains: bool = Query(True, description="True = recherche partielle, False = exact"),
):
    reg = _load_registry()
    items: List[Dict[str, Any]] = reg.get("databases", [])
    if not items:
        raise HTTPException(status_code=400, detail="Registry vide. Lance POST /notion/bootstrap.")

    q = _normalize(title)

    if not contains:
        # Exact
        ids = reg.get("by_title", {}).get(q, [])
        return {"query": title, "matches": [reg["by_id"][i] for i in ids]}

    # Partiel
    matches = [it for it in items if q in _normalize(it.get("title", ""))]
    return {"query": title, "matches": matches}


@app.get("/notion/database/{db_id}")
def get_database(db_id: str):
    """
    Retourne le schema (properties) de la database.
    """
    _ensure_notion()
    try:
        db = notion.databases.retrieve(database_id=db_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Database introuvable: {e}")

    props = db.get("properties", {})
    return {
        "id": db.get("id"),
        "title": _extract_title(db),
        "url": db.get("url"),
        "properties": props,
    }
