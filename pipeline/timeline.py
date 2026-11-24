"""Timeline: turns the storyboard + measured narration lengths into shot start/end times.

The narration sets the pace (professionals cut picture to the voice track):
shot duration = max(min_duration_s, lead_in + narration length + gap).
"""
from __future__ import annotations

import re

LEAD_IN_S = 0.3  # voice starts this long after the cut


def build(sb: dict, manifest: dict) -> dict:
    gap = sb["narration"].get("gap_s", 0.6)
    t = 0.0
    shots = []
    for s in sb["shots"]:
        n = manifest.get(str(s["id"]))
        speech = n["seconds"] if n else 0.0
        dur = max(s["min_duration_s"], (LEAD_IN_S + speech + gap) if n else 0)
        shots.append({"id": s["id"], "start": round(t, 3), "duration": round(dur, 3),
                      "voice_start": round(t + LEAD_IN_S, 3) if n else None,
                      "voice_seconds": speech, "text": s["narration"].strip(),
                      "voice_file": n["file"] if n else None})
        t += dur
    end_card = {"start": round(t, 3), "duration": sb["end_card"]["duration_s"], "text": sb["end_card"]["text"]}
    return {"shots": shots, "end_card": end_card, "total": round(t + end_card["duration"], 3)}


def _ts(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _wrap(text: str, width: int = 40) -> str:
    """At most 2 lines of ~40 characters."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur); cur = w
        else:
            cur = f"{cur} {w}".strip()
    lines.append(cur)
    return "\n".join(lines)


def _chunks(text: str, max_chars: int = 70) -> list[str]:
    """Split a long line into subtitle-sized pieces at sentence boundaries."""
    sentences = []
    for s in re.split(r"(?<=[.!?])\s+", text):
        # A sentence longer than 2 subtitle lines is split after a comma.
        sentences += re.split(r"(?<=,)\s+", s) if len(s) > max_chars else [s]
    out, cur = [], ""
    for s in sentences:
        if cur and len(cur) + 1 + len(s) > max_chars:
            out.append(cur); cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        out.append(cur)
    return out


def srt(tl: dict) -> str:
    events = []
    for s in tl["shots"]:
        if not s["voice_file"]:
            continue
        pieces = _chunks(s["text"])
        total_chars = sum(len(p) for p in pieces)
        t = s["voice_start"]
        for i, p in enumerate(pieces):
            d = s["voice_seconds"] * len(p) / total_chars
            hold = 0.4 if i == len(pieces) - 1 else 0.0  # only the last piece lingers, so pieces never overlap
            events.append((t, t + d + hold, _wrap(p)))
            t += d
    ec = tl["end_card"]
    events.append((ec["start"] + 0.2, ec["start"] + ec["duration"], ec["text"]))
    return "\n".join(f"{i}\n{_ts(a)} --> {_ts(b)}\n{txt}\n" for i, (a, b, txt) in enumerate(events, 1))
