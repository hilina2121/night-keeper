"""Stage: narration. One Gemini TTS call per shot that has a narration line.

Caching: the output file name contains a hash of (model, voice, style, text).
If you change one line in storyboard.json, only that shot gets a new hash, so only
that shot calls the API again. Everything else is a cache hit.

Writes outputs/narration/shot_XX_<hash>.wav and outputs/narration/manifest.json
(the timing contract the assembly stages read).
"""
from __future__ import annotations

import base64
import json
import time
import wave
from pathlib import Path

from pipeline.common import (OUTPUTS, HttpError, http_json, is_daily_quota, load_env,
                             log_call, require)
from pipeline.storyboard import input_hash, load

GEMINI = "https://generativelanguage.googleapis.com/v1beta"
OUT_DIR = OUTPUTS / "narration"
MANIFEST = OUT_DIR / "manifest.json"
SAMPLE_RATE = 24000  # Gemini TTS returns 24 kHz, 16-bit, mono PCM
# Bump when the way we prompt the TTS changes, so every line is regenerated.
# v1: style inside the spoken text (read aloud). v2: systemInstruction (HTTP 400). v3: text only.
PROMPT_VERSION = "v3"


def wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def synthesize(key: str, cfg: dict, model: str, text: str, out: Path, shot_id: int) -> None:
    params = {"voice": cfg["voice"], "style": cfg["style"], "text": text}
    t0 = time.perf_counter()
    try:
        data, attempts = http_json(
            f"{GEMINI}/models/{model}:generateContent", method="POST",
            headers={"x-goog-api-key": key},
            body={
                # Only the line itself is sent. v1 put "Read this aloud in a ... voice:" in the
                # text and the model read it out (caught by Whisper QA); v2 tried a
                # systemInstruction, which TTS models reject with HTTP 400. See FAILURES.md F6.
                # Delivery is now controlled by the choice of voice.
                "contents": [{"parts": [{"text": text}]}],
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": cfg["voice"]}}},
                },
            })
    except HttpError as e:
        log_call(stage="narration", provider="gemini", model=model, params=params, shot=shot_id,
                 latency_s=time.perf_counter() - t0, status="error",
                 attempts=getattr(e, "attempts", 1), error=str(e))
        raise
    pcm = base64.b64decode(data["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SAMPLE_RATE); w.writeframes(pcm)
    secs = len(pcm) / (SAMPLE_RATE * 2)
    log_call(stage="narration", provider="gemini", model=model, params=params, shot=shot_id,
             latency_s=time.perf_counter() - t0, status="ok", attempts=attempts,
             output=out.relative_to(OUTPUTS.parent).as_posix(), audio_seconds=round(secs, 2),
             words=len(text.split()), cost_usd=0.0)


def run(only_shot: int | None = None) -> dict:
    load_env()
    sb = load()
    cfg = sb["narration"]
    key = None
    manifest: dict = {}
    new_calls = 0
    exhausted: set[str] = set()

    for shot in sb["shots"]:
        sid, text = shot["id"], shot["narration"].strip()
        if not text:
            manifest[str(sid)] = None
            print(f"  shot {sid:02d}: silent")
            continue
        models = [cfg["model"], *cfg.get("fallback_models", [])]
        # One candidate file per model; the hash covers everything that changes the audio.
        candidates = {m: OUT_DIR / f"shot_{sid:02d}_{input_hash(PROMPT_VERSION, m, cfg['voice'], cfg['style'], text)}.wav"
                      for m in models if m not in exhausted}
        out = next((p for p in candidates.values() if p.exists()), None)
        if out:
            print(f"  shot {sid:02d}: cached  ({out.name})")
        elif only_shot is not None and sid != only_shot:
            print(f"  shot {sid:02d}: changed but skipped (--shot {only_shot})")
            continue
        else:
            key = key or require("GEMINI_API_KEY")
            for i, (model, path) in enumerate(candidates.items()):
                print(f"  shot {sid:02d}: GENERATING with {model} -> {path.name}")
                try:
                    synthesize(key, cfg, model, text, path, sid)
                    out = path
                    new_calls += 1
                    break
                except HttpError as e:
                    if not is_daily_quota(e) or i == len(candidates) - 1:
                        raise
                    exhausted.add(model)  # don't spend a request on it again this run
                    print(f"    daily quota used up for {model}; falling back")
        h = out.stem.rsplit("_", 1)[-1]
        manifest[str(sid)] = {"file": out.relative_to(OUTPUTS.parent).as_posix(),
                              "hash": h, "seconds": round(wav_seconds(out), 3), "text": text}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    spoken = sum(m["seconds"] for m in manifest.values() if m)
    print(f"  narration: {new_calls} new TTS call(s), {spoken:.1f}s of speech total")
    return manifest
