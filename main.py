import os
from fastapi import FastAPI
from notion_client import Client

app = FastAPI()

# ===== CONFIG =====
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID = "da575a035de84a3b8550e72e774cc292"

notion = Client(auth=NOTION_TOKEN)

# ===== TEST API =====
@app.get("/")
def root():
    return {"status": "agent notion ok"}

# ===== READ DATABASE =====
@app.get("/notion/read")
def read_database():
    response = notion.databases.query(
        database_id=DATABASE_ID,
        page_size=10
    )
    return response

# ===== WRITE TEST PAGE =====
@app.get("/notion/write-test")
def write_test():
    page = notion.pages.create(
        parent={"database_id": DATABASE_ID},
        properties={
            "Name": {
                "title": [
                    {"text": {"content": "TEST AUTO – Agent Notion"}}
                ]
            }
        }
    )
    return {"status": "page created", "id": page["id"]}
