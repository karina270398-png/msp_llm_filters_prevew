import json
import os
from typing import Any, Dict

import httpx

PROMPTS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "prompts", "system_instructions_batchcards.md")


def _load_system_prompt() -> str:
    try:
        with open(PROMPTS_PATH, "r", encoding="utf-8") as f:
            base = f.read()
    except Exception:
        base = ""
    extra = (
        "\n\nВажное требование по формату вывода:\n"
        "Верни ТОЛЬКО JSON со структурой {\"filters\": object, \"page\": integer, \"page_size\": integer}."
        " Без пояснений и текста вне JSON. Даты строго YYYY-MM-DD."
    )
    return base + extra


def nl_to_batchcards_via_ollama(query: str) -> Dict[str, Any]:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_K_M")

    system_prompt = _load_system_prompt()

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query},
        ],
        "options": {"temperature": 0.2},
        "stream": False,
    }

    with httpx.Client(timeout=60) as client:
        r = client.post(f"{base_url}/api/chat", json=payload)
        r.raise_for_status()
        data = r.json()

    content = (
        data.get("message", {}).get("content")
        or data.get("choices", [{}])[0].get("message", {}).get("content")
        or ""
    )
    content_str = content.strip()
    if content_str.startswith("```"):
        parts = content_str.split("```")
        if len(parts) >= 3:
            content_str = parts[1].strip()
    result = json.loads(content_str)
    if not isinstance(result, dict):
        raise ValueError("LLM output is not a JSON object")
    if "filters" not in result:
        result["filters"] = {}
    if "page" not in result:
        result["page"] = 1
    if "page_size" not in result:
        result["page_size"] = 20
    return result