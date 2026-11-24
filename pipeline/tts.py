"""Gemini TTS helper, shared by the voice audition and the narration stage."""
from __future__ import annotations

import base64
import time
import wave
from pathlib import Path

from pipeline.common import OUTPUTS, HttpError, http_json, log_call

GEMINI = "https://generativelanguage.googleapis.com/v1beta"
TTS_MODEL = "gemini-3.8-flash-tts"
SAMPLE_RATE = 24000  # Gemini TTS returns 24 kHz, 16-bit, mono PCM


def synthesize(key: str, text: str, out: Path, *, voice: str, style: str,
               stage: str, model: str = TTS_MODEL, **log_extra) -> float | None:
    """Speak `text` with a prebuilt voice, write a WAV, log the call. Returns audio seconds."""
    params = {"voice": voice, "style": style, "text": text}
    t0 = time.perf_counter()
    try:
        data, attempts = http_json(
            f"{GEMINI}/models/{model}:generateContent", method="POST",
            headers={"x-goog-api-key": key},
            body={
                "contents": [{"parts": [{"text": f"Say in a {style} voice: {text}"}]}],
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
                },
            })
        pcm = base64.b64decode(data["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
    except HttpError as e:
        log_call(stage=stage, provider="gemini", model=model, params=params,
                 latency_s=time.perf_counter() - t0, status="error",
                 attempts=getattr(e, "attempts", 1), error=str(e), **log_extra)
        print(f"  FAILED {voice}: {e}")
        return None

    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SAMPLE_RATE); w.writeframes(pcm)
    seconds = len(pcm) / (SAMPLE_RATE * 2)
    log_call(stage=stage, provider="gemini", model=model, params=params,
             latency_s=time.perf_counter() - t0, status="ok", attempts=attempts,
             output=out.relative_to(OUTPUTS.parent).as_posix(),
             audio_seconds=round(seconds, 2), words=len(text.split()), **log_extra)
    return seconds
