"""Oídos de Jarvis: captura el micrófono y transcribe con Whisper (Groq)."""
import os

import speech_recognition as sr
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

STT_MODEL = "whisper-large-v3-turbo"

_recognizer = sr.Recognizer()
_recognizer.dynamic_energy_threshold = True
_recognizer.pause_threshold = 0.8  # segundos de silencio para dar por terminada la frase
_calibrated = False
_client = None


def _get_client():
    global _client
    if _client is None:
        _client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    return _client


def listen(language: str = "es") -> str:
    """Escucha una frase y devuelve el texto ('' si no se entendió)."""
    global _calibrated
    with sr.Microphone() as source:
        if not _calibrated:
            # Mide el ruido de fondo para ajustar el umbral.
            _recognizer.adjust_for_ambient_noise(source, duration=1)
            _calibrated = True
        print("Escuchando...")
        try:
            audio = _recognizer.listen(source, timeout=8, phrase_time_limit=15)
        except sr.WaitTimeoutError:
            return ""

    wav = audio.get_wav_data(convert_rate=16000, convert_width=2)
    try:
        result = _get_client().audio.transcriptions.create(
            file=("audio.wav", wav),
            model=STT_MODEL,
            language=language,
            temperature=0.0,
        )
    except Exception as e:
        print(f"Error de transcripción: {e}")
        return ""
    return result.text.strip()


if __name__ == "__main__":
    print("Dijiste:", listen())
