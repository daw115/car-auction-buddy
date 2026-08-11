"""Transkrypcja nagrań od klienta — lokalnie, bez wysyłania głosu na zewnątrz.

Nagranie rozmowy albo notatka głosowa to dane osobowe klienta, więc silnik stoi
na tej samej maszynie co reszta: faster-whisper na CPU, model pobierany raz
i trzymany w cache. Żaden dostawca zewnętrzny nie dostaje tego dźwięku.

Czego ten moduł NIE robi: nie podsłuchuje rozmów na żywo. Połączenia WhatsApp
są szyfrowane end-to-end i ich dźwięk nigdy nie trafia na serwer — transkrybować
da się wyłącznie plik, który ktoś tu położył (notatka głosowa, nagranie rozmowy
zrobione świadomie po stronie brokera).
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# "small" to kompromis zmierzony na polskim: "base" gubi końcówki i marki aut,
# "medium" potrafi być 3× wolniejszy przy niewielkim zysku. Zmiana: WHISPER_MODEL.
DEFAULT_MODEL = os.getenv("WHISPER_MODEL", "small")
DEFAULT_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "pl")
MAX_AUDIO_MB = int(os.getenv("WHISPER_MAX_AUDIO_MB", "80"))

_model_lock = threading.Lock()
_model = None
_model_name: Optional[str] = None


@dataclass
class Transcript:
    text: str
    language: str
    duration_s: float
    model: str
    segments: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "text": self.text,
            "language": self.language,
            "durationSeconds": round(self.duration_s, 1),
            "model": self.model,
            "segments": self.segments,
        }


def is_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except Exception:
        return False
    return True


def _load_model(name: str):
    """Model trzymany między wywołaniami — wczytanie kosztuje kilkanaście sekund."""
    global _model, _model_name
    with _model_lock:
        if _model is not None and _model_name == name:
            return _model

        from faster_whisper import WhisperModel

        # int8 na CPU: kilkukrotnie szybciej niż float32, a na mowie telefonicznej
        # różnicy w treści nie widać.
        compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
        threads = int(os.getenv("WHISPER_THREADS", "0")) or None
        logger.info("[transcribe] wczytuję model %s (%s)", name, compute_type)
        _model = WhisperModel(
            name,
            device="cpu",
            compute_type=compute_type,
            cpu_threads=threads or 0,
            download_root=os.getenv("WHISPER_CACHE_DIR") or None,
        )
        _model_name = name
        return _model


def transcribe(
    audio_path: str | Path,
    *,
    language: Optional[str] = None,
    model_name: Optional[str] = None,
) -> Transcript:
    """Zamienia nagranie na tekst. Rzuca wyjątkiem, gdy pliku nie da się przeczytać."""
    path = Path(audio_path)
    if not path.is_file():
        raise FileNotFoundError(f"Nie ma pliku: {path}")

    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > MAX_AUDIO_MB:
        raise ValueError(
            f"Nagranie ma {size_mb:.0f} MB, limit to {MAX_AUDIO_MB} MB — podziel je na części"
        )

    name = model_name or DEFAULT_MODEL
    model = _load_model(name)

    segments, info = model.transcribe(
        str(path),
        language=language or DEFAULT_LANGUAGE,
        # Cisza między zdaniami w rozmowie telefonicznej potrafi wygenerować
        # halucynacje ("Napisy stworzone przez..."), stąd filtr ciszy.
        vad_filter=True,
        beam_size=int(os.getenv("WHISPER_BEAM_SIZE", "5")),
    )

    collected: list[dict] = []
    parts: list[str] = []
    for segment in segments:
        text = (segment.text or "").strip()
        if not text:
            continue
        parts.append(text)
        collected.append(
            {"start": round(segment.start, 1), "end": round(segment.end, 1), "text": text}
        )

    transcript = Transcript(
        text=" ".join(parts).strip(),
        language=getattr(info, "language", language or DEFAULT_LANGUAGE),
        duration_s=float(getattr(info, "duration", 0.0) or 0.0),
        model=name,
        segments=collected,
    )
    logger.info(
        "[transcribe] %s: %.0fs nagrania, %d znaków, model %s",
        path.name, transcript.duration_s, len(transcript.text), name,
    )
    return transcript
