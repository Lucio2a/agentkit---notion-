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


@app.get("/notion/read")
def read_database():
    try:
        response = notion.databases.query(
            database_id=NOTION_DATABASE_ID
        )
        return response
    except Exception as e:
        return {"error": str(e)}


@app.get("/notion/write")
def write_database():
    try:
        response = notion.pages.create(
            parent={"database_id": NOTION_DATABASE_ID},
            properties={
                "Mission": {
                    "title": [
                        {
                            "text": {
                                "content": "Test automatique depuis Render"
                            }
                        }
                    ]
                }
            }
        )
        return response
    except Exception as e:
        return {"error": str(e)}
