"""Manos de Jarvis: herramientas locales y sus descripciones JSON para la API."""
import subprocess
from datetime import datetime

import wikipedia

# Apps que Jarvis puede abrir (nombre -> comando). Añade las tuyas aquí,
# p. ej. "spotify": r"C:\Users\TU_USUARIO\AppData\Roaming\Spotify\Spotify.exe"
APPS = {
    "bloc de notas": "notepad.exe",
    "calculadora": "calc.exe",
    "paint": "mspaint.exe",
    "explorador": "explorer.exe",
}


def open_app(app_name: str) -> str:
    key = app_name.strip().lower()
    command = APPS.get(key)
    if command is None:
        return f"No tengo registrada la app '{app_name}'. Disponibles: {', '.join(APPS)}."
    try:
        subprocess.Popen(command)
        return f"Abrí {key}."
    except OSError as e:
        return f"No pude abrir {key}: {e}"


def get_time() -> str:
    return datetime.now().strftime("Son las %H:%M del %d/%m/%Y.")


def search_wikipedia(query: str) -> str:
    wikipedia.set_lang("es")
    try:
        return wikipedia.summary(query, sentences=3, auto_suggest=False)
    except wikipedia.DisambiguationError as e:
        return f"Búsqueda ambigua. Opciones: {', '.join(e.options[:5])}."
    except wikipedia.PageError:
        return f"No encontré nada en Wikipedia sobre '{query}'."
    except Exception as e:  # red, timeouts, etc.
        return f"Error al consultar Wikipedia: {e}"


TOOL_DEFINITIONS = [
    {
        "name": "open_app",
        "description": "Abre una aplicación local del computador del usuario.",
        "input_schema": {
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": f"Nombre de la app. Opciones: {', '.join(APPS)}.",
                }
            },
            "required": ["app_name"],
        },
    },
    {
        "name": "get_time",
        "description": "Devuelve la fecha y hora exactas del sistema.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "search_wikipedia",
        "description": "Busca un resumen de un tema en Wikipedia (en español).",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Tema a buscar."}},
            "required": ["query"],
        },
    },
]

_DISPATCH = {
    "open_app": open_app,
    "get_time": get_time,
    "search_wikipedia": search_wikipedia,
}


def run_tool(name: str, args: dict) -> str:
    func = _DISPATCH.get(name)
    if func is None:
        return f"Herramienta desconocida: {name}"
    try:
        return func(**args)
    except Exception as e:
        return f"Error ejecutando {name}: {e}"
