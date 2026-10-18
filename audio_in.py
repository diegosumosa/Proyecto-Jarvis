"""Oídos de Jarvis: captura el micrófono y transcribe con Whisper (Groq)."""
import os

import speech_recognition as sr
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

# whisper-large-v3 es más preciso que la versión "turbo" (que es más rápida).
STT_MODEL = "whisper-large-v3"
# Pista de vocabulario: ayuda a Whisper con el nombre y las palabras que más usas.
STT_PROMPT = "Jarvis, Spotify, Wikipedia, Discord, pausa la música, siguiente canción, abre la calculadora."
# Frases que Whisper inventa cuando solo hay silencio o ruido.
HALLUCINATIONS = (
    "subtítulos", "subtitulos", "amara.org", "gracias por ver", "suscríbete", "suscribete",
    "thanks for watching", "música", "musica",
)

_recognizer = sr.Recognizer()
_recognizer.dynamic_energy_threshold = True
_recognizer.pause_threshold = 2.0  # segundos de silencio para dar por terminada la frase
_calibrated = False
_client = None


def _get_client():
    global _client
    if _client is None:
        _client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    return _client


def listen(language: str = "es", skip=lambda: False) -> str:
    """Escucha una frase y devuelve el texto ('' si no se entendió).
    `skip` se consulta antes de enviar el audio a Groq: si devuelve True se descarta."""
    global _calibrated
    with sr.Microphone() as source:
        if not _calibrated:
            # Mide el ruido de fondo para ajustar el umbral.
            _recognizer.adjust_for_ambient_noise(source, duration=1)
            _calibrated = True
        print("Escuchando...")
        try:
            audio = _recognizer.listen(source, timeout=8, phrase_time_limit=30)
        except sr.WaitTimeoutError:
            return ""

    if skip():
        return ""
    wav = audio.get_wav_data(convert_rate=16000, convert_width=2)
    try:
        result = _get_client().audio.transcriptions.create(
            file=("audio.wav", wav),
            model=STT_MODEL,
            language=language,
            temperature=0.0,
            prompt=STT_PROMPT,
        )
    except Exception as e:
        print(f"Error de transcripción: {e}")
        return ""
    text = result.text.strip()
    if text.lower().strip(" .¡!¿?") in HALLUCINATIONS or any(
        h in text.lower() for h in HALLUCINATIONS[:6]
    ):
        return ""
    return text


if __name__ == "__main__":
    print("Dijiste:", listen())
