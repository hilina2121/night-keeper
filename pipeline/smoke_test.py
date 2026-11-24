"""Smoke test: call each provider once, log latency to runs.jsonl.

Model names change often, so this script first ASKS each provider which
models exist, prints them, then calls one. Run:

    python -m pipeline.smoke_test
"""
from __future__ import annotations

import base64
import re
import time
import wave

from pipeline.common import (OUTPUTS, HttpError, http_json, load_env, log_call,
                             require)

GEMINI = "https://generativelanguage.googleapis.com/v1beta"


def pick(names: list[str], must: list[str], avoid: list[str]) -> str | None:
    """Pick the newest-looking model whose name contains all `must` and none of `avoid`."""
    hits = [n for n in names if all(m in n for m in must) and not any(a in n for a in avoid)]
    return sorted(hits)[-1] if hits else None


def gemini_models(key: str) -> list[str]:
    t0 = time.perf_counter()
    data, attempts = http_json(f"{GEMINI}/models?pageSize=200", headers={"x-goog-api-key": key})
    names = [m["name"].removeprefix("models/") for m in data.get("models", [])]
    log_call(stage="smoke", provider="gemini", model="list-models", latency_s=time.perf_counter() - t0,
             status="ok", attempts=attempts, n_models=len(names))
    return names


def gemini_text(key: str, model: str) -> None:
    prompt = "In one short sentence, describe a night watchman's coat."
    t0 = time.perf_counter()
    try:
        data, attempts = http_json(
            f"{GEMINI}/models/{model}:generateContent", method="POST",
            headers={"x-goog-api-key": key},
            body={"contents": [{"parts": [{"text": prompt}]}]})
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        usage = data.get("usageMetadata", {})
        log_call(stage="smoke", provider="gemini", model=model, params={"prompt": prompt},
                 latency_s=time.perf_counter() - t0, status="ok", attempts=attempts, usage=usage)
        print(f"  text OK  -> {text}")
    except HttpError as e:
        log_call(stage="smoke", provider="gemini", model=model, params={"prompt": prompt},
                 latency_s=time.perf_counter() - t0, status="error", attempts=getattr(e, "attempts", 1), error=str(e))
        print(f"  text FAILED -> {e}")


def gemini_tts(key: str, model: str) -> None:
    line = "Every night, while the city slept, my father kept watch over a mall that was not his."
    params = {"voice": "Charon", "style": "calm, warm, unhurried"}
    t0 = time.perf_counter()
    try:
        data, attempts = http_json(
            f"{GEMINI}/models/{model}:generateContent", method="POST",
            headers={"x-goog-api-key": key},
            body={
                "contents": [{"parts": [{"text": f"Say in a {params['style']} voice: {line}"}]}],
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": params["voice"]}}},
                },
            })
        pcm = base64.b64decode(data["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
        out = OUTPUTS / "smoke" / "tts_test.wav"
        out.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out), "wb") as w:  # Gemini TTS returns 24 kHz 16-bit mono PCM
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(pcm)
        seconds = len(pcm) / (24000 * 2)
        log_call(stage="smoke", provider="gemini", model=model, params={**params, "text": line},
                 latency_s=time.perf_counter() - t0, status="ok", attempts=attempts,
                 output=str(out.relative_to(OUTPUTS.parent)), audio_seconds=round(seconds, 2),
                 words=len(line.split()))
        print(f"  TTS OK   -> {out.name}, {seconds:.1f}s of audio, {len(line.split()) / seconds:.2f} words/s")
    except HttpError as e:
        log_call(stage="smoke", provider="gemini", model=model, params=params,
                 latency_s=time.perf_counter() - t0, status="error", attempts=getattr(e, "attempts", 1), error=str(e))
        print(f"  TTS FAILED -> {e}")


def cloudflare(account: str, token: str) -> None:
    base = f"https://api.cloudflare.com/client/v4/accounts/{account}/ai"
    auth = {"Authorization": f"Bearer {token}"}

    t0 = time.perf_counter()
    data, attempts = http_json(f"{base}/models/search?search=flux&per_page=50", headers=auth)
    names = sorted(m["name"] for m in data.get("result", []))
    log_call(stage="smoke", provider="cloudflare", model="list-models", latency_s=time.perf_counter() - t0,
             status="ok", attempts=attempts, models=names)
    print("  FLUX models available:", ", ".join(names) or "(none found)")

    model = "@cf/black-forest-labs/flux-1-schnell"
    prompt = ("An old dark wool coat hanging on a nail on a mud wall, warm amber lamp light, "
              "warm hand-painted illustration, soft grain, muted earth tones, no text")
    # flux-1-schnell on Workers AI rejects a "seed" field (HTTP 400 on first run), so no seed here.
    params = {"prompt": prompt, "steps": 4}
    t0 = time.perf_counter()
    try:
        data, attempts = http_json(f"{base}/run/{model}", method="POST", headers=auth, body=params)
        img = base64.b64decode(data["result"]["image"])
        out = OUTPUTS / "smoke" / "flux_test.jpg"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(img)
        log_call(stage="smoke", provider="cloudflare", model=model, params=params,
                 latency_s=time.perf_counter() - t0, status="ok", attempts=attempts,
                 output=str(out.relative_to(OUTPUTS.parent)))
        print(f"  image OK -> {out.name} ({len(img) // 1024} KB)")
    except HttpError as e:
        log_call(stage="smoke", provider="cloudflare", model=model, params=params,
                 latency_s=time.perf_counter() - t0, status="error", attempts=getattr(e, "attempts", 1), error=str(e))
        print(f"  image FAILED -> {e}")


def main() -> None:
    load_env()
    gkey = require("GEMINI_API_KEY")

    print("[Gemini] listing models...")
    names = gemini_models(gkey)
    # Plain text models only, e.g. "gemini-3.8-flash". A loose "flash" match picked
    # gemini-omni-1.2-flash (video, free quota = 0) on the first run, see FAILURES.md.
    plain = [n for n in names if re.fullmatch(r"gemini-\d+(\.\d+)?-flash", n)]
    text_model = sorted(plain, key=lambda n: [int(x) for x in re.findall(r"\d+", n)])[-1] if plain else None
    tts_model = pick(names, ["flash", "tts"], [])
    print(f"  {len(names)} models. Text: {text_model} | TTS: {tts_model}")
    print("  all TTS models:", [n for n in names if "tts" in n])
    if text_model:
        gemini_text(gkey, text_model)
    if tts_model:
        gemini_tts(gkey, tts_model)

    print("[Cloudflare] ...")
    cloudflare(require("CLOUDFLARE_ACCOUNT_ID"), require("CLOUDFLARE_API_TOKEN"))

    print("\nDone. Every call above is one line in runs.jsonl.")


if __name__ == "__main__":
    main()
