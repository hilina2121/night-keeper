# FAILURES.md

What broke, what I tried, what fixed it. Newest at the bottom. Evidence is in `runs.jsonl`.

## F1. Wrong Gemini model picked: free quota is 0 (24 Nov)
- **What broke:** the smoke test picked the text model by matching "flash" in the name. It chose `gemini-omni-1.2-flash` (the new video model), which returned **HTTP 429, free-tier limit: 0**.
- **What I learned:** the brief warned that Veo moved to the "Omni Flash" family behind paid billing. The model list now has 65 entries and a loose name match is not safe.
- **Fix:** match only plain text models with a regex (`gemini-<version>-flash`). The next run picked `gemini-3.8-flash`.

## F2. `seed` rejected by FLUX.1 schnell on Workers AI (24 Nov)
- **What broke:** `@cf/black-forest-labs/flux-1-schnell` returned **HTTP 400: "Additional or unevaluated properties '/seed' not allowed"**.
- **Why it matters:** without a seed, the same prompt gives a different image each time, so experiments are not comparable.
- **Fix (temporary):** removed `seed` for schnell; the image then generated in 2.7 s.
- **Next:** the account also lists `flux-2-klein-4b` (Apache 2.0) and `flux-2-klein-9b`. Test whether klein accepts a seed and reference images, which the character sheet needs.

## F3. Gemini 3.8 Flash: 503 "high demand" (24 Nov)
- **What broke:** `gemini-3.8-flash` returned **HTTP 503 UNAVAILABLE** on every attempt; the retry wrapper waited 2 s, 4 s, 8 s and gave up after 34 s.
- **Also found:** failed calls were logged with `attempts=1` even after retrying. Fixed so the real retry count is logged.
- **Plan (F3):** text generation is not on the critical path (I write the storyboard myself). Fall back to `gemini-3.8-flash-lite` if it keeps failing.

## F4. FFmpeg install cut off on a slow connection (24 Nov)
- **What broke:** `winget install Gyan.FFmpeg` downloads a ~200 MB zip; the first attempt was still downloading after 10 minutes and was interrupted when the session restarted.
- **Fix:** re-ran the install in the background while working on the story. FFmpeg 9.1 installed. New terminals need to be reopened to see it on PATH.

## F5. Gemini TTS free tier: only 10 requests per day (24 Nov)
- **What broke:** after the smoke test (2 calls) and the voice audition (8 calls), the next TTS call returned **HTTP 429: generate_content_free_tier_requests, limit: 10, model: gemini-3.8-flash-tts**.
- **Why it matters:** the narration has 9 lines. Generating one file per line (as the brief suggests) uses 9 of the 10 daily calls, which leaves almost nothing for re-takes or for the live regeneration in the walkthrough.
- **What I will do:**
  1. **Cache hard:** the narration stage only calls the API for a line whose text, voice or style changed (hash of inputs).
  2. **Fallback chain:** quotas are per model, so on 429 fall back to `gemini-3.8-flash-lite-tts`, then `gemini-3.1-flash-tts-preview`. The voice may sound slightly different, so log which model made each line.
  3. **Spend quota on purpose:** no more casual tests; the quota resets at midnight Pacific time (11:00 EAT).

## F6. Wrong name for the "lite" text model (24 Nov)
- **What broke:** tried `gemini-3.8-flash-lite` for transcription: **HTTP 404**. `gemini-3.8-flash` was still 503 (overloaded).
- **Fix:** listed models. There is no 3.8 flash-lite text model; the lite text models are `gemini-3.5-flash-lite` and `gemini-3.1-flash-lite`. Lesson: always list before calling, never guess a model name.

## F7. The TTS read my style instruction out loud (24 Nov)
- **What broke:** I sent `"Read this aloud in a calm, warm, unhurried ... voice: <line>"`. Every file was 9–18 s long; "A good school." (3 words) took **9.4 s**.
- **How I found it:** added a QA step that transcribes each file with Whisper (`@cf/openai/whisper-large-v3-turbo` on Cloudflare, `python -m pipeline.transcribe`). Every transcript began with *"Read this aloud in a calm, warm..."*.
- **Tried:** moved the style into `systemInstruction` → **HTTP 400 "Developer instruction is not enabled for this model"** (TTS models don't accept it).
- **Fix:** send only the line itself; warmth comes from the voice choice. "A good school." is now **1.6 s** and Whisper hears exactly the line, for all 9 lines.
- **Knock-on:** the "1.65 words/s" in COSTS.md was wrong; it included the instruction. Real rate is **~2.65 words/s**.

## F8. Retries were burning the daily quota; per-minute limit not handled (24 Nov)
- **What broke (1):** on a *daily* 429 the retry wrapper tried 3 more times. Each retry used another request from a 10-per-day budget.
- **Fix:** `is_daily_quota()` detects "per day" in the 429 body and fails fast, so the narration stage falls back to the next model immediately and remembers that model is exhausted for the rest of the run.
- **What broke (2):** `gemini-3.1-flash-tts-preview` has a **3 requests/minute** limit. My backoff waited 2+4+8 s and gave up before the minute passed.
- **Fix:** the retry now reads Gemini's own `"retryDelay": "Ns"` from the error and waits that long. The re-run cached shots 1–8 and generated only 9 and 10.
- **Result:** narration for the radio cut uses `gemini-3.1-flash-tts-preview` for **all 9 lines** (one consistent voice). Switch back to 3.8 for the final once its quota resets.
