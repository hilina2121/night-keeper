"""Shared helpers for every pipeline stage.

- load_env():   reads keys from .env (never committed)
- http_json():  HTTP call with retries + exponential backoff
- log_call():   appends one line per model call to runs.jsonl
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS_LOG = ROOT / "runs.jsonl"
OUTPUTS = ROOT / "outputs"

RETRYABLE = {429, 500, 502, 503, 504}


def load_env() -> None:
    """Load KEY=value lines from .env into os.environ (does not override real env vars)."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Missing {name}. Copy .env.example to .env and fill it in.")
    return value


class HttpError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:500]}")
        self.status = status
        self.body = body


def is_daily_quota(err: Exception) -> bool:
    return isinstance(err, HttpError) and err.status == 429 and "per day" in err.body.lower()


def retry_delay(err: Exception, attempt: int) -> float:
    """Seconds to wait before the next attempt.

    Gemini's 429 body says how long to wait ("retryDelay": "32s"); per-minute limits
    need ~60 s, which plain 2/4/8 s backoff never reaches (FAILURES.md F7).
    """
    if isinstance(err, HttpError):
        m = re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', err.body)
        if m:
            return min(float(m.group(1)) + 1, 90)
        if err.status == 429:
            return 20 * attempt
    return 2 ** attempt


def http_json(url: str, *, method: str = "GET", headers: dict | None = None,
              body: dict | None = None, retries: int = 3, timeout: int = 120):
    """Call a JSON API. Retries on 429/5xx and network errors with backoff (2s, 4s, 8s).

    Returns (parsed_json, attempts_used).
    """
    data = json.dumps(body).encode("utf-8") if body is not None else None
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    last_err: Exception | None = None
    for attempt in range(1, retries + 2):
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8")), attempt
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            last_err = HttpError(e.code, err_body)
            last_err.attempts = attempt  # type: ignore[attr-defined]
            # A *daily* quota will not come back in a few seconds; retrying only burns more
            # of tomorrow's requests (see FAILURES.md F5). Fail fast so the caller can fall back.
            if e.code not in RETRYABLE or is_daily_quota(last_err):
                raise last_err
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = e
            last_err.attempts = attempt  # type: ignore[attr-defined]
        if attempt <= retries:
            time.sleep(retry_delay(last_err, attempt))
    raise last_err  # type: ignore[misc]


def log_call(*, stage: str, provider: str, model: str, params: dict | None = None,
             seed: int | None = None, latency_s: float, status: str,
             cost_usd: float = 0.0, attempts: int = 1, output: str | None = None,
             error: str | None = None, **extra) -> dict:
    """Append one JSON line to runs.jsonl describing a single model call."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stage": stage,
        "provider": provider,
        "model": model,
        "params": params or {},
        "seed": seed,
        "latency_s": round(latency_s, 3),
        "attempts": attempts,
        "status": status,
        "cost_usd": cost_usd,
        "output": output,
        "error": error,
        **extra,
    }
    with RUNS_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record
