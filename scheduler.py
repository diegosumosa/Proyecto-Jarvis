"""Temporizadores, alarmas, recordatorios y notas. Se guardan en data/ para sobrevivir reinicios."""
import json
import queue
import threading
import time
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
SCHEDULE_FILE = DATA_DIR / "schedule.json"
NOTES_FILE = DATA_DIR / "notes.json"

# Mensajes que Jarvis debe decir en voz alta (main.run los vacía en cada vuelta).
alerts: "queue.Queue[str]" = queue.Queue()

_lock = threading.Lock()
_started = False


def _load(path: Path) -> list:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def _save(path: Path, data: list) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _alert_text(item: dict) -> str:
    label = f" ({item['text']})" if item["text"] else ""
    if item["kind"] == "timer":
        return f"Tu temporizador{label} ha terminado."
    if item["kind"] == "alarm":
        return f"Es la hora de tu alarma{label}."
    return f"Recordatorio: {item['text']}."


def _scheduler_loop() -> None:
    while True:
        now = datetime.now()
        with _lock:
            items = _load(SCHEDULE_FILE)
            due = [i for i in items if datetime.fromisoformat(i["due"]) <= now]
            if due:
                _save(SCHEDULE_FILE, [i for i in items if i not in due])
        for item in due:
            alerts.put(_alert_text(item))
        time.sleep(1)


def start() -> None:
    """Arranca el vigilante en segundo plano (una sola vez)."""
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_scheduler_loop, daemon=True).start()


def _fmt_due(due: datetime) -> str:
    now = datetime.now()
    secs = int((due - now).total_seconds())
    if secs < 90:
        rel = f"en {max(secs, 0)} segundos"
    elif secs < 5400:
        rel = f"en {round(secs / 60)} minutos"
    elif secs < 86400:
        rel = f"en {secs / 3600:.1f} horas"
    else:
        rel = f"en {secs // 86400} días"
    day = "hoy" if due.date() == now.date() else due.strftime("%d/%m")
    return f"{day} a las {due.strftime('%H:%M')} ({rel})"


def schedule(kind: str, text: str = "", seconds: int = 0, at: str = "") -> str:
    now = datetime.now()
    if kind == "timer":
        if seconds <= 0:
            return "Dime cuántos segundos o minutos dura el temporizador."
        due = datetime.fromtimestamp(time.time() + seconds)
    elif kind in ("alarm", "reminder"):
        try:
            due = datetime.fromisoformat(at)
        except ValueError:
            return "Necesito la fecha y hora exactas (formato AAAA-MM-DDTHH:MM)."
        if due <= now:
            return "Esa hora ya pasó."
        if kind == "reminder" and not text:
            return "¿Qué quieres que te recuerde?"
    else:
        return f"Tipo desconocido: {kind}"

    with _lock:
        items = _load(SCHEDULE_FILE)
        new_id = max([i["id"] for i in items], default=0) + 1
        items.append({"id": new_id, "kind": kind, "text": text, "due": due.isoformat(timespec="seconds")})
        _save(SCHEDULE_FILE, items)
    names = {"timer": "Temporizador", "alarm": "Alarma", "reminder": "Recordatorio"}
    return f"{names[kind]} #{new_id} programado para {_fmt_due(due)}."


def list_scheduled() -> str:
    items = sorted(_load(SCHEDULE_FILE), key=lambda i: i["due"])
    if not items:
        return "No hay temporizadores, alarmas ni recordatorios pendientes."
    names = {"timer": "temporizador", "alarm": "alarma", "reminder": "recordatorio"}
    return "\n".join(
        f"#{i['id']} {names[i['kind']]}{' ' + repr(i['text']) if i['text'] else ''}: "
        f"{_fmt_due(datetime.fromisoformat(i['due']))}"
        for i in items
    )


def cancel_scheduled(id: int) -> str:
    with _lock:
        items = _load(SCHEDULE_FILE)
        rest = [i for i in items if i["id"] != id]
        if len(rest) == len(items):
            return f"No encontré el elemento #{id}."
        _save(SCHEDULE_FILE, rest)
    return f"Cancelé el elemento #{id}."


def notes(action: str, text: str = "", number: int = 0) -> str:
    with _lock:
        items = _load(NOTES_FILE)
        if action == "add":
            if not text:
                return "¿Qué quieres que anote?"
            items.append({"text": text, "created": datetime.now().isoformat(timespec="minutes")})
            _save(NOTES_FILE, items)
            return f"Nota #{len(items)} guardada."
        if action == "list":
            if not items:
                return "No tienes notas guardadas."
            return "\n".join(f"{n}. {i['text']}" for n, i in enumerate(items, 1))
        if action == "delete":
            if not 1 <= number <= len(items):
                return f"No existe la nota número {number}."
            removed = items.pop(number - 1)
            _save(NOTES_FILE, items)
            return f"Borré la nota: {removed['text']}"
    return f"Acción desconocida: {action}"


TOOL_DEFINITIONS = [
    {
        "name": "schedule",
        "description": (
            "Programa un temporizador (usa 'seconds'), una alarma o un recordatorio "
            "(usa 'at' = fecha y hora exacta AAAA-MM-DDTHH:MM, calculada con la hora actual). "
            "'text' es la etiqueta o lo que hay que recordar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["timer", "alarm", "reminder"]},
                "text": {"type": "string"},
                "seconds": {"type": "integer"},
                "at": {"type": "string"},
            },
            "required": ["kind"],
        },
    },
    {
        "name": "list_scheduled",
        "description": "Lista los temporizadores, alarmas y recordatorios pendientes.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "cancel_scheduled",
        "description": "Cancela un temporizador, alarma o recordatorio por su número (#id).",
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "integer"}},
            "required": ["id"],
        },
    },
    {
        "name": "notes",
        "description": "Notas del usuario: add (anotar 'text'), list (listar todas) o delete (borrar la nota 'number').",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["add", "list", "delete"]},
                "text": {"type": "string"},
                "number": {"type": "integer"},
            },
            "required": ["action"],
        },
    },
]

HANDLERS = {
    "schedule": schedule,
    "list_scheduled": list_scheduled,
    "cancel_scheduled": cancel_scheduled,
    "notes": notes,
}
