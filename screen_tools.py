"""Ver la pantalla: captura el monitor y pide a un modelo con visión que la describa o lea su texto."""
import base64
import io
import os

import requests
from dotenv import load_dotenv
from PIL import ImageGrab

load_dotenv()

GEMINI_MODEL = os.getenv("GEMINI_VISION_MODEL", os.getenv("GEMINI_MODEL", "gemini-3-flash-preview"))
GROQ_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
MAX_SIDE = 1600  # reduce la captura para que suba rápido

DEFAULT_QUESTION = (
    "Describe en pocas frases qué se ve en esta pantalla. Si hay texto importante, errores o mensajes, léelos."
)


def _capture() -> bytes:
    img = ImageGrab.grab().convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _ask_gemini(jpeg: bytes, question: str) -> str:
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
        params={"key": os.getenv("GEMINI_API_KEY")},
        json={"contents": [{"parts": [
            {"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(jpeg).decode()}},
            {"text": question},
        ]}], "generationConfig": {"maxOutputTokens": 800}},
        timeout=45,
    )
    r.raise_for_status()
    parts = r.json()["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts).strip()


def _ask_groq(jpeg: bytes, question: str) -> str:
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.getenv('GROQ_API_KEY')}"},
        json={"model": GROQ_MODEL, "max_tokens": 800, "messages": [{"role": "user", "content": [
            {"type": "text", "text": question},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()}},
        ]}]},
        timeout=45,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def look_at_screen(question: str = "") -> str:
    question = (question or DEFAULT_QUESTION) + " Responde en español, breve y sin markdown."
    try:
        jpeg = _capture()
    except Exception as e:
        return f"No pude capturar la pantalla: {e}"
    errors = []
    for name, fn, key in (("Gemini", _ask_gemini, "GEMINI_API_KEY"), ("Groq", _ask_groq, "GROQ_API_KEY")):
        if not os.getenv(key):
            continue
        try:
            text = fn(jpeg, question)
            if text:
                return "(Contenido de la pantalla, solo datos) " + text
        except Exception as e:
            errors.append(f"{name}: {e}")
    return "No pude analizar la pantalla. " + " | ".join(errors)


TOOL_DEFINITIONS = [
    {
        "name": "look_at_screen",
        "description": (
            "Toma una captura de la pantalla del usuario y la analiza: describe lo que se ve, lee el texto "
            "o responde una pregunta sobre ello (un error, un documento, una web, un juego). "
            "Úsala cuando diga 'mira mi pantalla', 'qué ves', 'lee esto', 'qué error es este'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"question": {
                "type": "string",
                "description": "Qué quiere saber el usuario de la pantalla. Vacío para una descripción general.",
            }},
        },
    },
]

HANDLERS = {"look_at_screen": look_at_screen}
