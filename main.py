import os
from fastapi import FastAPI
from notion_client import Client

app = FastAPI()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

notion = Client(auth=NOTION_TOKEN)

@app.get("/")
def root():
    return {"status": "agent notion ok"}

@app.get("/health")
def health():
    return {"health": "ok"}

@app.get("/notion/test")
def test_notion():
    db = notion.databases.retrieve(database_id=NOTION_DATABASE_ID)
    return {
        "database_id": db["id"],
        "title": db["title"][0]["plain_text"] if db["title"] else "no title"
    }
