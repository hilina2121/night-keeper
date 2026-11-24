# DESIGN.md — *The Night Keeper*

> Written **before** generating any images, video or music (24 Nov 2026).
> This file records who the film is for, what it should do, why each shot exists,
> and what our two audience tests changed.

## 1. The story

**Logline:** My father guarded a mall at night so I could study by day, and one day I will rebuild his house.

**Treatment:** Every night my father worked as a building keeper at a mall in the city,
sitting through the night shift in his old coat. With that money he sent me to a good school.
Today I work at a good company and I can support him, but I am not yet where I want to be.
The film ends on a promise: one day I will rebuild his mud house.

## 2. Audience and intent

| Question | Answer |
|---|---|
| **Who watches?** | *(to confirm)* My family first, then young Ethiopian professionals and students who had parents sacrifice for their education |
| **Where?** | On a phone, vertical (TikTok / Instagram / YouTube Shorts), often with sound on low, so subtitles matter |
| **Language** | English narration, English burned-in subtitles |
| **What should they feel at the end?** | Grateful, and moved to call or thank their own parent |
| **What should they understand?** | That success is shared: my salary started with his night shifts |

**Design problem (define):** How might I make young people who "made it" feel the quiet cost their parents paid, in 75 seconds, without it feeling like a sad advert?

## 3. Narration draft v1 (before the first user test)

First draft was 10 lines / ~125 words. The smoke test seemed to measure Gemini TTS at ~1.65 words/s,
which put the draft near the 90 s limit, so I cut line 9 ("The house of the man who guarded
everyone else's"): it explained the ending instead of letting the picture do it.

**Correction after the radio cut:** the 1.65 words/s was wrong (the TTS was also reading my style
instruction aloud, FAILURES.md F7). The real rate is ~2.65 words/s: 110 words = **41.5 s of speech**,
and the first radio cut was only **56.9 s**, under the 60 s minimum. Instead of adding words I added
space: pauses between lines 0.6 s → 1.2 s, and longer holds on the emotional shots (1 city, 3 silent
coat, 7 coat on the wall, 9 mud house, 10 the promise). Radio cut v1 is now **65.8 s**.

1. Every night, while the city slept, my father kept watch over a mall that was not his.
2. He sat by the doors in his old coat, through the long night shift.
3. In the morning he came home tired, and still he made sure I went to school.
4. A good school. A school he could not afford, until he decided he could.
5. He never told me what it cost him. I learned it from his coat.
6. Today I work for a good company. I can help him now.
7. But I am not where I want to be. Not yet.
8. Because one day, I will rebuild his house.
9. Abba, this is my promise.

## 4. Shot plan v1, with a reason for every shot

The **coat** is the visual motif: it appears at work, at home, and at the end.

| # | Shot | Narration line | Size / camera | Why this shot exists |
|---|---|---|---|---|
| 1 | City at night, mall lights glowing | 1 | Extreme wide, slow push-in | Establishes place and time: the city sleeps, he doesn't |
| 2 | Father sitting by the mall doors in his coat, seen from behind | 2 | Wide, static | Introduces him without showing a real face; he looks small next to the building |
| 3 | Close-up of the worn coat sleeve and his hands | *(silent, music only)* | Close-up, gentle | The motif, and a breath after the opening |
| 4 | Sunrise, father walking home along a dusty road | 3 | Wide, slow pan | Morning after a full night; tiredness |
| 5 | Father and young child walking to a school gate | 4a "A good school." | Medium, from behind | The trade-off made visible: his night buys my day |
| 6 | Child in a classroom, writing | 4b | Medium close-up | What the money bought |
| 7 | Coat hanging on a nail inside the mud house | 5 | Insert, static | "He never told me what it cost him": the coat at rest |
| 8 | Me today, adult, at an office desk at dusk, looking out of the window | 6 + 7 | Medium, slow push-in | The payoff, but "not yet" |
| 9 | The mud house as it is today | 8 | Wide, static | Grounds the promise in a real place |
| 10 | The same house rebuilt, as a dream in warm light; the coat on the new door | 9 | Wide, slow push-in | The promise; the motif comes home |
| — | End card: "Made with AI" | Still, 3 s | Required disclosure |

**Style block (added to every image prompt):** warm hand-painted illustration, soft grain, muted earth tones with amber lamp light, gentle and dignified, no text in image.

**Consistency plan:** one character sheet for the father (always in the same long dark coat), one for me (child and adult), generated first; every keyframe conditioned on it.

## 5. User test 1: radio cut (narration + placeholder music, black screen)

Tested: `outputs/radio/radio_cut.mp4` (storyboard v1, 66.2 s, Sulafat voice, placeholder drone, burned-in subtitles).
Sent by message on 24 Nov; answers written down as they were given.

| Person (first name / role) | Date | What they said | Where they reacted |
|---|---|---|---|
| Dereje, friend | 24 Nov | "The story is inspiring, it has no confusing part except the pronunciation for abba looks like ai sound" | Did not like the continuity: "her sound change when she start new sentence" |
| Selam, coworker | 24 Nov | "Is the detail about the coat withheld intentionally?" | Line 7, "I learned it from his coat" |
| Dad (the father, the subject of the film) | 24 Nov | Loved it, no comment | Heard the full narration (recorded in ETHICS.md as his confirmation) |

**Insights:**
1. **The story lands.** Nobody was confused about what happened, and the person it is about approved it. The structure stays.
2. **"Abba" is mispronounced** (it sounds like "Ai-ba"). The last word of the film is the most important one to get right.
3. **The voice is not continuous.** Each line is a separate TTS call, so each line starts with a slightly different tone and energy. Listeners hear it as the narrator changing.
4. **The coat is a promise the film does not keep.** "I learned it from his coat" names the motif but never says *what* the coat showed, so it reads as missing information instead of a feeling.

**What I will change because of it (storyboard v1 → v2):**

| # | Feedback | Change | Status |
|---|---|---|---|
| 1 | "abba looks like ai sound" | Add a TTS-only spelling for the spoken text; subtitles keep "Abba". Test spellings with Whisper and by ear (EXPERIMENTS E4) | proposed |
| 2 | Voice changes between sentences | Generate the whole narration in **one** TTS take, then cut it into lines at the silences; compare with per-line (EXPERIMENTS E5) | proposed |
| 3 | Coat detail unclear | **Cut** "I learned it from his coat." Line 5 is now only "He never told me what it cost him." The sentence promised an explanation the film never gives; without it, the coat on the wall (shot 7) says it silently. The coat stays as the visual motif in shots 2, 3, 7 and 10. Decided by me on 24 Nov | **done** (storyboard shot 7) |

## 6. User test 2: near-final cut

*To do.*

| Person | Date | What they said | Where they reacted |
|---|---|---|---|
| | | | |
| | | | |
| | | | |

**What I changed because of it:**
