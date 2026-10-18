"""Manos de Jarvis: herramientas locales y sus descripciones JSON para la API."""
import ctypes
import subprocess
from ctypes import wintypes
from datetime import datetime

import wikipedia
from ddgs import DDGS

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


# --- Control de música (Spotify) ---
_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
_WM_APPCOMMAND = 0x0319
# Comandos que se envían directo a la ventana de Spotify (no afectan a otros reproductores).
_SPOTIFY_COMMANDS = {"play_pause": 14, "next": 11, "previous": 12}
# Teclas globales de Windows para el volumen.
_VOLUME_KEYS = {"volume_up": 0xAF, "volume_down": 0xAE, "mute": 0xAD}


def _find_spotify_window():
    """Devuelve el HWND de la ventana principal de Spotify, o None si no está abierta."""
    found = []
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _):
        if not _user32.IsWindowVisible(hwnd) or _user32.GetWindowTextLengthW(hwnd) == 0:
            return True
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = _kernel32.OpenProcess(0x1000, False, pid.value)  # QUERY_LIMITED_INFORMATION
        if handle:
            buf = ctypes.create_unicode_buffer(520)
            size = wintypes.DWORD(520)
            _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
            _kernel32.CloseHandle(handle)
            if buf.value.lower().endswith("spotify.exe"):
                found.append(hwnd)
                return False
        return True

    _user32.EnumWindows(enum_proc(callback), 0)
    return found[0] if found else None


def media_control(action: str) -> str:
    if action in _VOLUME_KEYS:
        key = _VOLUME_KEYS[action]
        for _ in range(3 if action != "mute" else 1):
            _user32.keybd_event(key, 0, 0, 0)
            _user32.keybd_event(key, 0, 2, 0)
        return {"volume_up": "Subí el volumen.", "volume_down": "Bajé el volumen.", "mute": "Silencié."}[action]
    if action not in _SPOTIFY_COMMANDS:
        return f"Acción desconocida: {action}"
    hwnd = _find_spotify_window()
    if hwnd is None:
        return "Spotify no está abierto."
    _user32.PostMessageW(hwnd, _WM_APPCOMMAND, hwnd, _SPOTIFY_COMMANDS[action] << 16)
    return {"play_pause": "Listo, pausé o reanudé la música.", "next": "Siguiente canción.", "previous": "Canción anterior."}[action]


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


def search_web(query: str, news: bool = False) -> str:
    """Busca en la web (DuckDuckGo, sin clave) y devuelve títulos y extractos."""
    try:
        ddgs = DDGS()
        if news:
            results = ddgs.news(query, region="es-es", max_results=5)
        else:
            results = ddgs.text(query, region="es-es", max_results=5)
    except Exception as e:
        return f"Error al buscar en la web: {e}"
    if not results:
        return f"No encontré resultados para '{query}'."
    lines = []
    for r in results:
        source = r.get("source") or r.get("href", "")
        lines.append(f"- {r.get('title', '')} ({source}): {r.get('body', '')[:300]}")
    return "\n".join(lines)


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
        "name": "media_control",
        "description": "Controla la música de Spotify: pausar/reanudar, siguiente, anterior, y volumen del sistema.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["play_pause", "next", "previous", "volume_up", "volume_down", "mute"],
                    "description": "Acción a realizar.",
                }
            },
            "required": ["action"],
        },
    },
    {
        "name": "get_time",
        "description": "Devuelve la fecha y hora exactas del sistema.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "search_web",
        "description": (
            "Busca en internet. Úsala para noticias, datos actuales o recientes, clima, deportes, "
            "precios o cualquier cosa que Wikipedia no cubra bien. Resume los resultados con tus palabras."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Texto a buscar."},
                "news": {"type": "boolean", "description": "true para buscar noticias recientes."},
            },
            "required": ["query"],
        },
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
    "media_control": media_control,
    "get_time": get_time,
    "search_web": search_web,
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
