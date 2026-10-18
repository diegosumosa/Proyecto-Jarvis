"""Autoriza a Jarvis a controlar tu Spotify (se hace una sola vez).

Antes: pon SPOTIFY_CLIENT_ID=... en el archivo .env (está en el dashboard de Spotify > Settings).
Ejecuta:  .\\venv\\Scripts\\python spotify_login.py   (se abre el navegador para aceptar).
"""
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import spotify_tools

url, verifier = spotify_tools.make_login_url()
result = {}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
        result["code"] = params.get("code", [None])[0]
        result["error"] = params.get("error", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write("Listo, ya puedes cerrar esta pestaña.".encode("utf-8"))

    def log_message(self, *args):
        pass


server = HTTPServer(("127.0.0.1", 8888), Handler)
webbrowser.open(url)
print("Se abrió el navegador. Acepta el permiso en Spotify...")
server.handle_request()
server.server_close()

if not result.get("code"):
    raise SystemExit(f"No se autorizó: {result.get('error')}")
spotify_tools.exchange_code(result["code"], verifier)
print("Listo: Jarvis ya puede controlar tu Spotify.")
