"""Stage: narration. One Gemini TTS call per shot that has a narration line.

Caching: the output file name contains a hash of (model, voice, style, text).
If you change one line in storyboard.json, only that shot gets a new hash, so only
that shot calls the API again. Everything else is a cache hit.

Writes outputs/narration/shot_XX_<hash>.wav and outputs/narration/manifest.json
(the timing contract the assembly stages read).
"""
from __future__ import annotations

import base64
import difflib
import json
import re
import subprocess
import time
import wave
from pathlib import Path

from pipeline.common import (OUTPUTS, HttpError, http_json, is_daily_quota, load_env,
                             log_call, require)
from pipeline.storyboard import input_hash, load
from pipeline.transcribe import words

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


def spoken(shot: dict) -> str:
    """What the TTS is given: `tts_text` (e.g. a phonetic spelling) if set, else the subtitle line."""
    return (shot.get("tts_text") or shot["narration"]).strip()


def generate_with_fallback(key: str, cfg: dict, candidates: dict[str, Path], text: str,
                           shot_id) -> Path:
    """Try each model in order; on a *daily* quota error move to the next model."""
    for i, (model, path) in enumerate(candidates.items()):
        print(f"    GENERATING with {model} -> {path.name}")
        try:
            synthesize(key, cfg, model, text, path, shot_id)
            return path
        except HttpError as e:
            if not is_daily_quota(e) or i == len(candidates) - 1:
                raise
            print(f"    daily quota used up for {model}; falling back")
    raise RuntimeError("no TTS model available")


# ---------------------------------------------------------------- one take (E5)

def detect_silences(path: Path, min_silence_s: float, noise_db: int = -35) -> list[tuple[float, float]]:
    """Return (start, end) of every silence FFmpeg finds in the file."""
    res = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
         "-af", f"silencedetect=noise={noise_db}dB:d={min_silence_s}", "-f", "null", "-"],
        capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", res.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", res.stderr)]
    return list(zip(starts, ends))


def split_take(take: Path, n_lines: int) -> list[tuple[float, float]]:
    """Cut a one-take narration into `n_lines` (start, end) spans at the n-1 LONGEST interior pauses.

    Pauses between lines (paragraph breaks) are longer than pauses between sentences inside
    a line, so the longest n-1 pauses are the line boundaries. Checked afterwards by Whisper.
    """
    total = wav_seconds(take)
    for min_sil in (0.35, 0.25, 0.18):
        sil = detect_silences(take, min_sil)
        lead = next((e for s, e in sil if s < 0.05), 0.0)
        tail = next((s for s, e in sil if e > total - 0.05), total)
        interior = [(s, e) for s, e in sil if s >= 0.05 and e <= total - 0.05]
        if len(interior) >= n_lines - 1:
            cuts = sorted(sorted(interior, key=lambda se: se[1] - se[0], reverse=True)[:n_lines - 1])
            break
    else:
        raise RuntimeError(f"one-take split: found only {len(interior)} pauses for {n_lines} lines; "
                           "use mode per_line or regenerate the take")
    spans, start = [], max(0.0, lead - 0.05)
    for s, e in cuts:
        spans.append((start, min(s + 0.25, e)))  # keep the soft end of the last word
        start = max(s, e - 0.05)
    spans.append((start, min(total, tail + 0.15)))
    return spans


def _norm(w: str) -> str:
    return re.sub(r"[^a-z0-9]", "", w.lower())


def align_take(take: Path, spoken_lines: list[str]) -> list[tuple[float, float]] | None:
    """Cut points from Whisper word timestamps (first try; pauses alone mis-split, see E5).

    Script words are matched to heard words with difflib, so one misheard word does not
    shift everything. Each line runs from just before its first word to just after its last,
    and never past the midpoint of the gap to the next line.
    """
    heard = words(take)
    if not heard:
        return None
    script = [(i, _norm(w)) for i, line in enumerate(spoken_lines) for w in line.split()]
    sm = difflib.SequenceMatcher(a=[w for _, w in script], b=[_norm(h["word"]) for h in heard], autojunk=False)
    times: dict[int, list[tuple[float, float]]] = {}
    for a, b, n in sm.get_matching_blocks():
        for k in range(n):
            line_idx = script[a + k][0]
            h = heard[b + k]
            times.setdefault(line_idx, []).append((float(h["start"]), float(h["end"])))
    if len(times) != len(spoken_lines) or sm.ratio() < 0.8:
        print(f"  align: only matched {len(times)}/{len(spoken_lines)} lines (ratio {sm.ratio():.2f})")
        return None
    first = [min(s for s, _ in times[i]) for i in range(len(spoken_lines))]
    last = [max(e for _, e in times[i]) for i in range(len(spoken_lines))]
    total = wav_seconds(take)
    spans = []
    for i in range(len(spoken_lines)):
        lo = 0.0 if i == 0 else (last[i - 1] + first[i]) / 2
        hi = total if i == len(spoken_lines) - 1 else (last[i] + first[i + 1]) / 2
        spans.append((max(lo, first[i] - 0.1), min(hi, last[i] + 0.3)))
    print(f"  align: Whisper matched {sm.ratio():.0%} of words")
    return spans


