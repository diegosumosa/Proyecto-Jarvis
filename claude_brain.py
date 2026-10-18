"""Cerebro de Jarvis: envía texto a Groq (Llama) y ejecuta herramientas (tool use)."""
import json
import os

from dotenv import load_dotenv
from groq import Groq

import tools

load_dotenv()

MODEL = "openai/gpt-oss-20b"
SYSTEM_PROMPT = (
    "Eres Jarvis, un asistente virtual local. Responde siempre en español, "
    "de forma breve y conversacional (tus respuestas se leen en voz alta, "
    "así que evita markdown, listas y símbolos). Usa las herramientas "
    "disponibles cuando el usuario pida abrir apps, la hora o buscar en Wikipedia."
)
MAX_TOOL_ROUNDS = 5
MAX_HISTORY = 20  # mensajes recientes que se conservan (evita pasar el límite de tokens)

# Groq usa el formato de herramientas estilo OpenAI.
_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["input_schema"],
        },
    }
    for t in tools.TOOL_DEFINITIONS
]

_client = None
_history = []


def _get_client():
    global _client
    if _client is None:
        key = os.getenv("GROQ_API_KEY")
        if not key or key == "tu_api_key_aqui":
            raise RuntimeError("Falta GROQ_API_KEY en el archivo .env")
        _client = Groq(api_key=key)
    return _client


def _trim_history():
    """Recorta el historial sin dejar un mensaje 'tool' huérfano al inicio."""
    global _history
    if len(_history) > MAX_HISTORY:
        _history = _history[-MAX_HISTORY:]
        while _history and _history[0]["role"] != "user":
            _history.pop(0)


def ask_claude(text: str) -> str:
    """Recibe texto, lo envía al modelo (resolviendo tool calls) y devuelve la respuesta."""
    client = _get_client()
    _history.append({"role": "user", "content": text})

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=1024,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, *_history],
            tools=_TOOLS,
            tool_choice="auto",
        )
        message = response.choices[0].message

        if not message.tool_calls:
            reply = (message.content or "").strip()
            _history.append({"role": "assistant", "content": reply})
            _trim_history()
            return reply

        # Guardamos el turno del asistente con sus tool_calls.
        _history.append(
            {
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.function.name, "arguments": c.function.arguments},
                    }
                    for c in message.tool_calls
                ],
            }
        )
        # Ejecutamos localmente cada herramienta y devolvemos su resultado.
        for call in message.tool_calls:
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            output = tools.run_tool(call.function.name, args)
            _history.append({"role": "tool", "tool_call_id": call.id, "content": output})

    return "Lo siento, no pude completar la tarea."


if __name__ == "__main__":
    print(ask_claude("¿Qué hora es?"))
