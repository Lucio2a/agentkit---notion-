@app.get("/notion/read")
def notion_read(page_size: int = Query(5, ge=1, le=50)):
    _ensure_notion()
    try:
        effective_id, mode, db = _resolve_database_id(NOTION_DATABASE_ID)
        title_prop = _get_title_property_name(db)
        
        # Utilise requests au lieu de notion.databases.query
        import requests
        headers = {
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json"
        }
        url = f"https://api.notion.com/v1/databases/{effective_id}/query"
        response = requests.post(url, headers=headers, json={"page_size": page_size})
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=response.text)
        
        res = response.json()
        
        items = []
        for page in res.get("results", []) or []:
            page_id = page.get("id")
            title = _plain_title_from_page(page, title_prop)
            url = page.get("url") or f"https://www.notion.so/{page_id.replace('-', '')}"
            items.append({"page_id": page_id, "title": title, "url": url})

        return {
            "status": "success",
            "mode": mode,
            "database_id": NOTION_DATABASE_ID,
            "effective_id": effective_id,
            "count": len(items),
            "items": items,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

**Et ton requirements.txt :**
```
fastapi
uvicorn[standard]
notion-client
requests
