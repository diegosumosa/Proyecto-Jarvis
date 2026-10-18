"""Jarvis con interfaz: un orbe naranja que brilla y se mueve cuando habla.

Arrastra el orbe para moverlo. Botón del micrófono (o tecla M): silenciar/activar.
Botón de stop (o tecla S): corta la respuesta que está dando.
Doble clic en el orbe o Esc: cerrar.
Ejecuta:  python app.py
"""
import math
import random
import threading
import time
import tkinter as tk

import audio_in
import audio_out
import main

SIZE = 300
CENTER = SIZE // 2
BASE_RADIUS = 48
TRANSPARENT = "#010101"  # color "clave": se vuelve transparente en Windows
ORANGE = (255, 140, 20)
GRAY = (120, 120, 125)
GREEN = (61, 220, 132)
HEARING_HOLD = 0.8  # segundos que el anillo sigue verde después de la última señal de voz
RED = "#e5484d"
FPS_MS = 33
BTN_Y = SIZE - 26  # centro del botón del micrófono
BTN_R = 17
BTN_GAP = 26  # separación del centro: mic a la izquierda, stop a la derecha

# Intensidad objetivo del brillo según el estado (0 = apagado, 1 = máximo).
TARGET = {"idle": 0.0, "listening": 0.15, "thinking": 0.3, "speaking": 1.0}


def _blend(color, amount):
    """Mezcla un color con el fondo transparente; amount=0 -> invisible, 1 -> color pleno."""
    # Se mezcla hacia el color transparente: con amount=0 el píxel desaparece del todo.
    return "#%02x%02x%02x" % tuple(int(1 + (c - 1) * amount) for c in color)


