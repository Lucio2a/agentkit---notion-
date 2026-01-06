from fastapi import FastAPI
import os
from notion_client import Client

app = FastAPI()

notion = Client(auth=os.environ["NOTION_TOKEN"])
DATABASE_ID = os.environ["NOTION_DATABASE_ID"]


def get_title_property_name(database):
    for name, prop in database["properties"].items():
        if prop["type"] == "title":
            return name
    return None


@app.get("/notion/read")
def read_database():
    db = notion.databases.retrieve(database_id=DATABASE_ID)
    title_prop = get_title_property_name(db)

    if not title_prop:
        return {"error": "No title property found in database"}

    results = notion.databases.query(database_id=DATABASE_ID)

    items = []
    for page in results["results"]:
        title = page["properties"][title_prop]["title"]
        text = title[0]["plain_text"] if title else ""
        items.append(text)

    return {
        "database": db["title"][0]["plain_text"],
        "count": len(items),
        "items": items
    }
