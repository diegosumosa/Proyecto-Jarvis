"""Rutas: tiempo y distancia entre dos lugares (OpenStreetMap/OSRM, sin clave)."""
import os
import webbrowser
from urllib.parse import quote

import requests

HEADERS = {"User-Agent": "Jarvis-assistant/1.0"}
PROFILES = {"coche": "driving", "bici": "cycling", "a pie": "foot"}
GMAPS_MODES = {"coche": "driving", "bici": "bicycling", "a pie": "walking", "transporte": "transit"}


def _geocode(place: str):
    r = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": place, "format": "json", "limit": 1}, headers=HEADERS, timeout=10,
    ).json()
    if not r:
        return None
    return float(r[0]["lon"]), float(r[0]["lat"]), r[0]["display_name"].split(",")[0]


def _human(seconds: float) -> str:
    m = round(seconds / 60)
    return f"{m} minutos" if m < 60 else f"{m // 60} h {m % 60} min"


def get_route(destination: str, origin: str = "", mode: str = "coche", open_map: bool = False) -> str:
    origin = origin or os.getenv("HOME_ADDRESS") or os.getenv("DEFAULT_CITY", "")
    if not origin:
        return "¿Desde dónde sales? Dime el origen o define HOME_ADDRESS en el archivo .env."
    mode = mode if mode in GMAPS_MODES else "coche"
    if open_map:
        webbrowser.open(
            f"https://www.google.com/maps/dir/?api=1&origin={quote(origin)}&destination={quote(destination)}"
            f"&travelmode={GMAPS_MODES[mode]}"
        )
    if mode == "transporte":
        return "Te abrí el mapa con transporte público." if open_map else \
            "No calculo transporte público; pídeme abrir el mapa."
    try:
        a, b = _geocode(origin), _geocode(destination)
        if not a:
            return f"No encontré el origen '{origin}'."
        if not b:
            return f"No encontré el destino '{destination}'."
        r = requests.get(
            f"https://router.project-osrm.org/route/v1/{PROFILES[mode]}/{a[0]},{a[1]};{b[0]},{b[1]}",
            params={"overview": "false"}, headers=HEADERS, timeout=15,
        ).json()
        route = r["routes"][0]
    except Exception as e:
        return f"No pude calcular la ruta: {e}"
    note = " Sin contar el tráfico en vivo." if mode == "coche" else ""
    return (f"De {a[2]} a {b[2]} en {mode}: {_human(route['duration'])}, "
            f"{route['distance'] / 1000:.1f} km.{note}" + (" Abrí el mapa." if open_map else ""))


TOOL_DEFINITIONS = [
    {
        "name": "get_route",
        "description": (
            "Calcula cuánto se tarda y qué distancia hay hasta un lugar. Sin origen usa la casa del usuario. "
            "Con open_map=true abre la ruta en Google Maps (ahí se ve el tráfico en vivo)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "destination": {"type": "string", "description": "Lugar de destino (dirección, sitio o ciudad)."},
                "origin": {"type": "string", "description": "Opcional: punto de partida."},
                "mode": {"type": "string", "enum": ["coche", "bici", "a pie", "transporte"]},
                "open_map": {"type": "boolean", "description": "true para abrir el mapa en el navegador."},
            },
            "required": ["destination"],
        },
    },
]

HANDLERS = {"get_route": get_route}
