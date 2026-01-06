import os
from fastapi import FastAPI, HTTPException
from notion_client import Client

app = FastAPI()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

if not NOTION_TOKEN:
    raise RuntimeError("Missing NOTION_TOKEN env var")
if not NOTION_DATABASE_ID:
    raise RuntimeError("Missing NOTION_DATABASE_ID env var")

notion = Client(auth=NOTION_TOKEN)


def _get_title_property_name(database: dict) -> str:
    props = database.get("properties", {})
    for name, meta in props.items():
        if meta.get("type") == "title":
            return name
    raise ValueError("No title property found in database")


@app.get("/notion/test")
def notion_test():
    return {"status": "agent notion ok"}


@app.get("/notion/read")
def notion_read():
    try:
        db = notion.databases.retrieve(database_id=NOTION_DATABASE_ID)
        title_prop = _get_title_property_name(db)

        res = notion.databases.query(database_id=NOTION_DATABASE_ID, page_size=10)

        pages = []
        for p in res.get("results", []):
            title_parts = p.get("properties", {}).get(title_prop, {}).get("title", [])
            title = "".join([t.get("plain_text", "") for t in title_parts]).strip()
            pages.append({"id": p.get("id"), "title": title})

        return {"database_id": NOTION_DATABASE_ID, "title_property": title_prop, "count": len(pages), "pages": pages}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/notion/write")
def notion_write():
    """
    Crée UNE page dans la database.
    (On force un parent database_id => plus jamais 'undefined')
    """
    try:
        db = notion.databases.retrieve(database_id=NOTION_DATABASE_ID)
        title_prop = _get_title_property_name(db)

        created = notion.pages.create(
            parent={"database_id": NOTION_DATABASE_ID},
            properties={
                title_prop: {
                    "title": [
                        {"type": "text", "text": {"content": "Test - création depuis Render"}}
                    ]
                }
            },
        )
        return {"status": "ok", "created_page_id": created.get("id")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
