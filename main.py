"""Bucle principal de Jarvis: oír -> pensar -> hablar."""
import re
import threading
import time
import unicodedata
from datetime import datetime
from pathlib import Path

import audio_in
import scheduler
from audio_in import listen
from audio_out import speak
from claude_brain import ask_claude

NAME_VARIANTS = ("jarvis", "yarvis", "harvis", "jarbis", "yarbis", "jarvi", "yarvi", "yervis", "jervis", "arvis", "garvis", "charvis", "travis", "jarves", "harvi")
# Palabras que pueden ir antes del nombre ("oye, Jarvis"). Con otra cosa delante ("siento que Jarvis...")
# se habla DE Jarvis, no A Jarvis, y no se activa.
FILLERS = {"oye", "hey", "ey", "hola", "y", "eh", "ok", "okay", "bueno", "pues", "ahora", "mira", "a", "ya"}
WAKE_WINDOW = 8  # segundos que sigue atento tras una respuesta, sin repetir su nombre
FOLLOWUP_MIN_WORDS = 2  # sin decir 'Jarvis', las frases de una sola palabra se ignoran
FOLLOWUP_MAX_NO_SPEECH = 0.15  # y se exige más seguridad de que hubo voz de verdad
# Palabras con las que una frase no puede terminar: si acaba así, se cortó a medias.
DANGLING = {"de", "del", "a", "al", "el", "la", "los", "las", "un", "una", "y", "o", "que", "con", "en", "para", "por", "mi", "mis", "tu", "me", "te", "se", "lo", "pon", "ponme"}
LOG_FILE = Path(__file__).parent / "data" / "jarvis.log"
WAKE_MAX_POSITION = 3  # "Jarvis" debe estar entre las primeras palabras ("oye Jarvis, ...")


def log(message: str) -> None:
    """Anota lo que oyó y decidió Jarvis (data/jarvis.log), para saber por qué actuó. Jarvis corre
    sin consola, así que los print no se ven."""
    print(message)
    try:
        LOG_FILE.parent.mkdir(exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}\n")
    except OSError:
        pass


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def is_shutdown(text: str) -> bool:
    """True para 'apágate (Jarvis)', 'apaga a Jarvis', 'Jarvis, apágate' o 'ciérrate Jarvis'.
    Tolera que Whisper se coma la 'a' inicial ('págate'). Frases como
    'Jarvis, apaga la música' NO apagan el programa."""
    t = _normalize(text)
    t = re.sub(r"[^\w\s]", " ", t)  # sin puntuación
    names = "|".join(NAME_VARIANTS)
    reflexive = r"(?:a\s?pa[gd]ate|pa[gd]ate|apagarte|cierrate|cerrarte|desactivate)"
    verb = r"(?:apaga|apagar|pagar|cierra|cerrar|desactiva|desactivar)"
    if re.search(rf"\b{reflexive}\b", t) and re.search(rf"\b(?:{names})\b", t):
        return True
    if re.search(rf"\b{verb}\s+(?:a\s+)?(?:{names})\b", t):
        return True
    return bool(re.search(rf"\b(?:{names})\s+{verb}\s*$", t))


def extract_command(text: str):
    """Si la frase empieza con 'Jarvis' ('Jarvis, pon música') o termina con él ('pon música, Jarvis')
    devuelve la orden ('' si solo dijo el nombre). Devuelve None si no lo llamó."""
    tokens = re.findall(r"\w+", text)
    for i, token in enumerate(tokens[:WAKE_MAX_POSITION]):
        if _normalize(token) in NAME_VARIANTS:
            if all(_normalize(t) in FILLERS for t in tokens[:i]):
                return " ".join(tokens[i + 1:])
            break  # hay otras palabras antes: están hablando de Jarvis, no con él
    for i in range(max(len(tokens) - 4, 0), len(tokens)):  # el nombre al final de la frase
        if _normalize(tokens[i]) in NAME_VARIANTS:
            return " ".join(tokens[:i] + tokens[i + 1:])
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

    scheduler.start()
    say("Jarvis en línea.")
    while not stop.is_set():
        while not scheduler.alerts.empty():  # temporizadores, alarmas y recordatorios
            say(scheduler.alerts.get())
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

        # Si la frase quedó cortada en una pausa ("...pon la playlist de"), espera el resto y la une.
        for _ in range(2):
            words = _normalize(text).strip(" .,").split()
            if not (text.endswith(("...", "…")) or (words and words[-1] in DANGLING)):
                break
            rest = listen(skip=lambda: muted.is_set() or stop.is_set(), timeout=3)
            if not rest:
                break
            text = text.rstrip(". …") + " " + rest.lstrip(". …")

        log(f"[oído] {text!r} (stt={audio_in.last_stt_seconds:.1f}s, sin_voz={audio_in.last_no_speech_prob:.2f}, pico={audio_in.last_peak:.0f}, umbral={audio_in.mic_threshold:.0f})")
        if is_shutdown(text):
            say("Apagando sistemas. Hasta luego.")
            break

        command = extract_command(text)
        if command is None:
            if time.time() > awake_until:
                log("[ignorado] no dijo 'Jarvis'")
                continue
            if len(text.split()) < FOLLOWUP_MIN_WORDS or audio_in.last_no_speech_prob > FOLLOWUP_MAX_NO_SPEECH:
                log("[ignorado] seguimiento dudoso (muy corto o poco seguro de que fuera voz)")
                continue
            command = text  # sigue en modo conversación
        elif not command:
            say("Dime.")
            awake_until = time.time() + WAKE_WINDOW
            continue

        log(f"[orden] {command}")
        on_state("thinking")
        started = time.time()
        try:
            reply = ask_claude(command)
        except Exception as e:
            log(f"[error] {e}")
            reply = "Tuve un problema al procesar tu solicitud."
        if interrupt.is_set():  # lo cortaron mientras pensaba: se descarta la respuesta
            interrupt.clear()
            print("(respuesta descartada)")
            continue
        log(f"[respuesta] ({time.time() - started:.1f}s) {reply}")
        say(reply)
        interrupt.clear()
        # Tras responder sigue atento unos segundos sin oír su nombre (las frases dudosas o de una sola
        # palabra se siguen ignorando, para que la tele o el ruido no se cuelen como órdenes).
        awake_until = time.time() + WAKE_WINDOW
    on_state("idle")


if __name__ == "__main__":
    run()
