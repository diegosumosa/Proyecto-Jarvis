"""Spotify por API: poner canciones, artistas o listas por nombre y saber qué suena.

Usa el flujo PKCE, así que solo hace falta SPOTIFY_CLIENT_ID en .env (sin Client Secret).
Requiere Spotify Premium. La primera vez ejecuta:  .\\venv\\Scripts\\python spotify_login.py
"""
import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv

load_dotenv()

REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPES = (
    "user-modify-playback-state user-read-playback-state user-read-currently-playing "
    "user-library-modify user-library-read"
)
TOKEN_FILE = Path(__file__).parent / "data" / "spotify_token.json"
_AUTH_URL = "https://accounts.spotify.com/authorize"
_TOKEN_URL = "https://accounts.spotify.com/api/token"
_API = "https://api.spotify.com/v1"
_NOT_READY = "Spotify no está configurado. Ejecuta spotify_login.py una vez."


def _client_id() -> str:
    cid = os.getenv("SPOTIFY_CLIENT_ID")
    if not cid:
        raise RuntimeError("Falta SPOTIFY_CLIENT_ID en el archivo .env")
    return cid


def make_login_url() -> tuple:
    """Devuelve (url para abrir en el navegador, code_verifier)."""
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    query = urlencode({
        "client_id": _client_id(),
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
    })
    return f"{_AUTH_URL}?{query}", verifier


def _save_token(data: dict, old: dict = None) -> dict:
    token = {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token") or (old or {}).get("refresh_token"),
        "expires_at": time.time() + data.get("expires_in", 3600) - 30,
    }
    TOKEN_FILE.parent.mkdir(exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(token), encoding="utf-8")
    return token


def exchange_code(code: str, verifier: str) -> None:
    r = requests.post(_TOKEN_URL, data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": _client_id(),
        "code_verifier": verifier,
    }, timeout=15)
    r.raise_for_status()
    _save_token(r.json())


def _access_token() -> str:
    if not TOKEN_FILE.exists():
        raise RuntimeError(_NOT_READY)
    token = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    if time.time() >= token["expires_at"]:
        r = requests.post(_TOKEN_URL, data={
            "grant_type": "refresh_token",
            "refresh_token": token["refresh_token"],
            "client_id": _client_id(),
        }, timeout=15)
        r.raise_for_status()
        token = _save_token(r.json(), token)
    return token["access_token"]


def _call(method: str, path: str, **kwargs) -> requests.Response:
    headers = {"Authorization": f"Bearer {_access_token()}"}
    return requests.request(method, f"{_API}{path}", headers=headers, timeout=15, **kwargs)


def _device_id():
    """Id del dispositivo activo; si ninguno lo está, el primero disponible (p. ej. la app de escritorio)."""
    devices = _call("GET", "/me/player/devices").json().get("devices", [])
    for d in devices:
        if d.get("is_active"):
            return d["id"]
    return devices[0]["id"] if devices else None


def spotify_play(query: str, kind: str = "track") -> str:
    if kind not in ("track", "artist", "playlist", "album"):
        kind = "track"
    r = _call("GET", "/search", params={"q": query, "type": kind, "limit": 1})
    if r.status_code != 200:
        return f"Spotify no respondió a la búsqueda ({r.status_code})."
    items = [i for i in r.json().get(f"{kind}s", {}).get("items", []) if i]
    if not items:
        return f"No encontré '{query}' en Spotify."
    item = items[0]
    body = {"uris": [item["uri"]]} if kind == "track" else {"context_uri": item["uri"]}
    params = {}
    device = _device_id()
    if device:
        params["device_id"] = device
    r = _call("PUT", "/me/player/play", params=params, json=body)
    if r.status_code == 403:
        return "Spotify rechazó la orden. Revisa que tu cuenta sea Premium."
    if r.status_code == 404 or not device:
        return "No hay ningún dispositivo de Spotify disponible. Abre la app de Spotify."
    if r.status_code not in (200, 202, 204):
        return f"Spotify no pudo reproducirlo ({r.status_code})."
    if kind == "track":
        artists = ", ".join(a["name"] for a in item["artists"])
        return f"Reproduciendo {item['name']} de {artists}."
    return f"Reproduciendo {item['name']}."


def spotify_now_playing() -> str:
    r = _call("GET", "/me/player/currently-playing")
    if r.status_code != 200 or not r.content:
        return "No hay nada sonando en Spotify."
    item = r.json().get("item")
    if not item:
        return "No hay nada sonando en Spotify."
    artists = ", ".join(a["name"] for a in item.get("artists", []))
    return f"Suena {item['name']} de {artists}."


def _find_track(query: str):
    """Busca una canción y devuelve su dato (o un mensaje de error como texto)."""
    r = _call("GET", "/search", params={"q": query, "type": "track", "limit": 1})
    if r.status_code != 200:
        return f"Spotify no respondió a la búsqueda ({r.status_code})."
    items = [i for i in r.json().get("tracks", {}).get("items", []) if i]
    return items[0] if items else f"No encontré '{query}' en Spotify."


def _describe(track: dict) -> str:
    return f"{track['name']} de {', '.join(a['name'] for a in track['artists'])}"


