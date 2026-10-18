"""Voz de Jarvis: edge-tts (voces neuronales, requiere internet) con respaldo offline pyttsx3."""
import asyncio
import ctypes
import os
import queue
import re
import tempfile
import threading
import time

import edge_tts

# Cambia aquí la voz. Ejecuta voice_demo.py para escucharlas.
VOICE = "fr-FR-VivienneMultilingualNeural"
RATE = "+10%"  # velocidad: "+0%" normal, "+20%" más rápido, "-10%" más lento

_winmm = ctypes.windll.winmm


_cancel = threading.Event()


def stop_speaking() -> None:
    """Corta la voz que esté sonando (se puede llamar desde otro hilo)."""
    _cancel.set()


def play_mp3(path: str) -> None:
    """Reproduce un mp3 con la API multimedia de Windows; se puede cortar con stop_speaking()."""
    alias = "jarvis_audio"
    _winmm.mciSendStringW(f'open "{path}" type mpegvideo alias {alias}', None, 0, None)
    _winmm.mciSendStringW(f"play {alias}", None, 0, None)
    status = ctypes.create_unicode_buffer(32)
    while not _cancel.is_set():
        _winmm.mciSendStringW(f"status {alias} mode", status, 32, None)
        if status.value != "playing":
            break
        time.sleep(0.05)
    _winmm.mciSendStringW(f"stop {alias}", None, 0, None)
    _winmm.mciSendStringW(f"close {alias}", None, 0, None)


async def _synthesize(text: str, voice: str, path: str) -> None:
    await edge_tts.Communicate(text, voice, rate=RATE).save(path)


def _speak_offline(text: str) -> None:
    import pyttsx3

    engine = pyttsx3.init()
    engine.say(text)
    engine.runAndWait()
    engine.stop()


def _split_sentences(text: str, min_len: int = 40) -> list:
    """Parte el texto en frases; junta las muy cortas para que la voz suene natural."""
    parts = re.split(r"(?<=[.!?…])\s+", text.strip())
    chunks = []
    for part in parts:
        if chunks and len(chunks[-1]) < min_len:
            chunks[-1] += " " + part
        else:
            chunks.append(part)
    return [c for c in chunks if c]


def _synthesize_to_file(text: str, voice: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    try:
        asyncio.run(_synthesize(text, voice, path))
    except Exception:
        os.remove(path)
        raise
    return path


def speak(text: str, voice: str = None) -> None:
    """Sintetiza por frases: empieza a hablar con la primera mientras prepara las siguientes."""
    _cancel.clear()
    voice = voice or VOICE
    chunks = _split_sentences(text) or [text]
    ready = queue.Queue()  # (texto, ruta mp3 o None si falló)

    def producer():
        for chunk in chunks:
            if _cancel.is_set():
                break
            try:
                ready.put((chunk, _synthesize_to_file(chunk, voice)))
            except Exception as e:  # sin internet u otro fallo: esa frase irá con la voz de Windows
                print(f"(edge-tts falló: {e}; usando voz offline)")
                ready.put((chunk, None))
        ready.put(None)

    threading.Thread(target=producer, daemon=True).start()
    while (item := ready.get()) is not None:
        chunk, path = item
        try:
            if _cancel.is_set():
                continue
            if path:
                play_mp3(path)
            else:
                _speak_offline(chunk)
        finally:
            if path:
                try:
                    os.remove(path)
                except OSError:
                    pass


if __name__ == "__main__":
    speak("Hola, soy Jarvis.")