class JarvisOrb:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Jarvis")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", TRANSPARENT)
        self.root.configure(bg=TRANSPARENT)
        x = self.root.winfo_screenwidth() - SIZE - 40
        y = self.root.winfo_screenheight() - SIZE - 80
        self.root.geometry(f"{SIZE}x{SIZE}+{x}+{y}")

        self.canvas = tk.Canvas(
            self.root, width=SIZE, height=SIZE, bg=TRANSPARENT, highlightthickness=0
        )
        self.canvas.pack()

        self.state = "idle"
        self.level = 0.0  # intensidad actual (suavizada)
        self.mic = 0.0  # volumen del micrófono (suavizado, 0-1)
        self.hearing = False  # True mientras detecta tu voz
        self._voice_until = 0.0
        self.pulse = 0.0  # amplitud de la "voz" simulada
        self.stop = threading.Event()
        self.muted = threading.Event()
        self.interrupt = threading.Event()
        self._drag = (0, 0)

        self.canvas.bind("<ButtonPress-1>", self._start_drag)
        self.canvas.bind("<B1-Motion>", self._do_drag)
        self.canvas.bind("<Double-Button-1>", lambda e: self.close())
        self.canvas.tag_bind("mic", "<ButtonPress-1>", lambda e: self.toggle_mute())
        self.canvas.tag_bind("mic", "<Double-Button-1>", lambda e: self.toggle_mute())
        self.canvas.tag_bind("stop", "<ButtonPress-1>", lambda e: self.interrupt_reply())
        self.canvas.tag_bind("stop", "<Double-Button-1>", lambda e: self.interrupt_reply())
        self.root.bind("s", lambda e: self.interrupt_reply())
        self.root.bind("<Escape>", lambda e: self.close())
        self.root.bind("m", lambda e: self.toggle_mute())

    # --- ventana ---
    def _start_drag(self, e):
        self._drag = (e.x, e.y)

    def _do_drag(self, e):
        x = self.root.winfo_x() + e.x - self._drag[0]
        y = self.root.winfo_y() + e.y - self._drag[1]
        self.root.geometry(f"+{x}+{y}")

    def close(self):
        self.stop.set()
        self.root.destroy()

    def toggle_mute(self):
        if self.muted.is_set():
            self.muted.clear()
        else:
            self.muted.set()
        return "break"

    def interrupt_reply(self):
        """Corta la voz y descarta la respuesta si Jarvis está pensando o hablando."""
        if self.state in ("thinking", "speaking"):
            self.interrupt.set()
            audio_out.stop_speaking()
        return "break"

    # --- animación ---
    def set_state(self, state):
        self.state = state  # solo asigna un str: seguro entre hilos

    def _draw_status(self, c, muted):
        if muted:
            text, color = "Silenciado", (150, 150, 155)
        elif self.state == "listening":
            text, color = ("Te escucho…", GREEN) if self.hearing else ("Esperando…", (190, 190, 195))
        else:
            text = {"thinking": "Pensando…", "speaking": "Hablando"}.get(self.state, "")
            color = ORANGE
        if text:
            c.create_text(CENTER, 14, text=text, fill=_blend(color, 0.9), font=("Segoe UI", 10, "bold"))

    def _draw_mic_button(self, c, muted):
        cx, cy = CENTER - BTN_GAP, BTN_Y
        c.create_oval(cx - BTN_R, cy - BTN_R, cx + BTN_R, cy + BTN_R,
                      fill="#26262b", outline=RED if muted else "#4a4a52", width=2, tags="mic")
        icon = "#9a9aa2" if muted else "#ff8c14"
        c.create_rectangle(cx - 4, cy - 10, cx + 4, cy + 2, fill=icon, outline=icon, tags="mic")
        c.create_oval(cx - 4, cy - 12, cx + 4, cy - 6, fill=icon, outline=icon, tags="mic")
        c.create_oval(cx - 4, cy - 2, cx + 4, cy + 4, fill=icon, outline=icon, tags="mic")
        c.create_arc(cx - 8, cy - 8, cx + 8, cy + 8, start=200, extent=140, style="arc",
                     outline=icon, width=2, tags="mic")
        c.create_line(cx, cy + 8, cx, cy + 12, fill=icon, width=2, tags="mic")
        c.create_line(cx - 4, cy + 12, cx + 4, cy + 12, fill=icon, width=2, tags="mic")
        if muted:
            c.create_line(cx - 11, cy - 11, cx + 11, cy + 11, fill=RED, width=3, tags="mic")

    def _draw_stop_button(self, c, active):
        cx, cy = CENTER + BTN_GAP, BTN_Y
        c.create_oval(cx - BTN_R, cy - BTN_R, cx + BTN_R, cy + BTN_R,
                      fill="#26262b", outline=RED if active else "#4a4a52", width=2, tags="stop")
        icon = RED if active else "#6a6a72"
        c.create_rectangle(cx - 6, cy - 6, cx + 6, cy + 6, fill=icon, outline=icon, tags="stop")

    def _draw(self):
        if self.stop.is_set():
            return
        t = time.time()
        muted = self.muted.is_set()
        # Volumen del micrófono en vivo: 0 en silencio, ~1 a volumen de voz normal.
        raw = audio_in.mic_level / max(audio_in.mic_threshold * 2.5, 1.0)
        listening = self.state == "listening" and not muted
        self.mic += ((min(raw, 1.0) if listening else 0.0) - self.mic) * 0.4
        now = time.time()
        if listening and audio_in.mic_level > audio_in.mic_threshold:
            self._voice_until = now + HEARING_HOLD  # el volumen baja entre sílabas: se mantiene en verde un rato
        self.hearing = listening and now < self._voice_until
        target = 0.0 if muted else TARGET.get(self.state, 0.0)
        if self.hearing:
            target = max(target, 0.35 + 0.5 * self.mic)  # el orbe brilla más cuando te oye
        self.level += (target - self.level) * 0.15  # suaviza encendido/apagado

        # Simula el ritmo de la voz: oscilaciones rápidas con azar mientras habla.
        if self.state == "speaking" and not muted:
            self.pulse += (random.random() - self.pulse) * 0.35
        else:
            self.pulse += (0.5 + 0.5 * math.sin(t * 2) - self.pulse) * 0.1

        color = GRAY if muted else ORANGE
        radius = BASE_RADIUS * (1 + 0.28 * self.level * self.pulse)
        c = self.canvas
        c.delete("all")

        # Halo: círculos concéntricos cada vez más tenues.
        # El halo máximo (~145 px) queda dentro de la ventana para que no se recorte.
        for i in range(14, 0, -1):
            r = radius + i * 6 * (0.35 + 0.65 * self.level)
            c.create_oval(
                CENTER - r, CENTER - r, CENTER + r, CENTER + r,
                fill=_blend(color, self.level * 0.55 * (1 - i / 15) ** 2),
                outline="",
            )
        # Anillo de escucha: crece con tu voz; verde cuando detecta que hablas.
        if listening:
            ring = GREEN if self.hearing else (190, 120, 40)
            rr = radius + 22 + self.mic * 40
            c.create_oval(CENTER - rr, CENTER - rr, CENTER + rr, CENTER + rr,
                          outline=_blend(ring, 0.45 + 0.55 * self.mic), width=2 + int(self.mic * 4))
        # Núcleo.
        core = _blend(color, 0.22 + 0.78 * self.level)
        c.create_oval(
            CENTER - radius, CENTER - radius, CENTER + radius, CENTER + radius,
            fill=core, outline=_blend(color, 0.35 + 0.65 * self.level), width=2,
        )
        # Brillo interior.
        h = radius * 0.45
        c.create_oval(
            CENTER - h, CENTER - h * 1.2, CENTER + h * 0.3, CENTER - h * 0.1,
            fill=_blend((255, 235, 190), 0.1 + 0.6 * self.level), outline="",
        )
        self._draw_status(c, muted)
        self._draw_mic_button(c, muted)
        self._draw_stop_button(c, self.state in ("thinking", "speaking"))

        if not self._worker.is_alive():  # Jarvis se apagó por voz
            self.close()
            return
        self.root.after(FPS_MS, self._draw)

    def _run_jarvis(self):
        try:
            main.run(on_state=self.set_state, stop=self.stop, muted=self.muted,
                     interrupt=self.interrupt)
        except Exception as e:
            import traceback
            main.log(f"[caída] Jarvis se detuvo por un error: {e}\n{traceback.format_exc()}")

    def start(self):
        self._worker = threading.Thread(target=self._run_jarvis, daemon=True)
        self._worker.start()
        self._draw()
        self.root.mainloop()


if __name__ == "__main__":
    JarvisOrb().start()
