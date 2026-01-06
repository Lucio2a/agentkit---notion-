import os
from fastapi import FastAPI, HTTPException
from notion_client import Client

app = FastAPI()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

# Initialise Notion seulement si les variables existent
notion = Client(auth=NOTION_TOKEN) if NOTION_TOKEN else None


def require_env():
    if notion is None or not NOTION_DATABASE_ID:
        raise HTTPException(
            status_code=500,
            detail="Missing NOTION_TOKEN or NOTION_DATABASE_ID",
        )


def get_title_property_name(database_id: str) -> str:
    """
    Retourne le nom de la propriété Notion de type 'title' (ex: 'Nom').
    """
    db = notion.databases.retrieve(database_id=database_id)
    props = db.get("properties", {})
    for prop_name, prop in props.items():
        if prop.get("type") == "title":
            return prop_name
    raise ValueError("No title property found in database (API: type 'title')")


@app.get("/")
def root():
    return {"status": "ok"}


@app.get("/notion/test")
def notion_test():
    require_env()
    try:
        title_prop = get_title_property_name(NOTION_DATABASE_ID)
        return {
            "status": "ok",
            "database_id": NOTION_DATABASE_ID,
            "title_property": title_prop,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/notion/read")
def notion_read():
    require_env()
    try:
        title_prop = get_title_property_name(NOTION_DATABASE_ID)

        res = notion.databases.query(
            database_id=NOTION_DATABASE_ID,
            page_size=5,
        )

        items = []
        for page in res.get("results", []):
            props = page.get("properties", {})
            title_arr = props.get(title_prop, {}).get("title", [])
            title_text = "".join([t.get("plain_text", "") for t in title_arr]) if title_arr else ""
            items.append({"page_id": page.get("id"), "title": title_text})

        return {
            "database_id": NOTION_DATABASE_ID,
            "title_property": title_prop,
            "count": len(items),
            "items": items,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/notion/write")
def notion_write():
    require_env()
    try:
        title_prop = get_title_property_name(NOTION_DATABASE_ID)
        content = "TEST - création via Render"

        created = notion.pages.create(
            parent={"database_id": NOTION_DATABASE_ID},
            properties={
                title_prop: {
                    "title": [{"text": {"content": content}}]
                }
            },
        )

        return {
            "status": "created",
            "page_id": created.get("id"),
            "title_property": title_prop,
            "title": content,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
