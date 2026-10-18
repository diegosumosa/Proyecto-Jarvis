"""Voz de Jarvis: edge-tts (voces neuronales, requiere internet) con respaldo offline pyttsx3."""
import asyncio
import ctypes
import os
import tempfile
import threading
import time

import edge_tts

# Cambia aquí la voz. Ejecuta voice_demo.py para escucharlas.
VOICE = "es-MX-JorgeNeural"
RATE = "+30%"  # velocidad: "+0%" normal, "+20%" más rápido, "-10%" más lento

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


def speak(text: str, voice: str = None) -> None:
    _cancel.clear()
    fd, path = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    try:
        asyncio.run(_synthesize(text, voice or VOICE, path))
        if not _cancel.is_set():
            play_mp3(path)
    except Exception as e:  # sin internet u otro fallo: usa la voz de Windows
        print(f"(edge-tts falló: {e}; usando voz offline)")
        _speak_offline(text)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


if __name__ == "__main__":
    speak("Hola, soy Jarvis.")
