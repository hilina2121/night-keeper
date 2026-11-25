# The Night Keeper

A 60–90 second AI-made short film about my father, who guarded a mall at night so I could
go to a good school, and the house I promised to rebuild for him. It is narrated in English,
with an original score and English subtitles, in vertical (9:16) and horizontal (16:9).

**Watch it:** [vertical 9:16](https://drive.google.com/file/d/1XfwsgiS4b-XWgquNyZnju9QvFQvI-KG2/view?usp=sharing) · [horizontal 16:9](https://drive.google.com/file/d/1rz88OmCAmEffNUe2orM4qd9GCsfO-dPi/view?usp=sharing) (66.5 s, Google Drive)

This repository is the **studio that makes the film**: a pipeline that turns one file,
[`storyboard.json`](storyboard.json), into narration, keyframes, moving shots, music and a finished edit.
Change a line in the storyboard, run the pipeline again, and only what changed is regenerated.

> Status (25 Nov 2026): picture locked at storyboard v2. Narration, keyframes, the original ACE-Step score and the
> final edit in both aspect ratios are done. Wan 2.2 could not run on the free T4s (FAILURES F14), so every shot
> uses the brief's Ken Burns fallback; the stage still accepts clips if they are generated later.

## Quick start

Requirements: Python 3.11+ (tested on 3.14, Windows 11), [FFmpeg](https://ffmpeg.org/) on PATH, and free accounts at
[Google AI Studio](https://aistudio.google.com/apikey), [Cloudflare](https://dash.cloudflare.com/sign-up)
(Workers AI) [Kaggle](https://www.kaggle.com) (phone-verified for GPU) and [Hugging Face](https://huggingface.co/join).

```bash
git clone <this repo> && cd <repo>
pip install -r requirements.txt
cp .env.example .env          # then fill in the 6 values (see below)
python -m pipeline validate   # checks storyboard.json against schema/storyboard.schema.json
python -m pipeline all        # narration -> radio cut -> keyframes -> final film (only what is missing or changed)
```

| `.env` key | Where to get it |
|---|---|
| `GEMINI_API_KEY` | AI Studio → Get API key |
| `CLOUDFLARE_ACCOUNT_ID` | the long id in your dashboard URL |
| `CLOUDFLARE_API_TOKEN` | Workers AI → REST API → Create a Workers AI API Token |
| `KAGGLE_API_TOKEN` | kaggle.com/settings → API Tokens → Generate New Token |
| `KAGGLE_USERNAME` | your Kaggle username |
| `HF_TOKEN` | huggingface.co/settings/tokens → Create new token (Read); needed for the music stage |

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
| `python -m pipeline music-hf` | 3 score candidates per cue on a Hugging Face Space (Kaggle route: `music`); choose one by setting the cue's `chosen_seed` | ACE-Step | HF ZeroGPU |
| `python -m pipeline assemble` | Final edit in 9:16 and 16:9: Ken Burns or Wan clip per shot, score ducked under the voice, −14 LUFS, subtitles, AI end card | FFmpeg | laptop |

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

## How this was built

The code and the documents were drafted with a coding agent (Claude Code) under my direction. I chose the
story and the audience, ran both audience tests, made the creative choices (voice, characters, shots, music)
and reviewed what was written. The experiment and failure logs record what actually happened, including the
things that did not work.

## Ethics in one paragraph

The film is about my father, who agreed to it and heard the narration before it was finished. He is
an illustrated character seen mostly from behind; no real face or voice of anyone is used, and the
narrator is a stock TTS voice. The film ends on a "Made with AI" card, and the post uses the
platform's AI label. Details in [ETHICS.md](ETHICS.md).
