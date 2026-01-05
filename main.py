import os
from fastapi import FastAPI
from notion_client import Client

app = FastAPI()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")

# ⚠️ DATABASE ID EN DUR (celui de ta capture)
NOTION_DATABASE_ID = "da575a035de84a3b8550e72e774cc292"

notion = Client(auth=NOTION_TOKEN)

@app.get("/")
def root():
    return {"status": "agent notion ok"}

@app.get("/notion/read")
def read_database():
    db = notion.databases.retrieve(database_id=NOTION_DATABASE_ID)
    return {
        "database_id": db["id"],
        "title": db["title"]
    }

@app.get("/notion/write")
def write_test():
    page = notion.pages.create(
        parent={"database_id": NOTION_DATABASE_ID},
        properties={
            "Name": {
                "title": [
                    {"text": {"content": "TEST AUTO – MANPI"}}
                ]
            }
        }
    )
    return {"created_page_id": page["id"]}
