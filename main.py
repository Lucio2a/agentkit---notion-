import json
import logging
import os
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from openai_agents import Agent, Runner

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
    agent = _build_orchestrator_agent()
    prompt = request.message
    if request.context:
        prompt += "\n\nContexte JSON:\n" + json.dumps(request.context, ensure_ascii=False)
    try:
        result = Runner.run_sync(agent, prompt)
    except NotionAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except Exception as exc:
        logger.exception("Orchestrator run failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

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
