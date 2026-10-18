"""Bucle principal de Jarvis: oír -> pensar -> hablar."""
import unicodedata

from audio_in import listen
from audio_out import speak
from claude_brain import ask_claude

NAME_VARIANTS = ("jarvis", "yarvis", "harvis", "jarbis", "yarbis", "jarvi", "yarvi", "yervis", "jervis")


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def is_shutdown(text: str) -> bool:
    """True si dijo 'apágate/apaga/apagar' (el reconocedor a veces escribe mal 'Jarvis')."""
    t = _normalize(text)
    return "apaga" in t and any(n in t for n in NAME_VARIANTS)


def main() -> None:
    speak("Jarvis en línea.")
    while True:
        text = listen()
        if not text:
            continue
        print(f"Tú: {text}")
        if is_shutdown(text):
            speak("Apagando sistemas. Hasta luego.")
            break
        try:
            reply = ask_claude(text)
        except Exception as e:
            print(f"Error: {e}")
            reply = "Tuve un problema al procesar tu solicitud."
        print(f"Jarvis: {reply}")
        speak(reply)


if __name__ == "__main__":
    main()
