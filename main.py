import os
from fastapi import FastAPI
from notion_client import Client

app = FastAPI()

# === CONFIG NOTION ===
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = "da575a035de84a3b8550e72e774cc292"

notion = Client(auth=NOTION_TOKEN)

# === TEST API ===
@app.get("/")
def root():
    return {"status": "coach notion live"}

@app.get("/notion/test")
def test_notion():
    return {"status": "agent notion ok"}

# === TEST LECTURE DATABASE ===
@app.get("/notion/read")
def read_database():
    response = notion.databases.query(
        database_id=NOTION_DATABASE_ID,
        page_size=5
    )
    return {
        "count": len(response["results"]),
        "pages": response["results"]
    }
