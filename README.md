# Notion Write Service

Backend minimaliste qui reçoit des commandes JSON simples et écrit dans Notion
en résolvant automatiquement le schéma, sans exposer les types Notion aux utilisateurs.

## Configuration

Variables d'environnement requises :

- `NOTION_TOKEN` : token d'intégration Notion

## Commande de démarrage (Render)

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

## Endpoint

### `POST /write`

Input JSON :

```json
{
  "title": "string",
  "content": "string (optionnel)",
  "target_name": "Nom d’une database enfant (optionnel)"
}
```

Retour :

```json
{
  "status": "ok",
  "page_id": "...",
  "page_url": "..."
}
```

### `GET /read`

Retourne des informations simples sur la page racine et ses databases enfants :

```json
{
  "status": "ok",
  "root": { "id": "...", "title": "...", "type": "page" },
  "children": [{ "id": "...", "title": "...", "type": "database" }]
}
```

## Logique Notion

1. Trouve la page racine nommée exactement **"Liberté financières"**.
2. Liste ses databases enfants (pagination gérée).
3. Si `target_name` correspond au nom d'une database enfant, écrit dedans.
4. Sinon, crée une page enfant sous **"Liberté financières"**.

## Exemples curl

### Écrire dans une database enfant nommée "Journal"

```bash
curl -X POST "$BASE_URL/write" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Entrée du jour",
    "content": "Contenu de test",
    "target_name": "Journal"
  }'
```

### Lire la page racine

```bash
curl "$BASE_URL/read"
```

### Créer une page enfant sous "Liberté financières"

```bash
curl -X POST "$BASE_URL/write" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Nouvelle page",
    "content": "Ajoutée sous la page racine."
  }'
```

## Nouveaux endpoints (GPT Actions)

### `POST /command`

Permet d'exécuter une action métier sans fournir le schéma Notion.

### `GET /schema`

Renvoie le schéma d'une database (propriétés, types et options).

### `POST /resolve`

Résout une database ou une page depuis la page racine.

### `POST /database_query`

Interroge une database avec pagination.

### `GET /health` / `GET /notion/ping`

Checks de santé et ping Notion.

### `POST /selftest`

Exécute 3 tests réels (schema, query, update checkbox) avec les variables
`DATABASE_ID_TEST`, `PAGE_ID_TEST`, `PROP_CHECKBOX_TEST`.

Tant que `/selftest` n'est pas en **PASS**, n'utilisez pas les endpoints métiers.

## OpenAPI

Le fichier `openapi.yaml` contient le schéma OpenAPI 3.1 pour GPT Actions.

## Exemples JSON (fonctionnels)

### 1) Cocher une checkbox

```json
{
  "action": "update_page",
  "page_id": "PAGE_ID",
  "props": {
    "Done": true
  }
}
```

### 2) Select / multi-select (options existantes)

```json
{
  "action": "update_page",
  "page_id": "PAGE_ID",
  "props": {
    "Status": "Done",
    "Tags": ["Crypto", "Trading"]
  }
}
```

Si une option n'existe pas, le backend renvoie une erreur claire `VALIDATION`.

### 3) Append un paragraphe

```json
{
  "action": "update_page",
  "page_id": "PAGE_ID",
  "content_append": [
    { "type": "paragraph", "text": "Texte à ajouter" }
  ]
}
```

## Appel depuis un GPT custom

Exemple d'appel HTTP (action externe) :

```http
POST https://VOTRE-SERVICE.onrender.com/write
Content-Type: application/json

{
  "title": "Note via GPT",
  "content": "Créée par un appel custom.",
  "target_name": "Journal"
}
```
