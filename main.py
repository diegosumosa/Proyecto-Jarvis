"""Bucle principal de Jarvis: oír -> pensar -> hablar."""
import re
import threading
import time
import unicodedata

from audio_in import listen
from audio_out import speak
from claude_brain import ask_claude

NAME_VARIANTS = ("jarvis", "yarvis", "harvis", "jarbis", "yarbis", "jarvi", "yarvi", "yervis", "jervis")
WAKE_WINDOW = 12  # segundos que sigue atento tras una respuesta, sin repetir su nombre
WAKE_MAX_POSITION = 3  # "Jarvis" debe estar entre las primeras palabras ("oye Jarvis, ...")


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def is_shutdown(text: str) -> bool:
    """True solo para 'apágate (Jarvis)' o 'apaga/apagar a Jarvis'.
    Frases como 'Jarvis, apaga la música' NO apagan el programa."""
    t = _normalize(text)
    names = "|".join(NAME_VARIANTS)
    if re.search(r"\bapagate\b", t) and any(n in t for n in NAME_VARIANTS):
        return True
    return bool(re.search(rf"\bapagar?\s+(a\s+)?({names})\b", t))


def extract_command(text: str):
    """Si la frase empieza con 'Jarvis' devuelve lo que viene después ('' si solo dijo el nombre).
    Devuelve None si no lo llamó."""
    tokens = re.findall(r"\w+", text)
    for i, token in enumerate(tokens[:WAKE_MAX_POSITION]):
        if _normalize(token) in NAME_VARIANTS:
            return " ".join(tokens[i + 1:])
    return None


def run(on_state=lambda state: None, stop: threading.Event = None, muted: threading.Event = None,
        interrupt: threading.Event = None) -> None:
    """Ejecuta el bucle. `on_state` recibe: idle, listening, thinking, speaking.
    Si `muted` está activo, Jarvis no escucha. Si `interrupt` se activa mientras piensa o habla,
    se corta la respuesta."""
    stop = stop or threading.Event()
    muted = muted or threading.Event()
    interrupt = interrupt or threading.Event()
    awake_until = 0.0

    def say(text: str) -> None:
        on_state("speaking")
        try:
            speak(text)
        finally:
            on_state("idle")

    say("Jarvis en línea.")
    while not stop.is_set():
        if muted.is_set():
            on_state("idle")
            stop.wait(0.3)
            continue

        on_state("listening")
        text = listen(skip=lambda: muted.is_set() or stop.is_set())
        if stop.is_set():
            break
        if not text or muted.is_set():
            continue

        if is_shutdown(text):
            print(f"Tú: {text}")
            say("Apagando sistemas. Hasta luego.")
            break

        command = extract_command(text)
        if command is None:
            if time.time() > awake_until:
                print(f"(ignorado, sin 'Jarvis'): {text}")
                continue
            command = text  # sigue en modo conversación
        elif not command:
            say("Dime.")
            awake_until = time.time() + WAKE_WINDOW
            continue

        print(f"Tú: {command}")
        on_state("thinking")
        try:
            reply = ask_claude(command)
        except Exception as e:
            print(f"Error: {e}")
            reply = "Tuve un problema al procesar tu solicitud."
        if interrupt.is_set():  # lo cortaron mientras pensaba: se descarta la respuesta
            interrupt.clear()
            print("(respuesta descartada)")
            continue
        print(f"Jarvis: {reply}")
        say(reply)
        interrupt.clear()
        awake_until = time.time() + WAKE_WINDOW
    on_state("idle")


if __name__ == "__main__":
    run()
