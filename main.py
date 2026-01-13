import os
import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Dict, Optional, List

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Notion backend", version="1.0.0")

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_VERSION = os.getenv("NOTION_VERSION", "2022-06-28")

# DB "Tracker d'habitudes" (d'après ta capture)
HABITS_DB_ID = os.getenv("HABITS_DB_ID", "17631dd2-32a7-81fa-ac05-f7ec79035b8")

TZ = os.getenv("TZ", "Europe/Paris")


# ----------------- Helpers -----------------

def _headers() -> Dict[str, str]:
    if not NOTION_TOKEN:
        raise HTTPException(status_code=500, detail="Missing NOTION_TOKEN (Render env var)")
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _norm(s: str) -> str:
    """Normalize for fuzzy matching: lowercase, no accents, alnum only."""
    s = s.strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s


def _today_iso() -> str:
    now = datetime.now(ZoneInfo(TZ))
    return now.date().isoformat()  # YYYY-MM-DD


def notion_get_database(db_id: str) -> Dict[str, Any]:
    url = f"https://api.notion.com/v1/databases/{db_id}"
    r = requests.get(url, headers=_headers(), timeout=30)
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()


def notion_query_database(db_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    r = requests.post(url, headers=_headers(), json=payload, timeout=30)
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()


def notion_create_page(db_id: str, properties: Dict[str, Any]) -> Dict[str, Any]:
    url = "https://api.notion.com/v1/pages"
    payload = {"parent": {"database_id": db_id}, "properties": properties}
    r = requests.post(url, headers=_headers(), json=payload, timeout=30)
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()


def notion_update_page(page_id: str, properties: Dict[str, Any]) -> Dict[str, Any]:
    url = f"https://api.notion.com/v1/pages/{page_id}"
    payload = {"properties": properties}
    r = requests.patch(url, headers=_headers(), json=payload, timeout=30)
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()


def detect_title_and_date_props(db: Dict[str, Any]) -> Dict[str, str]:
    props = db.get("properties", {})
    title_prop = None
    date_prop = None
    for name, meta in props.items():
        if meta.get("type") == "title":
            title_prop = name
        if meta.get("type") == "date":
            # on prend le 1er date qu'on trouve
            if date_prop is None:
                date_prop = name
    if not title_prop:
        raise HTTPException(status_code=500, detail="No title property found in habits database")
    if not date_prop:
        raise HTTPException(status_code=500, detail="No date property found in habits database")
    return {"title": title_prop, "date": date_prop}


def find_checkbox_props(db: Dict[str, Any]) -> Dict[str, str]:
    """Return mapping normalized_name -> real property name for checkboxes."""
    props = db.get("properties", {})
    out = {}
    for name, meta in props.items():
        if meta.get("type") == "checkbox":
            out[_norm(name)] = name
    return out


def get_or_create_today_page(db_id: str, title_prop: str, date_prop: str) -> Dict[str, Any]:
    today = _today_iso()

    # Find existing page with date == today
    query_payload = {
        "page_size": 1,
        "filter": {
            "property": date_prop,
            "date": {"equals": today},
        },
    }
    data = notion_query_database(db_id, query_payload)
    results = data.get("results", [])
    if results:
        return results[0]

    # Create page for today
    properties = {
        title_prop: {
            "title": [{"type": "text", "text": {"content": today}}],
        },
        date_prop: {
            "date": {"start": today},
        },
    }
    return notion_create_page(db_id, properties)


# ----------------- API Models -----------------

class HabitsUpdate(BaseModel):
    # Ex: {"sport": true, "meditation": false}
    checks: Dict[str, bool]


# ----------------- Endpoints -----------------

@app.get("/")
def root():
    return {"status": "Notion backend OK", "habits_db_id": HABITS_DB_ID}

@app.post("/habits/today")
def habits_today(update: HabitsUpdate):
    """
    Create (if not exists) or update the 'today' page in habits tracker database,
    and apply checkbox states.
    """
    db = notion_get_database(HABITS_DB_ID)
    detected = detect_title_and_date_props(db)
    cb_map = find_checkbox_props(db)

    page = get_or_create_today_page(HABITS_DB_ID, detected["title"], detected["date"])
    page_id = page.get("id")

    # Build properties update for checkboxes
    props_update: Dict[str, Any] = {}
    for k, v in update.checks.items():
        key_norm = _norm(k)
        # try direct match
        real = cb_map.get(key_norm)

        # fallback: match common french names
        # (ex "meditation" should match "meditation", "méditation", etc.)
        if real is None:
            # try partial contains
            for nrm, real_name in cb_map.items():
                if key_norm in nrm or nrm in key_norm:
                    real = real_name
                    break

        if real is None:
            raise HTTPException(
                status_code=400,
                detail=f"Checkbox property not found for '{k}'. Available: {sorted(cb_map.values())}",
            )

        props_update[real] = {"checkbox": bool(v)}

    updated = notion_update_page(page_id, props_update)

    return {
        "status": "success",
        "mode": "habits_today",
        "date": _today_iso(),
        "page_id": updated.get("id"),
        "url": updated.get("url"),
        "applied": update.checks,
    }
