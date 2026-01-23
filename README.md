# Notion Command Backend

Backend minimaliste pour piloter Notion via GPT Actions.

## Configuration

Variables d'environnement :

- `NOTION_TOKEN` (ou `NOTION_API_KEY`, `NOTION_SECRET`, `NOTION_ACCESS_TOKEN`) : token d'intégration Notion.
- `ROOT_PAGE_ID` (optionnel) : page racine pour la navigation.

## Démarrage (Render)

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

## Endpoints exposés

- `GET /health`
- `GET /notion/ping`
- `POST /selftest` (sans body)
- `POST /command`

Toutes les autres routes historiques restent accessibles mais sont masquées de l'OpenAPI.

## Format `/command`

```json
{
  "action": "page.update",
  "params": {
    "page_id": "PAGE_ID",
    "properties": {
      "Done": true
    }
  }
}
```

Retour standard :

- OK: `{ "status": "ok", "result": ..., "meta": ... }`
- FAIL: `{ "status": "fail", "reason": "...", "details": ... }`

## Exemples minimaux

### Lire une page

```json
{
  "action": "page.read",
  "params": { "page_id": "PAGE_ID" }
}
```

### Mettre à jour une checkbox

```json
{
  "action": "page.update",
  "params": {
    "page_id": "PAGE_ID",
    "properties": { "Done": true }
  }
}
```

### Lister les databases accessibles

```json
{
  "action": "db.list",
  "params": { "page_size": 20 }
}
```

### Ajouter un bloc

```json
{
  "action": "block.append",
  "params": {
    "block_id": "PAGE_OR_BLOCK_ID",
    "blocks": [{ "type": "paragraph", "text": "Texte à ajouter" }]
  }
}
```

## Selftest

`POST /selftest` auto-découvre une database accessible, query 1 page, modifie une propriété
(checkbox > title/rich_text), relit la page et valide la modification. Aucun paramètre requis.

## OpenAPI

Le fichier `openapi.yaml` expose uniquement les 4 endpoints ci-dessus.
