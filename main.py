import os
from fastapi import FastAPI, HTTPException
from notion_client import Client

app = FastAPI()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

notion = Client(auth=NOTION_TOKEN) if (NOTION_TOKEN and NOTION_DATABASE_ID) else None

def get_title_property_name(database_id: str) -> str:
    if notion is None:
        raise ValueError("Missing NOTION_TOKEN or NOTION_DATABASE_ID")

    db = notion.databases.retrieve(database_id=database_id)
    props = db.get("properties", {})
    for prop_name, prop in props.items():
        if prop.get("type") == "title":
            return prop_name

    raise ValueError("No title property found in database (API: type 'title')")

@app.get("/notion/test")
def notion_test():
    if notion is None:
        raise HTTPException(status_code=500, detail="Missing NOTION_TOKEN or NOTION_DATABASE_ID")
    try:
        title_prop = get_title_property_name(NOTION_DATABASE_ID)
        return {"status": "ok", "database_id": NOTION_DATABASE_ID, "title_property": title_prop}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/notion/read")
def notion_read():
    if notion is None:
        raise HTTPException(status_code=500, detail="Missing NOTION_TOKEN or NOTION_DATABASE_ID")
    try:
        title_prop = get_title_property_name(NOTION_DATABASE_ID)
        res = notion.databases.query(database_id=NOTION_DATABASE_ID, page_size=5)
        items = []
        for page in res.get("results", []):
            title_obj = page.get("properties", {}).get(title_prop, {}).get("title", [])
            title_text = "".join([t.get("plain_text", "") for t in title_obj]) if title_obj else ""
            items.append({"page_id": page.get("id"), "title": title_text})
        return {"database_id": NOTION_DATABASE_ID, "title_property": title_prop, "items": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/notion/write")
def notion_write():
    if notion is None:
        raise HTTPException(status_code=500, detail="Missing NOTION_TOKEN or NOTION_DATABASE_ID")
    try:
        title_prop = get_title_property_name(NOTION_DATABASE_ID)
        content = "TEST - création via Render"
        created = notion.pages.create(
            parent={"database_id": NOTION_DATABASE_ID},
            properties={title_prop: {"title": [{"text": {"content": content}}]}},
        )
        return {"status": "created", "page_id": created.get("id"), "title": content, "title_property": title_prop}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
