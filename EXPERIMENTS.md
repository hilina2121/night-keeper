# EXPERIMENTS.md

Each entry: **hypothesis → change → result → decision**. One thing changed at a time.
Evidence: matching `"experiment": "E…"` lines in `runs.jsonl`.

## E1. Which female voice for the narrator? (24 Nov)

- **Why:** the narrator is the daughter telling her father's story, so the voice should be a young woman's. The smoke test used a male voice (Charon).
- **Hypothesis:** a voice Google describes as "warm" (Sulafat) will suit a grateful, intimate story better than "youthful", "soft" or "gentle".
- **Change:** same model (`gemini-3.8-flash-tts`), same 2 lines (first and last narration lines, 30 words), same style instruction
  (*"calm, warm, unhurried, like a daughter quietly remembering her father"*). Only the voice changes.
- **Result (measured):**

  | Voice | Google's description | Audio length | Words/s |
  |---|---|---|---|
  | Sulafat | warm | 27.0 s | 1.11 |
  | Leda | youthful | 28.9 s | 1.04 |
  | Achernar | soft | 25.8 s | 1.16 |
  | Vindemiatrix | gentle | 29.8 s | 1.01 |

- **Surprise:** every voice spoke **~1.0–1.16 words/s**, much slower than the smoke test (1.65 words/s with Charon and a shorter style instruction).
  Two possible causes: (a) "unhurried… quietly remembering" slows the delivery, or (b) the model reads the instruction aloud.
  A follow-up (E1b) to transcribe the audio and to compare a short style was blocked by the daily quota (see FAILURES F5).
- **Listening result:** I listened to all four. **Sulafat** sounded right: "the way she talks, everything is perfect". None of the samples read the style instruction aloud, so the slow pace is real delivery: pauses and an unhurried tone.
- **Hypothesis confirmed:** the "warm" voice suited the story best.
- **Decision:** narrator = **Sulafat**, style kept exactly as tested. Consequence: at ~1.1 words/s, 110 words ≈ 100 s, which is over the 90 s limit. The narration must be cut to **~75–80 words**, or the pace measured on the full narration first (short test lines may exaggerate pauses). This will be checked on the radio cut.
- **Correction (24 Nov, later):** a Whisper QA check (`python -m pipeline.transcribe`) shows the audition files **did** include the instruction read aloud, e.g. Sulafat_1: *"Say, in a calm, warm, unhurried, like a daughter quietly remembering her father voice. Every night, while the city slept..."*. That explains the ~1.1 words/s. All four voices had the same extra words, so the comparison was still fair and **Sulafat stays the narrator**, but the timing conclusion is replaced by E2.

## E2. Does a style instruction in the text change the delivery, or just get read out? (24 Nov)

- **Hypothesis:** putting a style instruction before the line ("Read this aloud in a calm... voice:") makes the TTS speak more warmly.
- **Change:** v1 = instruction + line in the text; v2 = instruction in `systemInstruction`; v3 = the line only. Same line ("A good school."), checked with Whisper.
- **Result:**

  | Prompt | Audio | What Whisper heard |
  |---|---|---|
  | v1 instruction in text | 9.4 s | "Read this aloud in a calm, warm, unhurried, like telling a memory to a friend voice. A good school." |
  | v2 systemInstruction | — | HTTP 400 "Developer instruction is not enabled for this model" |
  | v3 line only | 1.6 s | "A good school." |

- **Hypothesis rejected:** with a long instruction the model does not obey it, it *says* it.
- **Decision:** send the line only; choose warmth with the voice (E1). Whisper QA stays in the pipeline as a check.
- **Evidence:** `runs.jsonl` stage `narration` (shot 5) and stage `qa_transcribe`.

## E3. Is the narration long enough? Space vs. words (24 Nov)

- **Hypothesis:** the film can reach 60–90 s by adding pauses and holds, without adding words.
- **Change:** `gap_s` 0.6 → 1.2 s; `min_duration_s` raised on shots 1, 3, 5, 7, 9, 10. Narration text unchanged (110 words, 41.5 s of speech).
- **Result:** radio cut 56.9 s → **65.8 s**. Loudness after `loudnorm`: −14.6 LUFS integrated, −0.8 dBFS peak.
- **Decision:** keep. User test 1 will tell whether the pauses feel heavy or moving.
