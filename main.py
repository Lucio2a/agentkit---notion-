import os
from fastapi import FastAPI, HTTPException
from notion_client import Client


app = FastAPI()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

if not NOTION_TOKEN or not NOTION_DATABASE_ID:
    # On laisse l'app démarrer mais on renverra une erreur claire aux endpoints Notion
    pass

notion = Client(auth=NOTION_TOKEN) if NOTION_TOKEN else None


def _require_env():
    if not NOTION_TOKEN or not NOTION_DATABASE_ID:
        raise HTTPException(
            status_code=500,
            detail="Missing env vars: NOTION_TOKEN and/or NOTION_DATABASE_ID"
        )
    if notion is None:
        raise HTTPException(status_code=500, detail="Notion client not initialized")


def _get_title_property_name() -> str:
    """
    Récupère le nom exact de la propriété Title (type 'title') dans la database Notion.
    Ça évite 100% les erreurs 'Aucune propriété de type title trouvée'.
    """
    db = notion.databases.retrieve(database_id=NOTION_DATABASE_ID)
    props = db.get("properties", {})

    for name, meta in props.items():
        if meta.get("type") == "title":
            return name

    raise HTTPException(
        status_code=500,
        detail="No 'title' property found in this database (Notion schema)."
    )


@app.get("/")
def root():
    return {"status": "ok"}


@app.get("/notion/test")
def notion_test():
    _require_env()
    try:
        # Simple ping
        me = notion.users.me()
        return {"status": "agent notion ok", "notion_user": me.get("name", "unknown")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/notion/read")
def notion_read():
    _require_env()
    try:
        pages = notion.databases.query(
            database_id=NOTION_DATABASE_ID,
            page_size=5
        )

        results = []
        for p in pages.get("results", []):
            results.append({
                "id": p.get("id"),
                "url": p.get("url"),
                "properties": p.get("properties", {})
            })

        return {
            "ok": True,
            "database_id": NOTION_DATABASE_ID,
            "pages_count": len(results),
            "pages": results
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/notion/write")
def notion_write():
    _require_env()
    try:
        title_prop = _get_title_property_name()

        created = notion.pages.create(
            parent={"database_id": NOTION_DATABASE_ID},
            properties={
                title_prop: {
                    "title": [{"type": "text", "text": {"content": "Test Agent"}}]
                }
            }
        )

        return {
            "ok": True,
            "created_page_id": created.get("id"),
            "created_page_url": created.get("url"),
            "title_property_used": title_prop
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
