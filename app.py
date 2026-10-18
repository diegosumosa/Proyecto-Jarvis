"""Jarvis con interfaz: un orbe tipo reactor con anillos giratorios, partículas y una corona de barras.

La corona baila al ritmo de lo que suena en el PC (Spotify, la voz de Jarvis), se pone verde cuando
te oye hablar y "escanea" mientras piensa. El audio del sistema se analiza en audio_viz.py.

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
import audio_viz
import main

SIZE = 360
CENTER = SIZE // 2
BASE_RADIUS = 36
N_BARS = 48  # barras de la corona (simétricas: 24 bandas distintas)
BAR_R0 = 96  # radio donde nacen las barras
BAR_MAX = 48  # largo máximo de una barra
RIPPLE_LIFE = 1.2  # segundos que dura una onda expansiva
HOT = (255, 214, 120)  # tono "al rojo vivo" para los puntos más intensos
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

# Intensidad base del brillo según el estado (0 = apagado, 1 = máximo). En reposo sigue visible.
BASE_LEVEL = {"idle": 0.2, "listening": 0.3, "thinking": 0.6, "speaking": 1.0}
# Velocidad de giro de los anillos según el estado (pensando, giran rápido como escaneando).
SPIN = {"idle": 0.5, "listening": 0.8, "thinking": 3.2, "speaking": 1.5}

# Partículas que orbitan: (fase, velocidad angular en rad/s, radio, tamaño). Fijas para que no cambien.
_rng = random.Random(7)
PARTICLES = [
    (_rng.uniform(0, math.tau), _rng.choice((-1, 1)) * _rng.uniform(0.3, 1.1), _rng.uniform(54, 92), _rng.uniform(1.3, 2.8))
    for _ in range(18)
]


def _mix(a, b, f):
    """Mezcla dos colores RGB: f=0 -> a, f=1 -> b."""
    return tuple(a[i] + (b[i] - a[i]) * f for i in range(3))


def _blend(color, amount):
    """Mezcla un color con el fondo transparente; amount=0 -> invisible, 1 -> color pleno."""
    # Se mezcla hacia el color transparente: con amount=0 el píxel desaparece del todo.
    amount = max(0.0, min(1.0, amount))
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
        self.energy = 0.0  # energía del audio que suena en el PC (suavizada, 0-1)
        self.beat = 0.0  # golpe de ritmo actual (1 al sonar un golpe, decae rápido)
        self.bars = [0.0] * N_BARS  # alturas actuales de las barras (suavizadas)
        self.spin = 0.5  # velocidad de giro actual (suavizada)
        self.rot = 0.0  # ángulo acumulado de los anillos, en grados
        self.ripples = []  # instantes en que nació cada onda expansiva
        self._last_ripple = 0.0
        self._draw_error_logged = False
        self._last_frame = time.time()
        audio_viz.start()  # empieza a analizar el audio del sistema (música, voz de Jarvis)
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

    def _bar_target(self, i, idx, t, bands, muted):
        """Altura objetivo (0-1) de la barra i según lo que esté pasando."""
        if muted:
            return 0.04
        if self.energy > 0.04:  # suena algo: sigue el espectro (barras simétricas, graves arriba)
            j = min(idx * 2, len(bands) - 2)
            return (bands[j] + bands[j + 1]) / 2
        if self.hearing:  # te oye hablar: las barras bailan con tu voz
            return self.mic * (0.35 + 0.65 * abs(math.sin(t * 6 + idx * 0.9)))
        if self.state == "thinking":  # escaneo: una ola brillante recorre la corona
            ang = math.radians(i * 360 / N_BARS - 90) - math.radians(self.rot * 3)
            return 0.12 + 0.7 * max(0.0, math.cos(ang)) ** 6
        return 0.06 + 0.04 * math.sin(t * 1.5 + idx * 0.5)  # reposo: latido suave

    def _draw_scene(self, c, t, muted, listening, bands):
        lv = self.level
        color = GRAY if muted else ORANGE
        hot = (175, 175, 180) if muted else HOT
        radius = BASE_RADIUS * (1 + 0.2 * lv * self.pulse + 0.22 * self.beat)
        cx = cy = CENTER
        amt = 0.3 + 0.7 * lv
        c.delete("all")

        # Halo: círculos concéntricos cada vez más tenues.
        # Las capas casi invisibles se omiten: pintadas serían un disco oscuro duro sobre el escritorio.
        for i in range(10, 0, -1):
            glow = lv * 0.5 * (1 - i / 11) ** 2
            if glow < 0.07:
                continue
            r = radius + i * 5 * (0.4 + 0.6 * lv)
            c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=_blend(color, glow), outline="")

        # Ondas expansivas: nacen con los golpes de ritmo (o con la voz al hablar) y se desvanecen.
        spawn = self.beat > 0.9 or (self.state == "speaking" and self.pulse > 0.8)
        if spawn and not muted and t - self._last_ripple > 0.35:
            self.ripples.append(t)
            self._last_ripple = t
        self.ripples = [b for b in self.ripples if t - b < RIPPLE_LIFE]
        for born in self.ripples:
            age = (t - born) / RIPPLE_LIFE
            r = radius + 12 + age * 95
            c.create_oval(cx - r, cy - r, cx + r, cy + r,
                          outline=_blend(hot, 0.6 * (1 - age) ** 1.5 * (0.4 + 0.6 * lv)), width=2)

        # Corona de barras: espectro de la música, tu voz o un escaneo, según el momento.
        base = GREEN if self.hearing else color
        for i in range(N_BARS):
            idx = i if i < N_BARS // 2 else N_BARS - 1 - i
            tv = self._bar_target(i, idx, t, bands, muted)
            self.bars[i] += (tv - self.bars[i]) * (0.65 if tv > self.bars[i] else 0.2)
            v = self.bars[i]
            ang = math.radians(i * 360 / N_BARS - 90)
            r1, r2 = BAR_R0, BAR_R0 + 3 + v * BAR_MAX
            col = _mix(base, hot if not self.hearing else (200, 255, 225), min(1.0, v * 0.8))
            c.create_line(cx + r1 * math.cos(ang), cy + r1 * math.sin(ang),
                          cx + r2 * math.cos(ang), cy + r2 * math.sin(ang),
                          fill=_blend(col, min(1.0, 0.5 + 0.5 * max(v, lv * 0.5))), width=4 if v > 0.55 else 3)

        # Marcas de escala que giran despacio, como un dial.
        ticks_r = BAR_R0 - 10
        for k in range(60):
            a = math.radians(k * 6 - self.rot * 0.2)
            ln = 6 if k % 5 == 0 else 3
            c.create_line(cx + ticks_r * math.cos(a), cy + ticks_r * math.sin(a),
                          cx + (ticks_r - ln) * math.cos(a), cy + (ticks_r - ln) * math.sin(a),
                          fill=_blend(color, 0.12 + 0.28 * lv), width=1)

        # Anillo de escucha: se ensancha con tu voz; verde cuando detecta que hablas.
        if listening:
            ring = GREEN if self.hearing else (190, 120, 40)
            rr = BAR_R0 - 18
            c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr,
                          outline=_blend(ring, 0.45 + 0.55 * self.mic), width=2 + int(self.mic * 4))

        # Anillos del reactor: arcos que giran en sentidos opuestos.
        ra, rb, rc = radius + 11, radius + 23, radius + 31
        c.create_oval(cx - rc, cy - rc, cx + rc, cy + rc, outline=_blend(color, 0.12 + 0.2 * lv), width=1)
        for k in range(3):
            c.create_arc(cx - ra, cy - ra, cx + ra, cy + ra, start=self.rot + k * 120, extent=72,
                         style="arc", outline=_blend(color, amt * 0.95), width=4)
        for k in range(6):
            c.create_arc(cx - rb, cy - rb, cx + rb, cy + rb, start=-self.rot * 1.5 + k * 60, extent=26,
                         style="arc", outline=_blend(color, amt * 0.75), width=2)
        if self.state == "thinking" and not muted:  # arco brillante que "escanea"
            c.create_arc(cx - rb, cy - rb, cx + rb, cy + rb, start=self.rot * 3, extent=55,
                         style="arc", outline=_blend(hot, 0.95), width=4)

        # Núcleo con degradado: del borde ámbar al centro casi blanco, y un destello.
        core_amt = 0.35 + 0.65 * lv
        for i in range(8):
            f = i / 7
            r = radius * (1 - 0.88 * f)
            col = _mix(color, (255, 240, 200) if not muted else (200, 200, 205), f ** 1.4)
            c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=_blend(col, core_amt * (0.55 + 0.45 * f)),
                          outline=_blend(color, 0.4 + 0.6 * lv) if i == 0 else "", width=2)
        h = radius * 0.3
        c.create_oval(cx - radius * 0.45, cy - radius * 0.55, cx - radius * 0.45 + h, cy - radius * 0.55 + h * 0.7,
                      fill=_blend((255, 250, 235), 0.15 + 0.5 * lv), outline="")

        # Partículas que orbitan; se agrandan con cada golpe de ritmo.
        for phase, speed, pr, size in PARTICLES:
            a = phase + t * speed * (0.5 + 0.5 * self.spin)
            rr = pr + 5 * math.sin(t * 1.3 + phase * 3) + 8 * self.energy
            flick = 0.5 + 0.5 * math.sin(t * 3 + phase * 5)
            s = size * (1 + 0.8 * self.beat)
            x, y = cx + rr * math.cos(a), cy + rr * math.sin(a)
            c.create_oval(x - s, y - s, x + s, y + s, fill=_blend(hot, amt * (0.35 + 0.65 * flick)), outline="")

    def _draw(self):
        if self.stop.is_set():
            return
        t = time.time()
        muted = self.muted.is_set()
        # Volumen del micrófono en vivo: 0 en silencio, ~1 a volumen de voz normal.
        raw = audio_in.mic_level / max(audio_in.mic_threshold * 2.5, 1.0)
        listening = self.state == "listening" and not muted
        self.mic += ((min(raw, 1.0) if listening else 0.0) - self.mic) * 0.4
        if listening and audio_in.mic_level > audio_in.mic_threshold:
            self._voice_until = t + HEARING_HOLD  # el volumen baja entre sílabas: se mantiene en verde un rato
        self.hearing = listening and t < self._voice_until

        # Audio que suena en el PC (música o la propia voz de Jarvis): espectro, energía y golpes de ritmo.
        bands, energy, beat = audio_viz.get()
        if muted:
            energy, beat = 0.0, 0.0
        self.energy += (energy - self.energy) * 0.3
        self.beat = max(beat, self.beat * 0.85)

        # Brillo objetivo: según el estado y, si suena algo, según su energía.
        target = 0.0 if muted else BASE_LEVEL.get(self.state, 0.2)
        if not muted:
            target = max(target, 0.25 + 0.75 * self.energy)
            if self.hearing:
                target = max(target, 0.35 + 0.5 * self.mic)  # el orbe brilla más cuando te oye
        self.level += (target - self.level) * 0.15  # suaviza encendido/apagado

        # Pulso del núcleo: sigue el audio real (música o voz de Jarvis); sin captura, se simula.
        if self.state == "speaking" and not muted and not audio_viz.available():
            self.pulse += (random.random() - self.pulse) * 0.35
        elif self.energy > 0.05:
            self.pulse += (self.energy - self.pulse) * 0.4
        else:
            self.pulse += (0.5 + 0.5 * math.sin(t * 2) - self.pulse) * 0.1

        # Giro de los anillos: más rápido al pensar y con la música.
        dt = min(t - self._last_frame, 0.1)
        self._last_frame = t
        self.spin += (SPIN.get(self.state, 0.6) + 1.2 * self.energy - self.spin) * 0.08
        self.rot += self.spin * dt * 40.0

        c = self.canvas
        try:
            self._draw_scene(c, t, muted, listening, bands)
        except Exception as e:  # un cuadro mal dibujado no debe congelar el orbe
            if not self._draw_error_logged:
                main.log(f"[orbe] error al dibujar: {e!r}")
                self._draw_error_logged = True
        self._draw_status(c, muted)
        self._draw_mic_button(c, muted)
        self._draw_stop_button(c, self.state in ("thinking", "speaking"))

        if not self._worker.is_alive():  # Jarvis se apagó por voz
            self.close()
            return
        # En reposo y sin música no hace falta animar a toda velocidad: se gasta la mitad de procesador.
        busy = self.state != "idle" or self.energy > 0.03 or self.ripples
        self.root.after(FPS_MS if busy else FPS_MS * 2, self._draw)

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
