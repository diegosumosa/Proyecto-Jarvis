"""Analiza el audio que suena en el PC (loopback de WASAPI) para animar el orbe al ritmo.

Lee lo que Windows envía a tus altavoces o audífonos (Spotify, Jarvis hablando, etc.), así que funciona
aunque uses audífonos. Solo se miden las frecuencias para dibujar; el audio no se guarda ni se envía.
Si algo falla (sin numpy, sin dispositivo), el orbe simplemente no reacciona a la música.
"""
import threading
import time

try:
    import numpy as np
    import pyaudiowpatch as pa
except ImportError:  # sin las librerías: el orbe sigue funcionando, sin reaccionar al audio
    np = pa = None

N_BANDS = 48  # barras del espectro (graves a agudos)
_FMIN, _FMAX = 45.0, 14000.0
_FFT = 2048  # muestras por análisis (más resolución en los graves)
_FADE = 0.3  # segundos sin audio nuevo hasta apagar las barras (el loopback no envía nada en silencio)

_state = {"bands": [0.0] * N_BANDS, "energy": 0.0, "beat": 0.0, "t": 0.0, "ok": False}
_started = False
_stop = threading.Event()


def get():
    """(bandas 0-1, energía 0-1, golpe 0-1), ya atenuados si no llega audio nuevo."""
    age = time.time() - _state["t"]
    fade = max(0.0, 1.0 - age / _FADE)
    beat = _state["beat"] * max(0.0, 1.0 - age / 0.15)
    return [b * fade for b in _state["bands"]], _state["energy"] * fade, beat


def available() -> bool:
    """True si se está capturando el audio del sistema."""
    return bool(_state["ok"])


class _Analyzer:
    def __init__(self, rate: int, channels: int):
        self.channels = channels
        self.buf = np.zeros(_FFT, dtype=np.float32)
        self.window = np.hanning(_FFT).astype(np.float32)
        freqs = np.fft.rfftfreq(_FFT, 1.0 / rate)
        edges = np.geomspace(_FMIN, min(_FMAX, rate / 2 - 1), N_BANDS + 1)
        self.idx = np.searchsorted(freqs, edges)
        centers = np.sqrt(edges[:-1] * edges[1:])
        self.tilt = (2.5 * np.log2(centers / 100.0)).astype(np.float32)  # los agudos suenan más bajos: se realzan
        self.bands = np.zeros(N_BANDS, dtype=np.float32)
        self.ref = -60.0  # nivel de referencia (dB) que se adapta al volumen de lo que suena
        self.prev_bass = 0.0
        self.flux_avg = 0.0
        self.last_beat = 0.0

    def process(self, data: bytes) -> None:
        x = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        if self.channels > 1:
            x = x[: len(x) // self.channels * self.channels].reshape(-1, self.channels).mean(axis=1)
        self.buf = np.concatenate([self.buf, x])[-_FFT:]
        if float(np.abs(x).max(initial=0.0)) < 1e-4:  # silencio digital
            target = np.zeros(N_BANDS, dtype=np.float32)
        else:
            spec = np.abs(np.fft.rfft(self.buf * self.window)) / (_FFT / 4)
            mags = np.array([spec[a:max(b, a + 1)].mean() for a, b in zip(self.idx[:-1], self.idx[1:])])
            db = 20 * np.log10(mags + 1e-7) + self.tilt
            peak = float(db.max())
            # La referencia sube al instante con un golpe fuerte y baja despacio: así las barras se ven
            # igual de grandes con el volumen del sistema alto o bajo.
            self.ref = peak if peak > self.ref else max(self.ref - 0.02, -60.0)
            target = np.clip((db - (self.ref - 40.0)) / 40.0, 0.0, 1.0).astype(np.float32)
        rising = target > self.bands
        self.bands = np.where(rising, self.bands + 0.7 * (target - self.bands), self.bands + 0.2 * (target - self.bands))

        # Golpe = subida brusca del bajo (no su nivel, que en música fuerte ya está casi al máximo).
        bass = float(target[:6].mean())
        flux = bass - self.prev_bass
        self.prev_bass = bass
        now = time.time()
        beat = _state["beat"] * 0.85  # el golpe se apaga en unas décimas de segundo
        if flux > max(0.08, 2.6 * self.flux_avg) and bass > 0.35 and now - self.last_beat > 0.3:
            beat, self.last_beat = 1.0, now
        self.flux_avg = self.flux_avg * 0.9 + max(flux, 0.0) * 0.1
        _state.update(bands=self.bands.tolist(), energy=min(1.0, float(self.bands.mean()) * 1.7),
                      beat=beat, t=now)


def _run() -> None:
    while not _stop.is_set():
        p = stream = None
        try:
            p = pa.PyAudio()
            device = p.get_default_wasapi_loopback()
            analyzer = _Analyzer(int(device["defaultSampleRate"]), int(device["maxInputChannels"]))

            def callback(in_data, frame_count, time_info, status):
                try:
                    analyzer.process(in_data)
                except Exception:
                    pass
                return (None, pa.paContinue)

            stream = p.open(
                format=pa.paInt16, channels=analyzer.channels, rate=int(device["defaultSampleRate"]),
                frames_per_buffer=1024, input=True, input_device_index=device["index"],
                stream_callback=callback,
            )
            _state["ok"] = True
            while not _stop.is_set() and stream.is_active():
                time.sleep(2)
                if _default_name() != device["name"]:  # cambiaste de audífonos/altavoces: reabrir
                    break
        except Exception:
            pass
        finally:
            _state["ok"] = False
            try:
                if stream is not None:
                    stream.close()
                if p is not None:
                    p.terminate()
            except Exception:
                pass
        _stop.wait(3)


def _default_name():
    try:
        p = pa.PyAudio()
        try:
            return p.get_default_wasapi_loopback()["name"]
        finally:
            p.terminate()
    except Exception:
        return None


def start() -> None:
    """Empieza a analizar el audio del sistema en segundo plano (no hace nada si ya empezó o falta algo)."""
    global _started
    if _started or np is None:
        return
    _started = True
    threading.Thread(target=_run, daemon=True).start()
