import os
from datetime import datetime
from fastapi import FastAPI, HTTPException
from notion_client import Client

app = FastAPI()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
# On met ton Database ID en fallback (comme ça tu ne le rerentres pas partout)
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID") or "da575a035de84a3b8550e72e774cc292"

if not NOTION_TOKEN:
    raise RuntimeError("NOTION_TOKEN manquant dans les variables d'environnement Render.")

notion = Client(auth=NOTION_TOKEN)

_title_prop_cache = None

def get_title_prop_name() -> str:
    global _title_prop_cache
    if _title_prop_cache:
        return _title_prop_cache

    db = notion.databases.retrieve(database_id=NOTION_DATABASE_ID)
    props = db.get("properties", {})
    for name, meta in props.items():
        if meta.get("type") == "title":
            _title_prop_cache = name
            return name
    raise RuntimeError("Aucune propriété de type 'title' trouvée dans la database Notion.")


@app.get("/")
def root():
    return {"status": "ok", "service": "coach-notion"}


@app.get("/notion/test")
def notion_test():
    return {"status": "agent notion ok"}


@app.get("/notion/read")
def notion_read():
    try:
        db = notion.databases.retrieve(database_id=NOTION_DATABASE_ID)
        title_prop = get_title_prop_name()

        # On récupère aussi 3 pages (si tu veux voir que ça lit vraiment)
        pages = notion.databases.query(database_id=NOTION_DATABASE_ID, page_size=3)

        return {
            "database_id": db.get("id"),
            "database_title": db.get("title", []),
            "title_property_name": title_prop,
            "sample_pages_count": len(pages.get("results", [])),
            "sample_pages": [
                {
                    "id": p.get("id"),
                    "url": p.get("url"),
                }
                for p in pages.get("results", [])
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/notion/write")
def notion_write():
    try:
        title_prop = get_title_prop_name()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        new_page = notion.pages.create(
            parent={"database_id": NOTION_DATABASE_ID},
            properties={
                title_prop: {
                    "title": [
                        {"text": {"content": f"Test API - {now}"}}
                    ]
                }
            },
        )

        return {
            "ok": True,
            "created_page_id": new_page.get("id"),
            "created_page_url": new_page.get("url"),
            "used_title_property": title_prop,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
