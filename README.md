# The Night Keeper

A 60–90 second AI-made short film about my father, who guarded a mall at night so I could
go to a good school, and the house I promised to rebuild for him. It is narrated in English,
with an original score and English subtitles, in vertical (9:16) and horizontal (16:9).

This repository is the **studio that makes the film**: a pipeline that turns one file,
[`storyboard.json`](storyboard.json), into narration, keyframes, moving shots, music and a finished edit.
Change a line in the storyboard, run the pipeline again, and only what changed is regenerated.

> Status (24 Nov 2026): narration, radio cut, reference sheet and keyframes are done. Moving shots are
> running on Kaggle. Music and final assembly are next. See "Stages" below.

## Quick start

Requirements: Python 3.11+ (tested on 3.14, Windows 11), [FFmpeg](https://ffmpeg.org/) on PATH, and free accounts at
[Google AI Studio](https://aistudio.google.com/apikey), [Cloudflare](https://dash.cloudflare.com/sign-up)
(Workers AI) and [Kaggle](https://www.kaggle.com) (phone-verified for GPU).

```bash
git clone <this repo> && cd <repo>
pip install -r requirements.txt
cp .env.example .env          # then fill in the 5 values (see below)
python -m pipeline validate   # checks storyboard.json against schema/storyboard.schema.json
python -m pipeline all        # narration -> radio cut -> keyframes (only what is missing or changed)
```

| `.env` key | Where to get it |
|---|---|
| `GEMINI_API_KEY` | AI Studio → Get API key |
| `CLOUDFLARE_ACCOUNT_ID` | the long id in your dashboard URL |
| `CLOUDFLARE_API_TOKEN` | Workers AI → REST API → Create a Workers AI API Token |
| `KAGGLE_API_TOKEN` | kaggle.com/settings → API Tokens → Generate New Token |
| `KAGGLE_USERNAME` | your Kaggle username |

Because generated files are committed in `outputs/` and every output is cached by a hash of its
inputs, `python -m pipeline all` on a fresh clone with unchanged inputs makes **no model calls**: it
finds every file and rebuilds the cuts.

## Stages

Every command first validates the storyboard. Each stage reads `storyboard.json`, writes to `outputs/`,
and logs every model call to [`runs.jsonl`](runs.jsonl).

| Command | What it does | Model | Runs on |
|---|---|---|---|
| `python -m pipeline narration` | Speaks all lines in **one take** (one continuous voice), cuts it into one file per shot with Whisper word timestamps | Gemini 3.8 Flash TTS, voice *Sulafat* (fallbacks listed in the storyboard) + Whisper large-v3-turbo | Gemini API, Cloudflare |
| `python -m pipeline radio` | Radio cut: narration over a placeholder drone on black, ducked, subtitled, loudness-normalised (−14 LUFS) | FFmpeg | laptop |
| `python -m pipeline refs` | 4 reference candidates per character; the chosen one goes in `characters.<name>.reference_image` | FLUX.2 klein 4B | Cloudflare Workers AI |
| `python -m pipeline keyframes` | One 1024² keyframe per shot, with the character references as input images | FLUX.2 klein 4B | Cloudflare Workers AI |
| `python -m pipeline keyframes --shot 6 --variants 3` | Three candidates for one shot; pick one by setting that shot's `seed` | FLUX.2 klein 4B | Cloudflare |
| `python -m pipeline shots` | Uploads keyframes that have no clip yet to Kaggle and starts Wan 2.2 image-to-video on GPU T4 x2 | Wan 2.2 TI2V-5B | Kaggle |
| `python -m pipeline shots-status` / `shots-fetch` | Checks the Kaggle run / downloads the clips and merges their logs into `runs.jsonl` | | laptop |
| `music`, `assemble` | *(next)* ACE-Step score; final edit in 9:16 and 16:9 with ducking, subtitles, end card | ACE-Step 1.5, FFmpeg | Kaggle, laptop |

### Regenerate one shot (the walkthrough demo)

Edit one shot's `image_prompt` in `storyboard.json`, then:

```bash
python -m pipeline keyframes
```

Nine shots print `cached`, one prints `GENERATING`, and `runs.jsonl` gains exactly one new line.
Because a clip's hash includes the keyframe's bytes, `python -m pipeline shots` will then re-animate
only that shot.

## What it costs

Everything runs on free tiers: **$0 paid**. Measured latencies, quotas and list-price equivalents
are in [COSTS.md](COSTS.md). The binding limits were Gemini TTS (10 requests per day per model) and
Kaggle GPU time (30 h/week), not money.

## The documents

| File | What is in it |
|---|---|
| [DESIGN.md](DESIGN.md) | audience, intent, why every shot exists, the two user tests and what they changed |
| [ARCHITECTURE.md](ARCHITECTURE.md) | stages, the storyboard contract, caching, failure handling |
| [EXPERIMENTS.md](EXPERIMENTS.md) | hypothesis → change → result for every experiment (voice, TTS prompting, one-take narration, pronunciation, FLUX seeds and references, skin-tone drift) |
| [FAILURES.md](FAILURES.md) | what broke, what I tried, what fixed it |
| [COSTS.md](COSTS.md) | latency, quotas and cost per stage |
| [ETHICS.md](ETHICS.md) | consent, licences of every model, labelling plan |

## Ethics in one paragraph

The film is about my father, who agreed to it and heard the narration before it was finished. He is
an illustrated character seen mostly from behind; no real face or voice of anyone is used, and the
narrator is a stock TTS voice. The film ends on a "Made with AI" card, and the post uses the
platform's AI label. Details in [ETHICS.md](ETHICS.md).
