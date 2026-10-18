"""Descubre las apps y juegos instalados (Menú Inicio) para que Jarvis los abra por nombre."""
import ctypes
import difflib
import json
import os
import subprocess
import threading
import time
import unicodedata
from ctypes import wintypes
from pathlib import Path

_SKIP = ("uninstall", "desinstalar", "readme", "faq", "documentation", "website", "support", "help", "ayuda")
_START_MENUS = (
    Path(os.environ.get("ProgramData", "")) / "Microsoft/Windows/Start Menu/Programs",
    Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
)

_index = None  # nombre normalizado -> (nombre original, tipo, destino)
_lock = threading.Lock()


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn").strip()


def _scan_shortcuts(index: dict) -> None:
    """Accesos directos .lnk y .url (aquí aparecen los juegos de Steam)."""
    for root in _START_MENUS:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.suffix.lower() in (".lnk", ".url") and not any(s in path.stem.lower() for s in _SKIP):
                index.setdefault(_normalize(path.stem), (path.stem, "file", str(path)))


def _scan_start_apps(index: dict) -> None:
    """Apps de la tienda y otras que Windows lista en el Menú Inicio."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[Console]::OutputEncoding = [Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress"],
            capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW,
        ).stdout.decode("utf-8-sig", errors="replace")
        apps = json.loads(out or "[]")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return
    if isinstance(apps, dict):
        apps = [apps]
    for app in apps:
        name, app_id = app.get("Name", ""), app.get("AppID", "")
        if name and app_id and not any(s in name.lower() for s in _SKIP):
            index.setdefault(_normalize(name), (name, "appid", app_id))


def get_index() -> dict:
    global _index
    with _lock:
        if _index is None:
            index = {}
            _scan_shortcuts(index)
            _scan_start_apps(index)
            _index = index
        return _index


def prewarm() -> None:
    """Construye el índice en segundo plano para que la primera orden no tarde."""
    threading.Thread(target=get_index, daemon=True).start()


def find(query: str):
    """Devuelve (coincidencia, candidatos). La coincidencia es (nombre, tipo, destino) o None;
    los candidatos son nombres parecidos cuando hay duda."""
    index = get_index()
    q = _normalize(query)
    if not q:
        return None, []
    if q in index:
        return index[q], []
    contained = [k for k in index if q in k]
    if len(contained) == 1:
        return index[contained[0]], []
    if contained:
        starting = [k for k in contained if k.startswith(q)]
        if len(starting) == 1:
            return index[starting[0]], []
        return None, [index[k][0] for k in sorted(contained, key=len)[:5]]
    close = difflib.get_close_matches(q, index.keys(), n=3, cutoff=0.7)
    if close:
        return index[close[0]], []
    return None, []


def launch(kind: str, target: str) -> None:
    if kind == "file":
        os.startfile(target)
    else:  # appid
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{target}"])


# --- Cerrar apps ---
_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
_WM_CLOSE = 0x0010
# Nunca se cierran: el propio Jarvis y el shell de Windows.
_PROTECTED = {"pythonw", "python", "explorer", "dwm", "winlogon", "searchhost", "startmenuexperiencehost"}


def _windows() -> list:
    """Ventanas visibles con título: lista de (hwnd, título, nombre del exe sin extensión, pid)."""
    result = []
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _):
        if not _user32.IsWindowVisible(hwnd):
            return True
        length = _user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        title = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(hwnd, title, length + 1)
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = _kernel32.OpenProcess(0x1000, False, pid.value)  # QUERY_LIMITED_INFORMATION
        exe = ""
        if handle:
            buf = ctypes.create_unicode_buffer(520)
            size = wintypes.DWORD(520)
            _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
            _kernel32.CloseHandle(handle)
            exe = Path(buf.value).stem.lower()
        result.append((hwnd, title.value, exe, pid.value))
        return True

    _user32.EnumWindows(enum_proc(callback), 0)
    return result


def close(query: str, force: bool = False) -> str:
    """Cierra las ventanas de la app pedida. Devuelve un mensaje para el usuario."""
    names = {_normalize(query)}
    match, _ = find(query)
    if match:
        names.add(_normalize(match[0]))
    names.discard("")
    if not names:
        return "No me dijiste qué cerrar."

    targets = []
    for hwnd, title, exe, pid in _windows():
        if exe in _PROTECTED:
            continue
        haystacks = (_normalize(title), _normalize(exe))
        if any(n in h or (len(h) >= 4 and h in n) for n in names for h in haystacks):
            targets.append((hwnd, title, exe, pid))
    if not targets:
        return f"No veo ninguna ventana abierta de '{query}'."

    label = match[0] if match else query
    if force:
        for pid in {t[3] for t in targets}:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        return f"Cerré {label} a la fuerza."

    for hwnd, *_ in targets:
        _user32.PostMessageW(hwnd, _WM_CLOSE, 0, 0)  # petición normal, como pulsar la X
    time.sleep(1.5)
    remaining = {h for h, *_ in _windows()}
    if any(t[0] in remaining for t in targets):
        return f"Le pedí a {label} que se cerrara, pero sigue abierta (quizá pregunta si guardar). Puedo forzar el cierre si quieres."
    return f"Cerré {label}."
