"""QA check: transcribe narration files with Whisper (Cloudflare Workers AI) to verify
the TTS said exactly the line, and nothing else (e.g. the style instruction).

    python -m pipeline.transcribe outputs/narration/shot_05_xxx.wav [more.wav ...]
"""
from __future__ import annotations

import base64
import sys
import time
from pathlib import Path

from pipeline.common import http_json, load_env, log_call, require

MODEL = "@cf/openai/whisper-large-v3-turbo"


def transcribe(path: Path) -> str:
    account, token = require("CLOUDFLARE_ACCOUNT_ID"), require("CLOUDFLARE_API_TOKEN")
    t0 = time.perf_counter()
    data, attempts = http_json(
        f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{MODEL}",
        method="POST", headers={"Authorization": f"Bearer {token}"},
        body={"audio": base64.b64encode(path.read_bytes()).decode("ascii"), "language": "en"})
    text = data["result"]["text"].strip()
    log_call(stage="qa_transcribe", provider="cloudflare", model=MODEL, params={"file": path.as_posix()},
             latency_s=time.perf_counter() - t0, status="ok", attempts=attempts, transcript=text)
    return text


def words(path: Path) -> list[dict]:
    """Word-level timestamps [{'word', 'start', 'end'}] for a WAV, used to cut a one-take narration."""
    account, token = require("CLOUDFLARE_ACCOUNT_ID"), require("CLOUDFLARE_API_TOKEN")
    t0 = time.perf_counter()
    data, attempts = http_json(
        f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{MODEL}",
        method="POST", headers={"Authorization": f"Bearer {token}"},
        body={"audio": base64.b64encode(path.read_bytes()).decode("ascii"), "language": "en"})
    res = data["result"]
    ws = [w for seg in res.get("segments", []) for w in seg.get("words", [])]
    log_call(stage="qa_align", provider="cloudflare", model=MODEL, params={"file": path.as_posix()},
             latency_s=time.perf_counter() - t0, status="ok", attempts=attempts,
             transcript=res.get("text", "").strip(), n_words=len(ws))
    return ws


if __name__ == "__main__":
    load_env()
    for arg in sys.argv[1:]:
        print(f"{Path(arg).name}: {transcribe(Path(arg))}")
