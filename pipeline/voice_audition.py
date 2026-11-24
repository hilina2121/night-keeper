"""Experiment: which female Gemini voice suits the narrator?

Same two lines, same style instruction, only the voice changes.
Writes outputs/voice_audition/<voice>.wav (both lines joined by a short pause).

    python -m pipeline.voice_audition
"""
from __future__ import annotations

import wave

from pipeline.common import OUTPUTS, load_env, require
from pipeline.tts import SAMPLE_RATE, synthesize

# Female prebuilt voices, with Google's one-word description of each.
VOICES = {
    "Sulafat": "warm",
    "Leda": "youthful",
    "Achernar": "soft",
    "Vindemiatrix": "gentle",
}
STYLE = "calm, warm, unhurried, like a daughter quietly remembering her father"
LINES = [
    "Every night, while the city slept, my father kept watch over a mall that was not his.",
    "Because one day, I will rebuild his house. Abba, this is my promise.",
]


def join_wavs(parts, out, pause_s=0.6):
    silence = b"\x00\x00" * int(SAMPLE_RATE * pause_s)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SAMPLE_RATE)
        for i, p in enumerate(parts):
            with wave.open(str(p), "rb") as r:
                w.writeframes(r.readframes(r.getnframes()))
            if i < len(parts) - 1:
                w.writeframes(silence)


def main():
    load_env()
    key = require("GEMINI_API_KEY")
    folder = OUTPUTS / "voice_audition"
    print(f"{'voice':<14}{'desc':<10}{'seconds':>8}{'words/s':>9}")
    for voice, desc in VOICES.items():
        parts, total_s, total_w = [], 0.0, 0
        for i, line in enumerate(LINES, 1):
            part = folder / "parts" / f"{voice}_{i}.wav"
            s = synthesize(key, line, part, voice=voice, style=STYLE,
                           stage="experiment:voice", experiment="E1")
            if s:
                parts.append(part); total_s += s; total_w += len(line.split())
        if parts:
            join_wavs(parts, folder / f"{voice}.wav")
            print(f"{voice:<14}{desc:<10}{total_s:>8.1f}{total_w / total_s:>9.2f}")


if __name__ == "__main__":
    main()
