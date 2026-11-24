# ARCHITECTURE.md

How *The Night Keeper* pipeline is put together: the stages, the contract between them,
how caching works, and what happens when something fails.

## 1. One contract, independent stages

```
                       storyboard.json  ── validated by schema/storyboard.schema.json
                              │            (+ cross-field checks in pipeline/storyboard.py)
     ┌──────────────┬─────────┼──────────────┬──────────────┬──────────────┐
     ▼              ▼         ▼              ▼              ▼              ▼
 narration       refs     keyframes        shots          music         assemble
 Gemini TTS     FLUX.2    FLUX.2 klein   Wan 2.2 5B     ACE-Step 1.5    FFmpeg
 (+ Whisper)    klein     + references   on Kaggle GPU  on Kaggle GPU   (local)
     │              │         │              │              │              │
     ▼              ▼         ▼              ▼              ▼              ▼
 outputs/       outputs/   outputs/       outputs/       outputs/       outputs/
 narration/     refs/      keyframes/     shots/         music/         final/
 manifest.json             manifest.json
     │
     └──► radio cut (narration + placeholder music on black; user test 1)

 every model call ──► runs.jsonl (one JSON line: stage, model, params, seed, latency, attempts, status, cost, output)
```

**`storyboard.json` is the only input a stage reads** (plus the outputs of earlier stages, through
their manifests). It holds the title, style block, character sheet, narration settings, music cues,
end card, and 10 shots, each with a `reason`, shot size, camera, image prompt, motion prompt,
narration line, minimum duration and seed. Prompts and seeds live here, not in code, so a run is
explainable from one file.

**Validation runs before every command** (`python -m pipeline <anything>` loads the storyboard first):
1. JSON Schema (draft 2020-12): types, required fields, enums (shot sizes), ranges (8-12 shots,
   durations, gap), the end card must contain "AI", `additionalProperties: false` everywhere so a typo
   in a field name is an error, not a silently ignored setting.
2. Cross-field checks the schema cannot express: shot ids are 1..N in order, music cues point at
   real shots, every character used in a shot exists in the character sheet.

| Stage | Command | Reads | Writes | Status |
|---|---|---|---|---|
| Narration | `narration` | `narration`, each shot's `narration` / `tts_text` | `outputs/narration/` + `manifest.json` (file, seconds, subtitle text per shot) | done |
| Radio cut | `radio` | narration manifest, `music.duck`, `end_card` | `outputs/radio/radio_cut.mp4`, `.srt`, `timeline.json` | done |
| Reference sheet | `refs` | `characters`, `style_block` | `outputs/refs/<character>/cand*.jpg`; the chosen file is written back to `characters.<name>.reference_image` | done |
| Keyframes | `keyframes` | shots, characters + their references, `style_block` | `outputs/keyframes/shot_XX_<hash>.jpg` + `manifest.json` + contact sheet | done |
| Moving shots | `shots`, `shots-status`, `shots-fetch` | keyframes manifest, `motion_prompt`, `seed` | `outputs/shots/shot_XX_<hash>.mp4` | running |
| Music | `music` | `music.cues` | `outputs/music/` | to do |
| Assembly | `assemble` | all manifests, timeline | `outputs/final/` 9:16 and 16:9 | to do |

## 2. Timing: the narration sets the pace

Professionals cut picture to the voice track, so `pipeline/timeline.py` builds the edit from the
**measured** narration lengths: `shot duration = max(min_duration_s, 0.3 s lead-in + speech + gap_s)`.
Subtitles come from the same timeline: at most ~70 characters per event, at most 2 lines of ~40
characters, split at sentence or comma boundaries, timed in proportion to the characters spoken.
The subtitle shows `narration`; the voice may be given a different spelling (`tts_text`, used for
"Abba" -> "Aba", EXPERIMENTS E4).

## 3. Caching: a re-run only regenerates what changed

Every generated file is named after a **hash of everything that changes it**
(`pipeline/storyboard.py: input_hash`, SHA-256 of a JSON list, first 10 hex characters):

| Output | Hash covers |
|---|---|
| narration, per-line mode | prompt version, model, voice, style, spoken text |
| narration, one-take mode | prompt version, model, voice, **all** spoken lines (one take) |
| reference candidate | model, prompt, size, seed |
| keyframe | model, full prompt (shot + character descriptions + style block), size, seed, **bytes of each reference image** |
| moving shot | model, **bytes of the keyframe**, motion prompt + style suffix, negative prompt, seed, generation settings |

