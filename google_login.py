"""Autoriza a Jarvis a usar tu Google Calendar y Gmail (se hace una sola vez).

Pasos previos:
1. Entra a https://console.cloud.google.com y crea un proyecto (p. ej. "Jarvis").
2. En "APIs y servicios > Biblioteca" habilita "Google Calendar API" y "Gmail API".
3. En "Pantalla de consentimiento de OAuth": tipo "Externo", agrega tu correo como
   "Usuario de prueba".
4. En "Credenciales > Crear credenciales > ID de cliente de OAuth": tipo "Aplicación
   de escritorio". Descarga el JSON y guárdalo en esta carpeta como credentials.json.
5. Ejecuta:  .\\venv\\Scripts\\python google_login.py   (se abre el navegador para aceptar).
"""
from google_auth_oauthlib.flow import InstalledAppFlow

from google_tools import CREDENTIALS_FILE, SCOPES, TOKEN_FILE

if not CREDENTIALS_FILE.exists():
    raise SystemExit(f"Falta {CREDENTIALS_FILE}. Lee los pasos al inicio de este archivo.")

flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
creds = flow.run_local_server(port=0)
TOKEN_FILE.parent.mkdir(exist_ok=True)
TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
print("Listo: Jarvis ya puede usar tu calendario y leer tus correos.")
