# ETHICS.md

## 1. Consent

| Person | Appears how | Consent given | How recorded | Date |
|---|---|---|---|---|
| My father | Story told about him. Shown as an **illustrated, non-likeness** character, mostly from behind or in shadow. **His real face and voice are NOT used.** | Yes, verbally, to telling his story in this film and posting it publicly | *(to add: voice note / message saved privately, not in this repo)* | 24 Nov 2026 |
| Me (narrator) | Illustrated as a child and as an adult. Narration uses an AI TTS voice, not a clone of anyone | Self | n/a | 24 Nov 2026 |

- No voice cloning is used. The narrator is a stock Gemini TTS voice.
- The narration lines are words I wrote about my father. **He heard the full narration** (radio cut v1, 24 Nov 2026) and confirmed it verbally: he loved it and had no changes. If the narration changes after user test 1 (storyboard v2), he will hear the new lines again before the film is posted.
- Private details (full names, workplace name, address) are kept out of prompts sent to free APIs.

## 2. Labelling plan

- The film ends with a visible end card: "Made with AI".
- When posting, the platform's AI-content disclosure label is switched on. **Done:** posted publicly on TikTok on
  25 Nov 2026 with TikTok's AI-generated content setting on; the post shows "Creator labeled as AI-generated".
  The caption is kept minimal on purpose (no names, places or workplace) to protect my family's privacy.
- Provenance marks (SynthID / C2PA) left by any model are not removed.

## 3. Licences of models and outputs

*(Filled in as each model is chosen; each must be checked at the source.)*

| Stage | Model | Licence / terms | Output use |
|---|---|---|---|
| Narration | Gemini TTS | Gemini API terms (free tier may use inputs to improve products) | |
| Keyframes | FLUX on Cloudflare Workers AI | | |
| Moving shots | Wan 2.2 TI2V-5B | Apache 2.0 | |
| Music | ACE-Step 1.5 | MIT; outputs usable commercially | |
| Assembly | FFmpeg | LGPL/GPL (tool only) | n/a |
