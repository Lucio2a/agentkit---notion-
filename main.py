import os
import datetime as dt
from typing import Optional, Dict, Any

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

NOTION_TOKEN = os.getenv("NOTION_TOKEN", "").strip()
HABITS_DB_ID = os.getenv("HABITS_DB_ID", "").strip()  # ex: 17631dd2-32a7-81fa-ac05-f7ecc79035b8
NOTION_VERSION = os.getenv("NOTION_VERSION", "2022-06-28").strip()

NOTION_API = "https://api.notion.com/v1"


def notion_headers() -> Dict[str, str]:
    if not NOTION_TOKEN:
        raise HTTPException(status_code=500, detail="NOTION_TOKEN manquant (variable d'environnement).")
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def notion_get(path: str) -> Dict[str, Any]:
    r = requests.get(f"{NOTION_API}{path}", headers=notion_headers(), timeout=30)
    if not r.ok:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()


def notion_post(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    r = requests.post(f"{NOTION_API}{path}", headers=notion_headers(), json=payload, timeout=30)
    if not r.ok:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()


def notion_patch(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    r = requests.patch(f"{NOTION_API}{path}", headers=notion_headers(), json=payload, timeout=30)
    if not r.ok:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()


class HabitsUpdate(BaseModel):
    # Tu peux envoyer meditation/sport/deep_focus/lecture/alimentation en true/false
    checks: Dict[str, bool] = Field(default_factory=dict)
    jour: Optional[str] = None  # optionnel : texte dans la propriété "Jour "


app = FastAPI(title="Notion backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    # petit ping + db id si dispo
    return {"status": "Notion backend OK", "habits_db_id": HABITS_DB_ID or None}


@app.get("/notion/test")
def notion_test():
    # vérifie token + bot user
    data = notion_get("/users/me")
    return {"ok": True, "user": {"id": data.get("id"), "name": data.get("name"), "type": data.get("type")}, "token_present": bool(NOTION_TOKEN), "notion_version": NOTION_VERSION}


@app.get("/notion/databases")
def list_databases(page_size: int = 30):
    # Search Notion: filter object=database
    payload = {"filter": {"value": "database", "property": "object"}, "page_size": min(max(page_size, 1), 100)}
    data = notion_post("/search", payload)

    items = []
    for r in data.get("results", []):
        title = ""
        t = r.get("title", [])
        if t and isinstance(t, list):
            title = "".join([x.get("plain_text", "") for x in t])

        items.append({
            "id": r.get("id"),
            "title": title,
            "url": r.get("url"),
            "last_edited_time": r.get("last_edited_time"),
        })

    return {"count": len(items), "databases": items}


@app.get("/notion/database/{db_id}")
def get_database(db_id: str):
    return notion_get(f"/databases/{db_id}")


def normalize_checks(checks: Dict[str, bool]) -> Dict[str, bool]:
    """
    Accepte plusieurs noms côté user, map vers TES propriétés Notion exactes.
    """
    # clés user -> propriété Notion
    mapping = {
        "meditation": "Méditation",
        "méditation": "Méditation",

        "sport": "Sport / Marche",
        "sport_marche": "Sport / Marche",
        "sport/marche": "Sport / Marche",

        "deep_focus": "Deep Focus",
        "focus": "Deep Focus",
        "deepfocus": "Deep Focus",

        "lecture": "Lecture",

        "alimentation": "Bonne Alimentation",
        "bonne_alimentation": "Bonne Alimentation",
    }

    out: Dict[str, bool] = {}
    for k, v in checks.items():
        kk = (k or "").strip().lower()
        if kk in mapping:
            out[mapping[kk]] = bool(v)
    return out


def find_today_page(database_id: str, iso_date: str) -> Optional[str]:
    """
    Cherche une page dans la database avec Date == aujourd'hui.
    Renvoie page_id si trouvé.
    """
    payload = {
        "filter": {
            "property": "Date",
            "date": {"equals": iso_date}
        },
        "page_size": 1
    }
    data = notion_post(f"/databases/{database_id}/query", payload)
    results = data.get("results", [])
    if results:
        return results[0].get("id")
    return None


@app.post("/habits/today")
def habits_today(body: HabitsUpdate):
    if not HABITS_DB_ID:
        raise HTTPException(status_code=500, detail="HABITS_DB_ID manquant (variable d'environnement).")

    today = dt.date.today()
    iso_date = today.isoformat()

    # Map checks -> propriétés Notion
    checks_props = normalize_checks(body.checks)

    # construit le payload properties
    props: Dict[str, Any] = {
        "Date": {"date": {"start": iso_date}},
    }

    # title obligatoire (ta propriété title s'appelle "." dans ton schema)
    props["."] = {"title": [{"type": "text", "text": {"content": iso_date}}]}

    # optionnel: Jour
    if body.jour is not None:
        props["Jour "] = {"rich_text": [{"type": "text", "text": {"content": body.jour}}]}

    # checkboxes
    for notion_prop_name, val in checks_props.items():
        props[notion_prop_name] = {"checkbox": bool(val)}

    # create or update
    page_id = find_today_page(HABITS_DB_ID, iso_date)

    if page_id:
        updated = notion_patch(f"/pages/{page_id}", {"properties": props})
        return {"mode": "updated", "page_id": page_id, "url": updated.get("url")}
    else:
        created = notion_post("/pages", {"parent": {"database_id": HABITS_DB_ID}, "properties": props})
        return {"mode": "created", "page_id": created.get("id"), "url": created.get("url")}
