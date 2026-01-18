# Notion Write Service

Service minimaliste qui reçoit **UNE requête HTTP** et écrit dans Notion
en résolvant automatiquement la destination depuis la page racine
**"Liberté financières"** (sans ID hardcodé).

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

### Créer une page enfant sous "Liberté financières"

```bash
curl -X POST "$BASE_URL/write" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Nouvelle page",
    "content": "Ajoutée sous la page racine."
  }'
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
