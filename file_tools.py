"""Gestión de archivos: buscar, abrir, listar, crear carpetas y mover/copiar (nunca borra ni sobrescribe)."""
import os
import shutil
import time
from pathlib import Path

HOME = Path.home()
_ONEDRIVE = [p for p in HOME.glob("OneDrive*") if p.is_dir()]
# Carpetas donde se busca, en orden.
ROOTS = [r for r in (
    HOME / "Desktop", HOME / "Documents", HOME / "Downloads", HOME / "Pictures", HOME / "Videos", HOME / "Music",
    *[o / s for o in _ONEDRIVE for s in ("Desktop", "Documents", "Escritorio", "Documentos")],
) if r.is_dir()]
ALIASES = {
    "escritorio": "Desktop", "desktop": "Desktop", "documentos": "Documents", "documents": "Documents",
    "descargas": "Downloads", "downloads": "Downloads", "imagenes": "Pictures", "imágenes": "Pictures",
    "fotos": "Pictures", "videos": "Videos", "vídeos": "Videos", "musica": "Music", "música": "Music",
}
SKIP = {"node_modules", "venv", "__pycache__", "AppData"}
MAX_RESULTS = 8
SEARCH_SECONDS = 8


def _resolve(path: str) -> Path:
    """Acepta una ruta completa o el nombre de una carpeta conocida ('descargas')."""
    p = path.strip().strip('"')
    key = p.lower().rstrip("/\\")
    if key in ALIASES:
        for r in ROOTS:
            if r.name == ALIASES[key]:
                return r
        return HOME / ALIASES[key]
    return Path(os.path.expandvars(p)).expanduser()


def _fmt(p: Path) -> str:
    try:
        st = p.stat()
        mtime = time.strftime("%d/%m/%Y", time.localtime(st.st_mtime))
        if p.is_dir():
            info = "carpeta"
        elif st.st_size < 1_048_576:
            info = f"{st.st_size / 1024:.0f} KB"
        else:
            info = f"{st.st_size / 1_048_576:.1f} MB"
        return f"{p} ({info}, {mtime})"
    except OSError:
        return str(p)


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0


def find_files(query: str, folder: str = "") -> str:
    words = query.lower().split()
    if not words:
        return "¿Qué archivo busco?"
    roots = [_resolve(folder)] if folder else ROOTS
    deadline = time.time() + SEARCH_SECONDS
    hits = []
    for root in roots:
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith(".")]
            for name in files + dirs:
                low = name.lower()
                if all(w in low for w in words):
                    hits.append(Path(dirpath) / name)
            if time.time() > deadline or len(hits) >= 60:
                break
        if time.time() > deadline or len(hits) >= 60:
            break
    if not hits:
        return f"No encontré nada llamado '{query}'."
    hits.sort(key=_mtime, reverse=True)
    return "\n".join(f"- {_fmt(p)}" for p in hits[:MAX_RESULTS])


def open_path(path: str) -> str:
    p = _resolve(path)
    if not p.exists():
        return f"No existe '{path}'. Búscalo primero con find_files."
    os.startfile(str(p))
    return f"Abrí {p.name or p}."


def list_folder(path: str) -> str:
    p = _resolve(path)
    if not p.is_dir():
        return f"'{path}' no es una carpeta."
    try:
        items = sorted(p.iterdir(), key=_mtime, reverse=True)
    except OSError as e:
        return f"No pude leer la carpeta: {e}"
    if not items:
        return "La carpeta está vacía."
    shown = "\n".join(f"- {i.name}{'/' if i.is_dir() else ''}" for i in items[:15])
    return f"{len(items)} elementos, los más recientes:\n{shown}"


def create_folder(path: str) -> str:
    p = _resolve(path)
    p.mkdir(parents=True, exist_ok=True)
    return f"Carpeta lista: {p}"


def move_file(source: str, destination: str, copy: bool = False) -> str:
    src, dst = _resolve(source), _resolve(destination)
    if not src.exists():
        return f"No existe '{source}'."
    if dst.is_dir():
        dst = dst / src.name
    if dst.exists():
        return f"Ya existe {dst}; no sobrescribo nada."
    dst.parent.mkdir(parents=True, exist_ok=True)
    if copy:
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        return f"Copiado a {dst}."
    shutil.move(str(src), str(dst))
    return f"Movido a {dst}."


TOOL_DEFINITIONS = [
    {
        "name": "find_files",
        "description": (
            "Busca archivos o carpetas por nombre en Escritorio, Documentos, Descargas, Imágenes, Vídeos y Música "
            "(o en una carpeta dada). Devuelve rutas completas, los más recientes primero."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Palabras del nombre, p. ej. 'factura marzo'."},
                "folder": {"type": "string", "description": "Opcional: carpeta donde buscar (ej. 'descargas')."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "open_path",
        "description": "Abre un archivo con su programa predeterminado, o una carpeta en el Explorador.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Ruta completa o carpeta conocida ('descargas')."}},
            "required": ["path"],
        },
    },
    {
        "name": "list_folder",
        "description": "Lista el contenido de una carpeta (lo más reciente primero).",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Ruta o carpeta conocida ('escritorio')."}},
            "required": ["path"],
        },
    },
    {
        "name": "create_folder",
        "description": "Crea una carpeta nueva.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Ruta completa de la carpeta."}},
            "required": ["path"],
        },
    },
    {
        "name": "move_file",
        "description": "Mueve (o copia con copy=true) un archivo o carpeta a otro lugar. No sobrescribe ni borra.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Ruta completa del archivo (búscala antes si no la sabes)."},
                "destination": {"type": "string", "description": "Carpeta o ruta destino."},
                "copy": {"type": "boolean", "description": "true para copiar en vez de mover."},
            },
            "required": ["source", "destination"],
        },
    },
]

HANDLERS = {
    "find_files": find_files, "open_path": open_path, "list_folder": list_folder,
    "create_folder": create_folder, "move_file": move_file,
}
