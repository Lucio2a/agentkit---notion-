from notion_client import Client
import os

notion = Client(auth=os.environ["NOTION_TOKEN"])

DATABASE_ID = os.environ["NOTION_DATABASE_ID"]

notion.pages.create(
    parent={"database_id": DATABASE_ID},
    properties={
        "Name": {
            "title": [
                {"text": {"content": "TEST API – création automatique"}}
            ]
        }
    }
)

print("OK écriture")
