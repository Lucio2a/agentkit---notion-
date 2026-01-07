import os
from fastapi import FastAPI, HTTPException
from notion_client import Client

app = FastAPI()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")  # peut être DB id OU page url id
notion = Client(auth=NOTION_TOKEN) if NOTION_TOKEN else None


def _require_env():
    if notion is None:
        raise HTTPException(status_code=500, detail="Missing NOTION_TOKEN")
    if not NOTION_DATABASE_ID:
        raise HTTPException(status_code=500, detail="Missing NOTION_DATABASE_ID")


def _get_db_and_optional_data_source_id(db_id: str):
    """
    Retourne:
      - db (objet database)
      - data_source_id (str | None)
    """
    db = notion.databases.retrieve(database_id=db_id)
    data_sources = db.get("data_sources") or []
    data_source_id = data_sources[0]["id"] if data_sources else None
    return db, data_source_id


def _get_title_property_name_from_properties(props: dict) -> str:
    for prop_name, prop in (props or {}).items():
        if prop.get("type") == "title":
            return prop_name
    raise ValueError("No title property found (type 'title')")


def _get_schema_title_prop(db_id: str):
    """
    Cas 1: DB classique -> db.properties existe
    Cas 2: Data Source -> récupérer les propriétés via notion.data_sources.retrieve
    """
    db, data_source_id = _get_db_and_optional_data_source_id(db_id)

    # Cas classique
    if "properties" in db and db["properties"]:
        title_prop = _get_title_property_name_from_properties(db["properties"])
        return {"mode": "database", "title_prop": title_prop, "data_source_id": None}

    # Cas data_source
    if data_source_id and hasattr(notion, "data_sources"):
        ds = notion.data_sources.retrieve(data_source_id=data_source_id)
        props = ds.get("properties", {})
        title_prop = _get_title_property_name_from_properties(props)
        return {"mode": "data_source", "title_prop": title_prop, "data_source_id": data_source_id}

    raise ValueError("No properties found: database has no properties and no usable data_source schema")


@app.get("/notion/test")
def notion_test():
    _require_env()
    try:
        info = _get_schema_title_prop(NOTION_DATABASE_ID)
        return {"status": "ok", "id": NOTION_DATABASE_ID, **info}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/notion/read")
def notion_read():
    _require_env()
    try:
        info = _get_schema_title_prop(NOTION_DATABASE_ID)
        mode = info["mode"]
        title_prop = info["title_prop"]

        if mode == "database":
            res = notion.databases.query(database_id=NOTION_DATABASE_ID, page_size=5)
        else:
            # data_source
            res = notion.data_sources.query(data_source_id=info["data_source_id"], page_size=5)

        items = []
        for page in res.get("results", []):
            props = page.get("properties", {})
            title_obj = props.get(title_prop, {}).get("title", [])
            title_text = "".join([t.get("plain_text", "") for t in title_obj]) if title_obj else ""
            items.append({"page_id": page.get("id"), "title": title_text})

        return {"mode": mode, "title_property": title_prop, "items": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/notion/write")
def notion_write():
    _require_env()
    try:
        info = _get_schema_title_prop(NOTION_DATABASE_ID)
        mode = info["mode"]
        title_prop = info["title_prop"]
        content = "TEST - création via Render"

        if mode == "database":
            parent = {"database_id": NOTION_DATABASE_ID}
        else:
            parent = {"data_source_id": info["data_source_id"]}

        created = notion.pages.create(
            parent=parent,
            properties={
                title_prop: {"title": [{"text": {"content": content}}]}
            },
        )
        return {"status": "created", "mode": mode, "page_id": created.get("id"), "title": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
