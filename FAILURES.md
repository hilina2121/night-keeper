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

## F9. Splitting the one-take narration at pauses mis-cut two shots (24 Nov)
- **What broke:** the first one-take narration was cut at the 8 longest silences. Shots 6 and 7 came out impossible: 11 words in 1.6 s.
- **Why:** inside line 6 ("Today I work for a good company. I can help him now. But I am not where I want to be. Not yet.") the narrator pauses between sentences about as long as between lines.
- **Tried:** the same splitter on a synthetic take (v1 lines + 0.7 s silences) worked perfectly, which hid the problem.
- **Fix:** align the script to Whisper word timestamps (EXPERIMENTS E6). No extra TTS request was needed: the take was cached, only the cut changed.

## F10. Kaggle CLI on Windows + Python 3.14 (24 Nov)
- **What broke (1):** `kaggle` 2.2.5 crashed on import: `ModuleNotFoundError: No module named 'six'` (a dependency it does not declare, missing on Python 3.14). **Fix:** `pip install six`; added `kaggle` and `six` to `requirements.txt`.
- **What broke (2):** the first `python -m pipeline shots` crashed while reading the CLI's output: `UnicodeDecodeError: 'charmap' codec can't decode byte 0x8f`. Windows decodes subprocess output as cp1252 and the upload progress bar uses Unicode block characters. **Fix:** read the CLI output as UTF-8 with `errors="replace"`.
- **Also found:** `.env.example` had disappeared (renamed to `.env` during setup instead of copied), so a fresh clone would not know which keys to set. Recreated, with `KAGGLE_USERNAME` added.
- **New token format:** Kaggle now issues API *tokens* (`KAGGLE_API_TOKEN` env var) instead of the legacy `kaggle.json`; the CLI accepted the token directly.

## F11. Kaggle GPU queue: the Wan test sat in "QUEUED" for 30+ minutes (24 Nov, ~21:20 EAT)
- **What happened:** `python -m pipeline shots --shot 4` uploaded the job and pushed the kernel at 21:19; the kernel stayed `KernelWorkerStatus.QUEUED` (waiting for a free T4) for more than half an hour. Queued time does not use the 30 h quota.
- **Why it matters:** the brief's warning was right: the binding constraint is the GPU queue, not money. A plan that waits for video before editing would stall here.
- **Worked around:** built the assembly stage meanwhile with the brief's fallback: every shot without a Wan clip is animated with a Ken Burns move chosen from its `camera` field. A complete rough cut exists before any video model has run; Wan clips replace stills automatically when `shots-fetch` brings them in (the assembly picks the clip whose hash matches the current keyframe and motion prompt).

## F12. 16:9 export cut off heads (24 Nov)
- **What broke:** the first 16:9 export centre-cropped the square keyframes to 1440x810. Shot 4 lost the father's head; shot 8 lost the top of the frame.
- **Fix:** for 16:9 the whole square is shown in the middle over a blurred, darkened copy of itself (a common way to fit square or vertical footage in a wide frame). 9:16 keeps the centre crop, which works because every keyframe was composed with the subject in the middle (style block: "subject centred in frame").
- **Also measured:** first mix at **−15.5 LUFS**, −0.9 dBFS peak (target −14 / −1). Single-pass `loudnorm` undershoots when the end card is silent; to fix with two-pass loudnorm in the final mix.

## F13. API-started Kaggle GPU run never left the queue; the hand-started one hit a launcher bug (25 Nov)
- **What broke (1):** the kernel pushed by `python -m pipeline shots` at 21:19 was still `QUEUED` at 07:48 the next morning, **10.5 hours**, while an interactive session started in the Kaggle editor got a GPU after a queue position of 8 in about 4 minutes.
- **Workaround:** stopped relying on API-started GPU runs. The local stages still build the job, upload the dataset and push the code (`kernels push --no-run` for music), but the run is started by hand in the editor: Edit → GPU T4 x2 + Internet → Run All.
- **What broke (2):** in the editor the runner re-launched itself as two GPU workers with `sys.argv[0]`, which inside a notebook is `ipykernel_launcher.py`. That started a second kernel (`[ColabKernelApp] WARNING | Unrecognized alias: 'worker'`) that waits forever, so the run hung after the model download (11 GPU-minutes lost).
- **Fix:** cancelled, then called the already-defined `worker(0, jobs, input_dir)` from the Kaggle console, reusing the downloaded weights. The runner now re-launches only when it really is a script file, and otherwise runs on one GPU in-process.
- **Measured:** Wan 2.2 TI2V-5B (diffusers, fp16 transformer + fp32 VAE, CPU offload) loads in **124.5 s** on a T4.

## F14. Wan 2.2 TI2V-5B does not run usefully on Kaggle's free T4s (25 Nov)
- **Attempt 1, one T4 (15 GB), fp16 transformer + fp32 VAE + `enable_model_cpu_offload()`, 640×640, 97 frames, 30 steps:** model loaded in 124.5 s, then **`OutOfMemoryError: CUDA out of memory. Tried to allocate 108.00 MiB. GPU 0 has a total capacity of 14.56 GiB of which 14.81 MiB is free`** after 17.5 s of generation (logged in the Kaggle run).
- **Attempt 2, both T4s, `device_map="balanced"` (text encoder and transformer on different GPUs) + VAE tiling, same settings:** loaded, the sampler started (`0/30`), made **no step** for well over an hour, then the session died: **"Kernel died unexpectedly"**. Most likely cause: moving activations between the two GPUs through the CPU on every layer, plus host memory pressure (about 30 GB of RAM for 22 GB of weights).
- **GPU time spent:** about 2 h of the 30 h weekly quota, for no clip. The earlier API-started run (F11, F13) never got a GPU at all.
- **Not tried, and why:** sequential CPU offload, or 480p with fewer frames. Both are possible, but with the deadline the next day the required deliverables (original score, second audience test, report) had to come first. A smaller Wan run for one or two hero shots stays on the "if time allows" list.
- **Decision:** the film uses the brief's fallback for every shot, a slow Ken Burns camera move over each keyframe, chosen from the shot's `camera` field (push-in, pan, gentle drift). The pipeline still supports Wan clips: if a clip with the shot's current hash ever lands in `outputs/shots/`, `assemble` uses it instead of the still, automatically.
- **Lesson:** "runs on a consumer GPU" in a model card means a 24 GB RTX 4090, not a 15 GB T4 without bf16. Check memory against the card's own test hardware before spending quota, and test the smallest setting first, not the target one.