def cut_wav(src: Path, dst: Path, start: float, end: float) -> float:
    with wave.open(str(src), "rb") as r:
        rate = r.getframerate()
        r.setpos(int(start * rate))
        frames = r.readframes(int((end - start) * rate))
        params = r.getparams()
    with wave.open(str(dst), "wb") as w:
        w.setparams(params)
        w.writeframes(frames)
    return len(frames) / (params.sampwidth * params.nchannels) / rate


def run_one_take(sb: dict, cfg: dict) -> dict:
    lines = [(s["id"], spoken(s), s["narration"].strip()) for s in sb["shots"] if s["narration"].strip()]
    spoken_lines = [t for _, t, _ in lines]
    # Paragraph breaks between lines make the model pause longer there than between sentences.
    full_text = "\n\n".join(spoken_lines)
    models = [cfg["model"], *cfg.get("fallback_models", [])]
    candidates = {m: OUT_DIR / f"take_{input_hash(PROMPT_VERSION, 'one_take', m, cfg['voice'], spoken_lines)}.wav"
                  for m in models}
    take = next((p for p in candidates.values() if p.exists()), None)
    new_calls = 0
    if take:
        print(f"  one take: cached ({take.name})")
    else:
        print(f"  one take: {len(lines)} lines, {len(full_text.split())} words, changed -> 1 TTS call")
        take = generate_with_fallback(require("GEMINI_API_KEY"), cfg, candidates, full_text, "all")
        new_calls = 1

    take_hash = take.stem.rsplit("_", 1)[-1]
    spans_file = take.with_suffix(".spans.json")  # cache: the alignment is only computed once per take
    if spans_file.exists():
        spans = [tuple(s) for s in json.loads(spans_file.read_text(encoding="utf-8"))["spans"]]
        method = json.loads(spans_file.read_text(encoding="utf-8"))["method"]
    else:
        spans, method = align_take(take, spoken_lines), "whisper-words"
        if spans is None:
            spans, method = split_take(take, len(lines)), "silences"
        spans_file.write_text(json.dumps({"method": method, "spans": spans}), encoding="utf-8")
    print(f"  cut method: {method}")
    manifest: dict = {str(s["id"]): None for s in sb["shots"]}
    for (sid, said, subtitle), (a, b) in zip(lines, spans):
        out = OUT_DIR / f"shot_{sid:02d}_t{take_hash}.wav"
        secs = cut_wav(take, out, a, b)
        rate = len(said.split()) / secs
        flag = "  <-- check split" if not 1.2 <= rate <= 4.5 else ""
        print(f"  shot {sid:02d}: {a:6.2f}-{b:6.2f}s  {secs:4.1f}s  {rate:.1f} words/s{flag}")
        manifest[str(sid)] = {"file": out.relative_to(OUTPUTS.parent).as_posix(), "hash": f"t{take_hash}",
                              "seconds": round(secs, 3), "text": subtitle, "spoken": said,
                              "take": take.relative_to(OUTPUTS.parent).as_posix(), "span": [round(a, 3), round(b, 3)]}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    spoken_s = sum(m["seconds"] for m in manifest.values() if m)
    print(f"  narration: {new_calls} new TTS call(s), {spoken_s:.1f}s of speech total")
    return manifest


# ---------------------------------------------------------------- per line

def run(only_shot: int | None = None) -> dict:
    load_env()
    sb = load()
    cfg = sb["narration"]
    if cfg.get("mode", "per_line") == "one_take":
        if only_shot is not None:
            print("  note: --shot is ignored in one_take mode (the take is one call)")
        return run_one_take(sb, cfg)

    key = None
    manifest: dict = {}
    new_calls = 0
    exhausted: set[str] = set()

    for shot in sb["shots"]:
        sid, text = shot["id"], spoken(shot)
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
                              "hash": h, "seconds": round(wav_seconds(out), 3),
                              "text": shot["narration"].strip(), "spoken": text}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    spoken = sum(m["seconds"] for m in manifest.values() if m)
    print(f"  narration: {new_calls} new TTS call(s), {spoken:.1f}s of speech total")
    return manifest
