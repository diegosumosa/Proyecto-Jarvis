"""Oídos de Jarvis: captura el micrófono y transcribe con Whisper (Groq)."""
import audioop
import os
import time

import speech_recognition as sr
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

# whisper-large-v3 es más preciso que la versión "turbo" (que es más rápida).
STT_MODEL = "whisper-large-v3"
# Pista de vocabulario: ayuda a Whisper con el nombre y las palabras que más usas.
STT_PROMPT = (
    "Jarvis, Spotify, Wikipedia, Discord, pausa la música, siguiente canción, abre la calculadora. "
    "Oye Jarvis, pon mi playlist de tus me gusta en aleatorio, ¿qué suena ahora?, mira mi pantalla."
)
# Frases que Whisper inventa cuando solo hay silencio o ruido.
HALLUCINATIONS = (
    "subtítulos", "subtitulos", "amara.org", "gracias por ver", "suscríbete", "suscribete",
    "thanks for watching", "música", "musica",
)

# Frases sueltas que Whisper inventa con ruido; se descartan si son todo lo que "se oyó".
HALLUCINATION_EXACT = ("gracias", "muchas gracias", "ok", "listo")
NO_SPEECH_MAX = 0.5  # probabilidad (0-1) de que el audio no tenga voz; por encima se descarta
last_no_speech_prob = 0.0  # de la última transcripción; main.py lo usa para ser más estricto
mic_level = 0.0  # volumen actual del micrófono (RMS), para que la interfaz lo muestre en vivo
last_stt_seconds = 0.0  # lo que tardó Whisper en la última transcripción
last_peak = 0.0  # volumen máximo de la última frase escuchada (se anota en el registro)
mic_threshold = 300.0  # volumen a partir del cual se considera que hay voz

MIN_ENERGY = 400  # el umbral de voz nunca baja de aquí, aunque la sala esté en silencio


class _Recognizer(sr.Recognizer):
    """Igual que el original, pero el umbral dinámico no puede caer por debajo de MIN_ENERGY:
    si bajara casi a cero, un chasquido o un soplido contaría como voz y Whisper inventaría frases."""

    @property
    def energy_threshold(self):
        return self._energy_threshold

    @energy_threshold.setter
    def energy_threshold(self, value):
        self._energy_threshold = max(value, MIN_ENERGY)


_recognizer = _Recognizer()
_recognizer.dynamic_energy_threshold = True
_recognizer.pause_threshold = 1.0  # segundos de silencio para dar por terminada la frase
_calibrated = False
_client = None


def _get_client():
    global _client
    if _client is None:
        _client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    return _client


def _set_level(level: float) -> None:
    global mic_level, mic_threshold, last_peak
    mic_level = level
    last_peak = max(last_peak, level)
    mic_threshold = _recognizer.energy_threshold


def _watch_level(source) -> None:
    """Mide el volumen de cada fragmento de audio que lee el micrófono (sin alterarlo)."""
    stream = source.stream
    original_read = stream.read

    def read(size, *args, **kwargs):
        data = original_read(size, *args, **kwargs)
        try:
            _set_level(float(audioop.rms(data, source.SAMPLE_WIDTH)))
        except audioop.error:
            pass
        return data

    stream.read = read


def listen(language: str = "es", skip=lambda: False, timeout: float = 8) -> str:
    """Escucha una frase y devuelve el texto ('' si no se entendió).
    `skip` se consulta antes de enviar el audio a Groq: si devuelve True se descarta."""
    global _calibrated, last_peak
    with sr.Microphone() as source:
        if not _calibrated:
            # Mide el ruido de fondo para ajustar el umbral.
            _recognizer.adjust_for_ambient_noise(source, duration=1)
            _calibrated = True
        print("Escuchando...")
        last_peak = 0.0
        _watch_level(source)
        try:
            audio = _recognizer.listen(source, timeout=timeout, phrase_time_limit=30)
        except sr.WaitTimeoutError:
            return ""
        finally:
            _set_level(0.0)

    global last_no_speech_prob
    last_no_speech_prob = 0.0
    if skip():
        return ""
    global last_stt_seconds
    wav = audio.get_wav_data(convert_rate=16000, convert_width=2)
    started = time.time()
    try:
        result = _get_client().audio.transcriptions.create(
            file=("audio.wav", wav),
            model=STT_MODEL,
            language=language,
            temperature=0.0,
            prompt=STT_PROMPT,
            response_format="verbose_json",
        )
    except Exception as e:
        print(f"Error de transcripción: {e}")
        return ""
    last_stt_seconds = time.time() - started
    text = result.text.strip()
    segments = getattr(result, "segments", None) or []
    if segments:
        last_no_speech_prob = max(seg.get("no_speech_prob", 0.0) for seg in segments)
        if last_no_speech_prob > NO_SPEECH_MAX:
            return ""
    if text.lower().strip(" .¡!¿?") in HALLUCINATION_EXACT:
        return ""
    if text.lower().strip(" .¡!¿?") in HALLUCINATIONS or any(
        h in text.lower() for h in HALLUCINATIONS[:6]
    ):
        return ""
    return text


if __name__ == "__main__":
    print("Dijiste:", listen())
