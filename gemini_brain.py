"""Cerebro alternativo: Gemini (API REST de Google AI Studio) con tool use."""
import json
import os
import time

import requests
from dotenv import load_dotenv

import tools

load_dotenv()

MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
RETRIES = 1
_RETRYABLE = {403, 429, 500, 502, 503, 504}
MAX_TOOL_ROUNDS = 5
MAX_HISTORY = 20

_UNSUPPORTED_KEYS = {"additionalProperties", "default", "$schema"}


def _clean_schema(schema):
    """Gemini acepta solo un subconjunto de JSON Schema."""
    if isinstance(schema, dict):
        return {k: _clean_schema(v) for k, v in schema.items() if k not in _UNSUPPORTED_KEYS}
    if isinstance(schema, list):
        return [_clean_schema(v) for v in schema]
    return schema


def _declaration(t: dict) -> dict:
    decl = {"name": t["name"], "description": t["description"]}
    schema = _clean_schema(t["input_schema"])
    if schema.get("properties"):  # Gemini rechaza objetos sin propiedades
        decl["parameters"] = schema
    return decl


_TOOLS = [{"functionDeclarations": [_declaration(t) for t in tools.TOOL_DEFINITIONS]}]
_history = []  # contenidos en formato Gemini (se guardan tal cual vienen, con sus firmas de pensamiento)


def _trim_history():
    """Recorta sin dejar al inicio un resultado de herramienta o un turno del modelo huérfano."""
    global _history
    if len(_history) > MAX_HISTORY:
        _history = _history[-MAX_HISTORY:]

        def starts_user_text(c):
            return c["role"] == "user" and any("text" in p for p in c["parts"])

        while _history and not starts_user_text(_history[0]):
            _history.pop(0)


def _generate(system_prompt: str) -> dict:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("Falta GEMINI_API_KEY en el archivo .env")
    body = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": _history,
        "tools": _TOOLS,
        "generationConfig": {
            "maxOutputTokens": 1024,
            "thinkingConfig": {"thinkingLevel": "minimal"},  # respuestas rápidas
        },
    }
    # Los errores 403/429/5xx de Google son intermitentes en esta cuenta: se reintenta antes de rendirse.
    for attempt in range(RETRIES + 1):
        r = requests.post(_URL.format(model=MODEL), params={"key": key}, json=body, timeout=45)
        if r.ok:
            return r.json()
        if r.status_code not in _RETRYABLE or attempt == RETRIES:
            break
        time.sleep(0.3)
    raise RuntimeError(f"Gemini {r.status_code}: {r.text[:200]}")


def ask(text: str, system_prompt: str) -> str:
    """Envía el texto a Gemini, resuelve las herramientas y devuelve la respuesta.
    Si falla, deja el historial como estaba y propaga el error."""
    start = len(_history)
    _history.append({"role": "user", "parts": [{"text": text}]})
    try:
        for _ in range(MAX_TOOL_ROUNDS):
            data = _generate(system_prompt)
            candidates = data.get("candidates") or []
            content = candidates[0].get("content") if candidates else None
            if not content or not content.get("parts"):
                raise RuntimeError(f"Gemini no devolvió contenido: {str(data)[:200]}")
            _history.append(content)
            calls = [p["functionCall"] for p in content["parts"] if "functionCall" in p]
            if not calls:
                reply = "".join(p.get("text", "") for p in content["parts"] if not p.get("thought")).strip()
                _trim_history()
                return reply
            responses = []
            for call in calls:
                output = tools.run_tool(call["name"], call.get("args") or {})
                responses.append({"functionResponse": {"name": call["name"], "response": {"result": output}}})
            _history.append({"role": "user", "parts": responses})
    except Exception:
        del _history[start:]
        raise
    del _history[start:]
    return "Lo siento, no pude completar la tarea."
