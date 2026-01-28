import json
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from openai import OpenAI

from notion_writer import (
    NotionAPIError,
    notion_append_blocks,
    notion_archive_page,
    notion_create_child_page,
    notion_create_page_in_database,
    notion_delete_blocks,
    notion_read_database_schema,
    notion_read_page,
    notion_replace_blocks,
    notion_replace_page_content,
    notion_update_block_text,
    notion_update_page_properties,
)
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from openai_agents import Agent, Runner
from openai import OpenAI
from openai.agents import Agent, Runner

from notion_writer import NOTION_TOOLS, NotionAPIError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("orchestrator")

app = FastAPI()


class OrchestratorRequest(BaseModel):
    message: str = Field(..., min_length=1, description="User request for the orchestrator")
    context: Optional[Dict[str, Any]] = Field(
        default=None, description="Optional structured context to include with the request"
    )


class OrchestratorResponse(BaseModel):
    output: str
    run_metadata: Optional[Dict[str, Any]] = None


def _tool_definitions() -> List[Dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "notion_read_database_schema",
                "description": "Read a Notion database schema including property options.",
                "parameters": {
                    "type": "object",
                    "properties": {"database_id": {"type": "string"}},
                    "required": ["database_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "notion_read_page",
                "description": "Read a Notion page and its block tree.",
                "parameters": {
                    "type": "object",
                    "properties": {"page_id": {"type": "string"}},
                    "required": ["page_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "notion_create_page_in_database",
                "description": "Create a new page inside a database with validated properties.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "database_id": {"type": "string"},
                        "title": {"type": "string"},
                        "properties": {"type": "object"},
                        "content": {"type": "string"},
                        "blocks": {"type": "array", "items": {"type": "object"}},
                    },
                    "required": ["database_id", "title"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "notion_create_child_page",
                "description": "Create a child page under another page.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "parent_page_id": {"type": "string"},
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "blocks": {"type": "array", "items": {"type": "object"}},
                    },
                    "required": ["parent_page_id", "title"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "notion_update_page_properties",
                "description": "Update Notion page properties after validating against schema.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "page_id": {"type": "string"},
                        "properties": {"type": "object"},
                    },
                    "required": ["page_id", "properties"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "notion_archive_page",
                "description": "Archive a Notion page (or database entry).",
                "parameters": {
                    "type": "object",
                    "properties": {"page_id": {"type": "string"}},
                    "required": ["page_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "notion_append_blocks",
                "description": "Append blocks to an existing Notion page or block.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "block_id": {"type": "string"},
                        "blocks": {"type": "array", "items": {"type": "object"}},
                    },
                    "required": ["block_id", "blocks"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "notion_replace_blocks",
                "description": "Replace all blocks under a page or block with new content.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "block_id": {"type": "string"},
                        "blocks": {"type": "array", "items": {"type": "object"}},
                    },
                    "required": ["block_id", "blocks"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "notion_delete_blocks",
                "description": "Delete blocks by id.",
                "parameters": {
                    "type": "object",
                    "properties": {"block_ids": {"type": "array", "items": {"type": "string"}}},
                    "required": ["block_ids"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "notion_update_block_text",
                "description": "Update the text of a supported Notion block.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "block_id": {"type": "string"},
                        "text": {"type": "string"},
                    },
                    "required": ["block_id", "text"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "notion_replace_page_content",
                "description": "Replace all content in a page with plain text paragraphs.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "page_id": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["page_id", "content"],
                },
            },
        },
    ]


def _tool_dispatch() -> Dict[str, Any]:
    return {
        "notion_read_database_schema": notion_read_database_schema,
        "notion_read_page": notion_read_page,
        "notion_create_page_in_database": notion_create_page_in_database,
        "notion_create_child_page": notion_create_child_page,
        "notion_update_page_properties": notion_update_page_properties,
        "notion_archive_page": notion_archive_page,
        "notion_append_blocks": notion_append_blocks,
        "notion_replace_blocks": notion_replace_blocks,
        "notion_delete_blocks": notion_delete_blocks,
        "notion_update_block_text": notion_update_block_text,
        "notion_replace_page_content": notion_replace_page_content,
    }


def _build_system_prompt() -> str:
    return "" + (
        "Tu es l'orchestrateur unique du backend. "
        "Analyse la demande, puis appelle uniquement les tools Notion Writer pour interagir avec Notion. "
        "Avant toute écriture sur une base de données, lis le schéma de la base pour valider les propriétés et options. "
        "Réponds en français avec un résumé clair de l'action réalisée et les identifiants retournés par Notion."
    )

def _build_orchestrator_agent() -> Agent:
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    return Agent(
        name="Notion Orchestrator",
        model=model,
        instructions=(
            "Tu es l'orchestrateur unique du backend. "
            "Analyse la demande, puis appelle uniquement les tools Notion Writer "
            "pour interagir avec Notion. "
            "Avant toute écriture sur une base de données, lis le schéma de la base pour "
            "valider les propriétés et options. "
            "Réponds en français avec un résumé clair de l'action réalisée et les identifiants "
            "retournés par Notion."
        ),
        tools=NOTION_TOOLS,
    )


@app.get("/health")
async def healthcheck() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/agent", response_model=OrchestratorResponse)
async def orchestrate(request: OrchestratorRequest) -> OrchestratorResponse:
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=500, detail="Missing OPENAI_API_KEY environment variable")

    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    client = OpenAI()
    prompt = request.message
    if request.context:
        prompt += "\n\nContexte JSON:\n" + json.dumps(request.context, ensure_ascii=False)

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": _build_system_prompt()},
        {"role": "user", "content": prompt},
    ]
    tools = _tool_definitions()
    tool_map = _tool_dispatch()
    tool_calls_executed: List[Dict[str, Any]] = []

    try:
        for _ in range(6):
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )
            choice = response.choices[0].message
            if not choice.tool_calls:
                output = choice.content or ""
                return OrchestratorResponse(
                    output=output,
                    run_metadata={
                        "model": response.model,
                        "usage": response.usage.model_dump() if response.usage else None,
                        "tool_calls": tool_calls_executed,
                    },
                )

            for tool_call in choice.tool_calls:
                tool_name = tool_call.function.name
                raw_args = tool_call.function.arguments or "{}"
                try:
                    args = json.loads(raw_args)
                except json.JSONDecodeError:
                    args = {}
                tool_fn = tool_map.get(tool_name)
                if not tool_fn:
                    raise HTTPException(status_code=400, detail=f"Unknown tool requested: {tool_name}")
                result = tool_fn(**args)
                tool_calls_executed.append({"name": tool_name, "arguments": args, "result": result})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
    except Exception:
        raise
    client = OpenAI()
    agent = _build_orchestrator_agent()
    prompt = request.message
    if request.context:
        prompt += "\n\nContexte JSON:\n" + json.dumps(request.context, ensure_ascii=False)
    try:
        result = Runner.run_sync(agent, prompt)
        try:
            result = Runner.run_sync(agent, prompt, client=client)
        except TypeError:
            result = Runner.run_sync(agent, prompt)
    except NotionAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except Exception as exc:
        logger.exception("Orchestrator run failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    raise HTTPException(status_code=500, detail="Orchestrator exceeded tool call limit")
    output = getattr(result, "final_output", None)
    if output is None:
        output = getattr(result, "output_text", None)
    if output is None:
        output = str(result)

    run_metadata = None
    if hasattr(result, "model_dump"):
        run_metadata = result.model_dump()
    elif hasattr(result, "dict"):
        run_metadata = result.dict()

    return OrchestratorResponse(output=output, run_metadata=run_metadata)
