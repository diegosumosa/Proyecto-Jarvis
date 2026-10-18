"""Reproduce una frase con distintas voces en español para que elijas la tuya."""
from audio_out import speak

VOICES = [
    # Voces multilingües: las más naturales; hablan español con un leve acento.
    ("en-US-AndrewMultilingualNeural", "Multilingüe, hombre"),
    ("en-US-BrianMultilingualNeural", "Multilingüe, hombre"),
    ("en-US-AvaMultilingualNeural", "Multilingüe, mujer"),
    ("en-US-EmmaMultilingualNeural", "Multilingüe, mujer"),
    ("de-DE-FlorianMultilingualNeural", "Multilingüe (alemán), hombre"),
    ("fr-FR-VivienneMultilingualNeural", "Multilingüe (francés), mujer"),
    # Voces nativas en español, para comparar.
    ("es-MX-JorgeNeural", "México, hombre"),
    ("es-MX-DaliaNeural", "México, mujer"),
    ("es-ES-AlvaroNeural", "España, hombre"),
    ("es-ES-ElviraNeural", "España, mujer"),
    ("es-ES-XimenaNeural", "España, mujer (más nueva)"),
]

for i, (voice, label) in enumerate(VOICES, 1):
    print(f"{i}. {voice}  ({label})")
    speak("Hola, soy Jarvis, tu asistente virtual. ¿En qué puedo ayudarte hoy?", voice)

print("\nPara elegir una, cambia VOICE en audio_out.py.")
