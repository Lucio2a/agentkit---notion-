# Notion Agent Orchestrator Backend

Backend simplifié pour piloter Notion via **OpenAI Agents SDK**. L'orchestrateur est l'unique point d'entrée, et toutes les interactions Notion passent par des tools internes (Notion Writer).

## Configuration

Variables d'environnement (existantes) :

- `NOTION_TOKEN` (ou `NOTION_API_KEY`, `NOTION_SECRET`, `NOTION_ACCESS_TOKEN`) : token d'intégration Notion.
- `ROOT_PAGE_ID` (optionnel) : conservé pour compatibilité, non utilisé par l'orchestrateur.

Variables d'environnement OpenAI :

- `OPENAI_API_KEY` : clé API OpenAI.
- `OPENAI_MODEL` (optionnel, défaut: `gpt-4.1-mini`).

## Démarrage (Render)

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

## Endpoint exposé

- `GET /health`
- `POST /agent` (orchestrateur unique)

### Format `/agent`

```json
{
  "message": "Crée une page dans la base Journal avec le titre Lundi et le statut Todo.",
  "context": {
    "database_hint": "Journal"
  }
}
```

Réponse standard :

- `output` : réponse finale de l'orchestrateur.
- `run_metadata` : métadonnées de l'exécution (si disponibles dans le SDK).

## Notion Writer (tools)

Le Notion Writer supporte :

- Pages : créer, modifier, archiver/supprimer, lire.
- Blocs : ajouter, remplacer, supprimer, modifier le texte.
- Databases : lire le schéma, créer/modifier/archiver des entrées.
- Propriétés : lecture des options (select/status/multi-select) et validation stricte avant écriture.

L'orchestrateur lit le schéma des bases avant toute écriture pour éviter les actions invalides.
