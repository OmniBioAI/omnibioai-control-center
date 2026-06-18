from __future__ import annotations
import os
import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

OLLAMA_URL = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434")

@router.get("/llms")
async def get_llms() -> JSONResponse:
    # Ollama models
    models = []
    ollama_status = "unreachable"
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{OLLAMA_URL}/api/tags")
            if r.status_code == 200:
                ollama_status = "running"
                for m in r.json().get("models", []):
                    models.append({
                        "name": m["name"],
                        "size_gb": round(m.get("size", 0) / 1e9, 1),
                        "modified": m.get("modified_at", "")[:10],
                    })
    except Exception:
        pass

    # API key status — check env vars
    # Never expose actual key values — just whether they are set
    api_keys = {
        "anthropic": {
            "configured": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "label": "Claude API (Anthropic)",
        },
        "openai": {
            "configured": bool(os.environ.get("OPENAI_API_KEY")),
            "label": "OpenAI API",
        },
    }

    return JSONResponse({
        "ollama": {
            "status": ollama_status,
            "url": OLLAMA_URL,
            "models": models,
        },
        "api_keys": api_keys,
    })