Before calling a model a stage checks whether the file for the current hash exists; if it does, it
is a cache hit and no call is made. Consequences:

- Change one `image_prompt` -> one new keyframe -> because the keyframe's bytes feed the shot hash,
  exactly one shot is re-animated. Nothing else moves.
- Change a character's reference image -> every keyframe with that character is regenerated, and only those.
- Choosing between candidates is a cache operation: `keyframes --shot N --variants 3` saves candidates
  under the names a normal run would use for seeds s, s+1000, s+2000, so picking one = setting the
  shot's `seed`, and the next run makes **0** calls (verified, EXPERIMENTS E10/E11).
- Old files are kept, so earlier versions can be compared and the run can be inspected.

**Why the cache matters more than the seed here:** FLUX.2 klein on Workers AI does **not** return the
same image for the same seed (EXPERIMENTS E7). The seed is recorded but the cache is what makes the
film reproducible from a clean clone that includes `outputs/`.

**One-take narration trade-off:** to keep the narrator's voice continuous (user test 1), all lines are
generated in one request and then cut into per-shot files using Whisper word timestamps
(EXPERIMENTS E5, E6). Changing any line regenerates the whole take: 1 request instead of 1, but every
shot's audio changes slightly. `"mode": "per_line"` is still supported when single-line re-takes matter more.
The cut points are cached next to the take (`take_<hash>.spans.json`).

## 4. Failure handling

| Failure | Handling | Where |
|---|---|---|
| 429 rate limit (per minute), 5xx, network errors | retry with backoff 2 s, 4 s, 8 s (3 retries) | `common.http_json`, `common.http_multipart` |
| 429 **daily** quota | do **not** retry (it would waste tomorrow's quota): fail fast and fall to the next model | `common.is_daily_quota`, `narration.generate_with_fallback` |
| One TTS model's daily quota used up | ordered fallback list in `narration.fallback_models` (quotas are per model, COSTS.md) | storyboard + narration stage |
| TTS reads the style instruction aloud | only the line is sent; every take is checked by Whisper (`qa_transcribe`, `qa_align`) | FAILURES F7 |
| Pause-based split mis-cuts the take | Whisper word alignment first, pause detection only as fallback | FAILURES F9 |
| Keyframe drifts (pose, skin tone, coat) | `--variants` (3 tries per shot, the brief's rule), then change approach (`use_references: false`) | EXPERIMENTS E9-E11 |
| Kaggle run times out or one shot crashes | each clip is written as soon as it is done; one failed shot is logged and the run continues | `kaggle/wan_runner.py` |
| A shot has no clip at all | assembly uses a slow pan-and-zoom (Ken Burns) over the keyframe instead | assembly stage (planned) |
| Invalid storyboard | the run stops before any model call with a list of every problem | `storyboard.validate` |

Every call, successful or not, is one line in `runs.jsonl` with its error text and the number of
attempts, so a failure can be traced to the exact request.

## 5. Where things run

| Where | What | Why |
|---|---|---|
| Laptop (Windows, Python 3.14) | orchestration, FFmpeg, all API calls | no GPU needed |
| Gemini API (free tier) | narration TTS | free, 10 requests/day/model (COSTS.md) |
| Cloudflare Workers AI (free allowance) | FLUX.2 klein images, Whisper QA | fast (~8 s/image), daily free allowance |
| Kaggle notebook, GPU T4 x2 (30 h/week) | Wan 2.2 video, ACE-Step music | open weights need a GPU |

The Kaggle part is driven from the laptop with the Kaggle CLI: `shots` uploads a private dataset
(`jobs.json` + the keyframes that need clips) and pushes `kaggle/wan_runner.py` as a script kernel
with GPU and internet on; `shots-fetch` downloads the clips and merges the kernel's log
(`runs_kaggle.jsonl`: latency, GPU minutes, peak VRAM per clip) into `runs.jsonl`. On Kaggle the
jobs are split across the two T4s, one worker process per GPU.

## 6. Secrets

Keys live only in `.env` (git-ignored); `.env.example` lists the names. They are sent in headers,
never in URLs, and never written to `runs.jsonl`. Every commit is scanned for key patterns first.
