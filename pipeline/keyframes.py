"""Stage: reference sheet + keyframes (FLUX.2 klein 4B on Cloudflare Workers AI).

    python -m pipeline refs        4 candidate reference images per character (you pick one)
    python -m pipeline keyframes   one keyframe per shot, conditioned on the chosen references

Consistency: every prompt = shot prompt + the character sheet description + the style block,
and the approved reference image of each character in the shot is sent as an input image.

Caching: each image's file name contains a hash of everything that changes it (model, prompt,
size, seed, and the bytes of the reference images). The seed is NOT reproducible on this
endpoint (EXPERIMENTS E7), so the cache is what makes a re-run reproducible: an unchanged
shot is never regenerated. Change one image_prompt and only that shot calls the API.

Size: 1024x1024 with the subject centred (style block), so the assembly stage can crop the
same keyframe to both 9:16 and 16:9.
"""
from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import time
from pathlib import Path

from pipeline.common import OUTPUTS, ROOT, HttpError, http_multipart, load_env, log_call, require
from pipeline.storyboard import input_hash, load

MODEL = "@cf/black-forest-labs/flux-2-klein-4b"
SIZE = 1024
REF_DIR = OUTPUTS / "refs"
KF_DIR = OUTPUTS / "keyframes"
N_REF_CANDIDATES = 4

# How each character is posed on its reference sheet. The father's face stays in shadow:
# he is illustrated, not a likeness (ETHICS.md).
REF_POSE = {
    "father": "full body, standing, seen from the side and three-quarter back, face turned away in soft shadow",
}
DEFAULT_POSE = "full body, standing, front view, calm gentle expression"


def file_hash(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:10]


def flux(prompt: str, seed: int, out: Path, refs: list[Path], stage: str, **extra) -> Path:
    account, token = require("CLOUDFLARE_ACCOUNT_ID"), require("CLOUDFLARE_API_TOKEN")
    fields = {"prompt": prompt, "width": str(SIZE), "height": str(SIZE), "seed": str(seed)}
    files = {f"input_image_{i}": r for i, r in enumerate(refs)}
    t0 = time.perf_counter()
    try:
        data, attempts = http_multipart(
            f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{MODEL}",
            fields=fields, files=files, headers={"Authorization": f"Bearer {token}"})
    except HttpError as e:
        log_call(stage=stage, provider="cloudflare", model=MODEL, params=fields, seed=seed,
                 latency_s=time.perf_counter() - t0, status="error",
                 attempts=getattr(e, "attempts", 1), error=str(e), **extra)
        raise
    img = base64.b64decode(data["result"]["image"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(img)
    log_call(stage=stage, provider="cloudflare", model=MODEL, params=fields, seed=seed,
             latency_s=time.perf_counter() - t0, status="ok", attempts=attempts,
             output=out.relative_to(ROOT).as_posix(), cost_usd=0.0,
             ref_images=[r.relative_to(ROOT).as_posix() for r in refs], **extra)
    return out


def contact_sheet(images: list[Path], out: Path, cols: int = 4, tile: int = 320) -> None:
    """One JPEG with all images side by side, for reviewing."""
    if not images:
        return
    pads = images + [images[-1]] * ((-len(images)) % cols)  # fill the last row
    ins, chains = [], []
    for i, p in enumerate(pads):
        ins += ["-i", str(p)]
        chains.append(f"[{i}]scale={tile}:{tile}[t{i}]")
    rows = [f"{''.join(f'[t{r * cols + c}]' for c in range(cols))}hstack={cols}[r{r}]"
            for r in range(len(pads) // cols)]
    n_rows = len(pads) // cols
    stack = "".join(f"[r{r}]" for r in range(n_rows)) + (f"vstack={n_rows}" if n_rows > 1 else "copy")
    subprocess.run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex",
                    ";".join(chains + rows) + ";" + stack, str(out)], check=True)


# ---------------------------------------------------------------- reference sheet

def ref_prompt(sb: dict, name: str) -> str:
    desc = sb["characters"][name]["description"]
    return (f"character reference sheet: {desc}. {REF_POSE.get(name, DEFAULT_POSE)}. "
            f"Plain warm beige background, even soft light. {sb['style_block']}")


def run_refs(only: str | None = None) -> None:
    load_env()
    sb = load()
    for name, ch in sb["characters"].items():
        if only and name != only:
            continue
        approved = ch.get("reference_image")
        if approved and (ROOT / approved).exists():
            print(f"  {name}: approved -> {approved}")
            continue
        prompt = ref_prompt(sb, name)
        cands = []
        for seed in range(1, N_REF_CANDIDATES + 1):
            out = REF_DIR / name / f"cand{seed}_{input_hash(MODEL, prompt, SIZE, seed)}.jpg"
            if out.exists():
                print(f"  {name} cand{seed}: cached")
            else:
                print(f"  {name} cand{seed}: GENERATING")
                flux(prompt, seed, out, [], stage="refs", character=name)
            cands.append(out)
        sheet = REF_DIR / f"{name}_candidates.jpg"
        contact_sheet(cands, sheet, cols=N_REF_CANDIDATES)
        print(f"  {name}: pick one of {sheet.relative_to(ROOT).as_posix()} (1-{N_REF_CANDIDATES}, left to right)")


# ---------------------------------------------------------------- keyframes

def shot_prompt(sb: dict, shot: dict) -> str:
    who = " ".join(f"The {c.replace('_', ' ')} is {sb['characters'][c]['description']}."
                   for c in shot.get("characters", []))
    keep = " Keep each person exactly as in the reference image(s)." if shot.get("characters") else ""
    return f"{shot['image_prompt']}. {who}{keep} {shot['size']} shot. {sb['style_block']}"


def run(only_shot: int | None = None) -> dict:
    load_env()
    sb = load()
    missing = [c for c, ch in sb["characters"].items()
               if not (ch.get("reference_image") and (ROOT / ch["reference_image"]).exists())]
    used = {c for s in sb["shots"] for c in s.get("characters", [])}
    if used & set(missing):
        raise SystemExit(f"No approved reference image for: {', '.join(sorted(used & set(missing)))}. "
                         "Run `python -m pipeline refs` and set characters.<name>.reference_image.")
    manifest, new_calls, images = {}, 0, []
    for shot in sb["shots"]:
        sid = shot["id"]
        refs = [ROOT / sb["characters"][c]["reference_image"] for c in shot.get("characters", [])]
        prompt = shot_prompt(sb, shot)
        h = input_hash(MODEL, prompt, SIZE, shot["seed"], [file_hash(r) for r in refs])
        out = KF_DIR / f"shot_{sid:02d}_{h}.jpg"
        if out.exists():
            print(f"  shot {sid:02d}: cached  ({out.name})")
        elif only_shot is not None and sid != only_shot:
            print(f"  shot {sid:02d}: changed but skipped (--shot {only_shot})")
            continue
        else:
            print(f"  shot {sid:02d}: GENERATING -> {out.name}")
            flux(prompt, shot["seed"], out, refs, stage="keyframes", shot=sid)
            new_calls += 1
        manifest[str(sid)] = {"file": out.relative_to(ROOT).as_posix(), "hash": h, "prompt": prompt,
                              "refs": [r.relative_to(ROOT).as_posix() for r in refs]}
        images.append(out)
    KF_DIR.mkdir(parents=True, exist_ok=True)
    (KF_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    contact_sheet(images, KF_DIR / "contact_sheet.jpg", cols=5)
    print(f"  keyframes: {new_calls} new image(s); review outputs/keyframes/contact_sheet.jpg")
    return manifest
