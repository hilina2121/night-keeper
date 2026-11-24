# COSTS.md

Measured from `runs.jsonl`. Every call so far ran on a free tier ($0 paid).
List-price equivalents will be added per stage.

## Free tiers as found (24 Nov 2026)

| Provider | What I found |
|---|---|
| Gemini API (AI Studio) | 65 models listed. `gemini-3.8-flash-tts` works on the free tier. `gemini-omni-1.2-flash` (video) has a free limit of **0**. `gemini-3.8-flash` was overloaded (503). |
| Cloudflare Workers AI | FLUX models available: `flux-1-schnell`, `flux-2-klein-4b`, `flux-2-klein-9b`, `flux-2-dev` |
| Kaggle | Phone verified; GPU T4 x2 available (quota to record) |

## Smoke test measurements (24 Nov)

| Call | Model | Latency | Notes |
|---|---|---|---|
| Narration, 1 line (17 words) | gemini-3.8-flash-tts | 4.5 s | 10.1–10.4 s of audio → **1.63–1.68 words/s** (slower than the brief's 2–2.5). 150 words ≈ 90 s, so the script must stay under ~140 words |
| Keyframe, 1024×1024 | flux-1-schnell, 4 steps | 2.7 s | 467 KB JPEG |
| Model listing | — | 0.3–0.6 s | |

> **Correction:** the 1.63–1.68 words/s above included the style instruction being read aloud (FAILURES F7). Real narration rate is **~2.6 words/s**.

## Gemini TTS free-tier limits, as measured (24 Nov)

Every TTS model has its **own** quota, which makes a fallback chain possible.

| Model | Requests/day | Requests/min | Notes |
|---|---|---|---|
| gemini-3.8-flash-tts | **10** | — | Used up by smoke test + voice audition (E1) |
| gemini-3.8-flash-lite-tts | **10** | — | Used up by the v1 narration (instruction-read-aloud bug) |
| gemini-3.1-flash-tts-preview | (≥ 10) | **3** | Made the first clean narration (Charon) |
| gemini-2.5-flash-preview-tts | (≥ 9) | — | Made the radio-cut narration with Sulafat, 9 calls |

**Consequence for the design:** one file per line (9 lines) costs 9 of ~10 daily calls on a model.
Caching by input hash is therefore not optional: the walkthrough's "change one line" demo must cost exactly one call.

## Stage measurements

| Stage | Model / tool | Calls | Latency per call | Output | Cost |
|---|---|---|---|---|---|
| Narration (9 lines, Sulafat) | gemini-2.5-flash-preview-tts | 9 | see `runs.jsonl` stage `narration` | 41.9 s of speech | $0 (free tier) |
| QA transcription | @cf/openai/whisper-large-v3-turbo | 1 per line | see `runs.jsonl` stage `qa_transcribe` | transcripts | $0 (free allowance) |
| Radio cut | FFmpeg 9.1 (local) | 1 | 8–10 s for 66 s of video | 1080×1920 MP4, −14.3 LUFS, −1.0 dBFS peak | $0 |