def spotify_queue(query: str) -> str:
    track = _find_track(query)
    if isinstance(track, str):
        return track
    params = {"uri": track["uri"]}
    device = _device_id()
    if device:
        params["device_id"] = device
    r = _call("POST", "/me/player/queue", params=params)
    if r.status_code == 403:
        return "Spotify rechazó la orden. Revisa que tu cuenta sea Premium."
    if r.status_code == 404 or not device:
        return "No hay ningún dispositivo de Spotify activo. Abre Spotify y pon algo primero."
    if r.status_code not in (200, 202, 204):
        return f"Spotify no pudo añadirla a la cola ({r.status_code})."
    return f"Añadí {_describe(track)} a la cola."


def spotify_like() -> str:
    """Guarda en 'Canciones que te gustan' la canción que suena ahora."""
    r = _call("GET", "/me/player/currently-playing")
    item = r.json().get("item") if r.status_code == 200 and r.content else None
    if not item:
        return "No hay nada sonando en Spotify."
    r = _call("PUT", "/me/tracks", params={"ids": item["id"]})
    if r.status_code == 403:
        return "Me falta permiso para tus canciones guardadas. Ejecuta spotify_login.py otra vez."
    if r.status_code not in (200, 201, 204):
        # Spotify está migrando este endpoint a /me/library con URIs.
        r = _call("PUT", "/me/library", params={"uris": item["uri"]})
    if r.status_code not in (200, 201, 204):
        return f"Spotify no pudo guardar la canción ({r.status_code})."
    return f"Guardé {_describe(item)} en tus canciones que te gustan."


def spotify_devices(action: str = "list", name: str = "") -> str:
    devices = _call("GET", "/me/player/devices").json().get("devices", [])
    if not devices:
        return "No veo ningún dispositivo de Spotify. Abre la app en el dispositivo que quieras."
    if action == "list":
        return "\n".join(f"- {d['name']} ({d['type']}){' [activo]' if d.get('is_active') else ''}" for d in devices)
    wanted = name.strip().lower()
    matches = [d for d in devices if wanted and wanted in d["name"].lower()]
    if not matches:
        return f"No encontré un dispositivo llamado '{name}'. Disponibles: {', '.join(d['name'] for d in devices)}."
    r = _call("PUT", "/me/player", json={"device_ids": [matches[0]["id"]], "play": True})
    if r.status_code not in (200, 202, 204):
        return f"Spotify no pudo cambiar de dispositivo ({r.status_code})."
    return f"Pasé la música a {matches[0]['name']}."


def spotify_mode(shuffle: bool = None, repeat: str = None) -> str:
    """Activa o desactiva el modo aleatorio y/o la repetición (off, track o context)."""
    done = []
    if shuffle is not None:
        r = _call("PUT", "/me/player/shuffle", params={"state": str(bool(shuffle)).lower()})
        if r.status_code not in (200, 202, 204):
            return f"Spotify no pudo cambiar el modo aleatorio ({r.status_code})."
        done.append("aleatorio activado" if shuffle else "aleatorio desactivado")
    if repeat is not None:
        if repeat not in ("off", "track", "context"):
            return "La repetición puede ser: off, track o context."
        r = _call("PUT", "/me/player/repeat", params={"state": repeat})
        if r.status_code not in (200, 202, 204):
            return f"Spotify no pudo cambiar la repetición ({r.status_code})."
        done.append({"off": "repetición desactivada", "track": "repitiendo la canción",
                     "context": "repitiendo la lista"}[repeat])
    return ("Listo: " + ", ".join(done) + ".") if done else "¿Qué quieres cambiar: aleatorio o repetición?"


TOOL_DEFINITIONS = [
    {
        "name": "spotify_queue",
        "description": "Añade una canción a la cola de Spotify (suena después de la actual) por su nombre.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Canción (con el artista si lo dijo)."}},
            "required": ["query"],
        },
    },
    {
        "name": "spotify_like",
        "description": "Guarda en 'Canciones que te gustan' (da me gusta a) la canción que suena ahora en Spotify.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "spotify_devices",
        "description": "Lista los dispositivos de Spotify (action=list) o pasa la música a otro (action=transfer, con su nombre).",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "transfer"]},
                "name": {"type": "string", "description": "Nombre (o parte) del dispositivo, para transfer."},
            },
            "required": ["action"],
        },
    },
    {
        "name": "spotify_mode",
        "description": "Activa o desactiva el modo aleatorio de Spotify y/o la repetición (off, track = la canción, context = la lista).",
        "input_schema": {
            "type": "object",
            "properties": {
                "shuffle": {"type": "boolean", "description": "true para aleatorio, false para quitarlo."},
                "repeat": {"type": "string", "enum": ["off", "track", "context"]},
            },
        },
    },
    {
        "name": "spotify_play",
        "description": (
            "Pone en Spotify una canción, artista, álbum o lista por su nombre. "
            "Úsala cuando el usuario pida poner o reproducir música concreta."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Nombre de la canción, artista, álbum o lista (con el artista si lo dijo)."},
                "kind": {"type": "string", "enum": ["track", "artist", "album", "playlist"], "description": "Qué buscar; 'track' por defecto."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "spotify_now_playing",
        "description": "Dice qué canción está sonando ahora en Spotify.",
        "input_schema": {"type": "object", "properties": {}},
    },
]

HANDLERS = {
    "spotify_play": spotify_play,
    "spotify_now_playing": spotify_now_playing,
    "spotify_queue": spotify_queue,
    "spotify_like": spotify_like,
    "spotify_devices": spotify_devices,
    "spotify_mode": spotify_mode,
}
