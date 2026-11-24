"""Experiment E4b: which spelling makes the TTS say "Abba" (AH-bah) correctly?

Same voice, same model chain, same sentence; only the spelling of the name changes.
Writes outputs/spelling_audition/<n>_<spelling>.wav for listening.

    python -m pipeline.spelling_audition
"""
from __future__ import annotations

import re

from pipeline.common import OUTPUTS, load_env, require
from pipeline.narration import generate_with_fallback
from pipeline.storyboard import load

SPELLINGS = ["Aba", "Ahbah", "Ah-ba", "Abbah"]  # "Ahba" (E4) was heard as "Ababa" by the user
SENTENCE = "{name}, this is my promise."


def main() -> None:
    load_env()
    key = require("GEMINI_API_KEY")
    cfg = load()["narration"]
    models = [cfg["model"], *cfg.get("fallback_models", [])]
    folder = OUTPUTS / "spelling_audition"
    for i, name in enumerate(SPELLINGS, 1):
        text = SENTENCE.format(name=name)
        safe = re.sub(r"[^A-Za-z]", "", name)
        candidates = {m: folder / f"{i}_{safe}__{m}.wav" for m in models}
        done = next((p for p in candidates.values() if p.exists()), None)
        if done:
            print(f"  {name:<7} cached  {done.name}")
            continue
        print(f"  {name:<7} '{text}'")
        generate_with_fallback(key, cfg, candidates, text, f"E4b:{name}")


if __name__ == "__main__":
    main()
