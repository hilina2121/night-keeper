# COSTS.md

Measured from `runs.jsonl`. Every call so far ran on a free tier ($0 paid).
List-price equivalents are in the stage table below.

## Free tiers as found (24 Nov 2026)

| Provider | What I found |
|---|---|
| Gemini API (AI Studio) | 65 models listed. `gemini-3.8-flash-tts` works on the free tier. `gemini-omni-1.2-flash` (video) has a free limit of **0**. `gemini-3.8-flash` was overloaded (503). |
| Cloudflare Workers AI | FLUX models available: `flux-1-schnell`, `flux-2-klein-4b`, `flux-2-klein-9b`, `flux-2-dev` |
| Kaggle | Phone verified; GPU T4 x2, **30 h/week** (0 used on 24 Nov) |

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

## Stage measurements (whole project, from `runs.jsonl`, 205 lines, 24-25 Nov)

Median latency of successful calls; "total" = sum of successful latencies. Every paid-looking
number is zero: **$0 was spent**. The last column is what the same work would cost at list price,
see the method below.

| Stage | Model / tool | Where | Calls (ok) | Median latency | Total time | List-price equivalent |
|---|---|---|---|---|---|---|
| Narration | Gemini TTS: 3.8 Flash (5 ok of 19), 3.8 Flash-Lite (9/13), 3.1 Flash preview (9/10), 2.5 Flash preview (11/11) | Gemini API, free tier | 53 (34) | 3.3-8.3 s | 3.7 min | < $0.05 |
| QA: transcribe + align | Whisper large-v3-turbo | Cloudflare Workers AI | 29 (29) | 2.8 s | 1.6 min | < $0.01 |
| Reference sheet | FLUX.2 klein 4B, 1024² | Cloudflare Workers AI | 16 (16) | 11.2 s | 3.0 min | within the daily free allowance |
| Keyframes (incl. variants) | FLUX.2 klein 4B, 1024² | Cloudflare Workers AI | 32 (32) | 7.9 s | 4.5 min | within the daily free allowance |
| Experiments (FLUX seeds, voices) | FLUX.2 klein 4B, Gemini TTS, Whisper | Cloudflare, Gemini | 16 (14) | 5.5-9.7 s | 1.6 min | < $0.02 |
| Moving shots | Wan 2.2 TI2V-5B | Kaggle, GPU T4 ×2 | 2 attempts (0) | load 124.5 s; OOM after 17.5 s | **1 h 54 min of GPU quota** (Kaggle counter) | ≈ $0.70 (1.9 GPU-h × ~$0.35/h for a T4) |
| Music | ACE-Step (community Space `victor/ace-step-jam`) | Hugging Face ZeroGPU A10G | 16 (5) | 11.7 s per 25-44 s track | 51 s of GPU | ≈ $0.02 (51 s × ~$1/h for an A10G) |
| Radio cut + final assembly | FFmpeg 9.1 | laptop | 31 (31) | 6-9 s | 6.7 min | $0 |

**Per minute of finished film (66.5 s):** about 15 minutes of model calls that succeeded, plus 2 GPU-hours on attempts that failed.

**Free-tier limits that shaped the pipeline:**

| Limit | Measured | Effect on the design |
|---|---|---|
| Gemini TTS | 10 requests/day **per model**, some models 3/min | quota-aware fallback chain; one-take narration = 1 request (E5) |
| Cloudflare Workers AI | ~50 images and ~30 transcriptions in one day without hitting a limit | no change needed |
| Kaggle GPU | 30 h/week; 1 interactive GPU session at a time; API-started runs never left the queue (10.5 h); interactive queue up to position 614 | run by hand in the editor; Ken Burns fallback for video (F11, F13-F15) |
| HF ZeroGPU | anonymous ≈ 180 s/day; logged-in free account: 5 runs before "runs limit" | `HF_TOKEN`; 2 candidates for the second cue instead of 3 (F16) |

**Method for the list-price column (approximate, check the providers' current pages):** GPU time at
typical on-demand cloud prices (NVIDIA T4 ≈ $0.35/h, A10G ≈ $1/h). Gemini TTS: Google's published
paid-tier rates for Flash TTS (cents per minute of audio); about 10 minutes of audio were generated in
total. Cloudflare: the FLUX and Whisper calls stayed inside the daily free allowance (no billing
attached). These are order-of-magnitude figures, not invoices.

**Frontier comparison:** not done. No frontier lane (Omni Flash, Nano Banana, Lyria) was opened for this
cohort, and `gemini-omni-1.2-flash` has a free quota of 0 (F1).
