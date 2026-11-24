"""Stage: moving shots (Wan 2.2 TI2V-5B image-to-video on a Kaggle GPU).

    python -m pipeline shots                 build jobs for shots without a clip, upload, start the Kaggle run
    python -m pipeline shots --shot 4        only that shot (e.g. a first test)
    python -m pipeline shots-status          is the Kaggle run still going?
    python -m pipeline shots-fetch           download finished clips + their log lines into runs.jsonl

Caching: a clip's name is shot_XX_<hash>.mp4, hash = (model, keyframe image bytes, motion prompt,
generation settings). A shot is only sent to Kaggle when no clip with its current hash exists,
so changing one keyframe or one motion prompt re-animates only that shot.

Shots without a clip are not an error: the assembly stage animates the keyframe with a slow
pan-and-zoom instead (the brief's fallback).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from pipeline.common import OUTPUTS, ROOT, RUNS_LOG, load_env, require
from pipeline.keyframes import file_hash
from pipeline.storyboard import input_hash, load

MODEL_ID = "Wan-AI/Wan2.2-TI2V-5B-Diffusers"
SHOTS_DIR = OUTPUTS / "shots"
KAGGLE_DIR = OUTPUTS / "kaggle"
DATASET_SLUG = "night-keeper-wan-input"
KERNEL_SLUG = "night-keeper-wan"
RUNNER = ROOT / "kaggle" / "wan_runner.py"

# Draft settings (the brief: draft low, finish only what is chosen). 640x640 is a multiple of 32
# as the 5B VAE needs; 97 frames = 4 s at 24 fps (Wan needs 4k+1 frames).
SETTINGS = {"width": 640, "height": 640, "num_frames": 97, "fps": 24, "steps": 30, "guidance": 5.0}
STYLE_SUFFIX = "warm hand-painted illustration, gentle slow natural motion, stable camera"
NEGATIVE = ("blurry, distorted, morphing face, deformed hands, extra limbs, flicker, jitter, "
            "fast motion, text, watermark, logo")


def kaggle(*args: str, check: bool = True) -> str:
    """Run the Kaggle CLI with the token from .env (never printed)."""
    load_env()
    env = {**os.environ, "KAGGLE_API_TOKEN": require("KAGGLE_API_TOKEN")}
    exe = shutil.which("kaggle") or str(Path(os.environ["APPDATA"]) / "Python" / "Python314" / "Scripts" / "kaggle.exe")
    # utf-8 + replace: on Windows the CLI's progress bars broke the default cp1252 decoding (FAILURES F10)
    res = subprocess.run([exe, *args], capture_output=True, text=True, env=env,
                         encoding="utf-8", errors="replace")
    out = ((res.stdout or "") + (res.stderr or "")).strip()
    if check and res.returncode != 0:
        raise SystemExit(f"kaggle {' '.join(args)} failed:\n{out}")
    return out


def plan(sb: dict) -> list[dict]:
    kf = json.loads((OUTPUTS / "keyframes" / "manifest.json").read_text(encoding="utf-8"))
    jobs = []
    for shot in sb["shots"]:
        sid = shot["id"]
        img = ROOT / kf[str(sid)]["file"]
        prompt = f"{shot['motion_prompt']}, {STYLE_SUFFIX}"
        h = input_hash(MODEL_ID, file_hash(img), prompt, NEGATIVE, shot["seed"], SETTINGS)
        jobs.append({"shot": sid, "hash": h, "keyframe": img.name, "keyframe_path": img,
                     "prompt": prompt, "negative_prompt": NEGATIVE, "seed": shot["seed"],
                     "out": f"shot_{sid:02d}_{h}.mp4", **SETTINGS})
    return jobs


def run(only_shot: int | None = None) -> None:
    load_env()
    user = require("KAGGLE_USERNAME")
    sb = load()
    todo = []
    for j in plan(sb):
        if (SHOTS_DIR / j["out"]).exists():
            print(f"  shot {j['shot']:02d}: cached  ({j['out']})")
        elif only_shot is not None and j["shot"] != only_shot:
            print(f"  shot {j['shot']:02d}: needs a clip, skipped (--shot {only_shot})")
        else:
            print(f"  shot {j['shot']:02d}: QUEUED  ({j['out']})")
            todo.append(j)
    if not todo:
        print("  shots: nothing to do")
        return

    # 1. Dataset with the job list and the keyframes it needs.
    ds = KAGGLE_DIR / "input"
    shutil.rmtree(ds, ignore_errors=True)
    ds.mkdir(parents=True)
    for j in todo:
        shutil.copy(j.pop("keyframe_path"), ds / j["keyframe"])
    (ds / "jobs.json").write_text(json.dumps({"jobs": todo}, indent=2), encoding="utf-8")
    (ds / "dataset-metadata.json").write_text(json.dumps(
        {"title": "Night Keeper Wan input", "id": f"{user}/{DATASET_SLUG}", "licenses": [{"name": "other"}]}),
        encoding="utf-8")
    ref = f"{user}/{DATASET_SLUG}"
    if "ready" in kaggle("datasets", "status", ref, check=False).lower():
        print("  uploading new dataset version...")
        print("  " + kaggle("datasets", "version", "-p", str(ds), "-m", f"{len(todo)} job(s)", "-r", "zip"))
    else:
        print("  creating private dataset...")
        print("  " + kaggle("datasets", "create", "-p", str(ds), "-r", "zip"))
    # The kernel can only mount the dataset once Kaggle has processed the upload.
    for _ in range(36):
        time.sleep(5)
        if "ready" in kaggle("datasets", "status", ref, check=False).lower():
            break
    else:
        raise SystemExit("dataset still not ready after 3 minutes; run `python -m pipeline shots` again")

    # 2. Script kernel that runs wan_runner.py on GPU T4 x2 with internet (to download the model).
    kd = KAGGLE_DIR / "kernel"
    shutil.rmtree(kd, ignore_errors=True)
    kd.mkdir(parents=True)
    shutil.copy(RUNNER, kd / "wan_runner.py")
    (kd / "kernel-metadata.json").write_text(json.dumps({
        "id": f"{user}/{KERNEL_SLUG}", "title": "night-keeper-wan", "code_file": "wan_runner.py",
        "language": "python", "kernel_type": "script", "is_private": True,
        "enable_gpu": True, "enable_internet": True,
        "dataset_sources": [f"{user}/{DATASET_SLUG}"], "competition_sources": [], "kernel_sources": []},
        indent=2), encoding="utf-8")
    print("  pushing kernel and starting the run (GPU T4 x2)...")
    print("  " + kaggle("kernels", "push", "-p", str(kd), "--accelerator", "NvidiaTeslaT4"))
    print("  started. Check with: python -m pipeline shots-status")


def status() -> str:
    load_env()
    user = require("KAGGLE_USERNAME")
    out = kaggle("kernels", "status", f"{user}/{KERNEL_SLUG}", check=False)
    print("  " + out)
    return out


def fetch() -> None:
    load_env()
    user = require("KAGGLE_USERNAME")
    dl = KAGGLE_DIR / "output"
    shutil.rmtree(dl, ignore_errors=True)
    dl.mkdir(parents=True)
    print("  " + kaggle("kernels", "output", f"{user}/{KERNEL_SLUG}", "-p", str(dl), check=False)[-300:])
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    got = 0
    for clip in dl.rglob("shot_*.mp4"):
        dst = SHOTS_DIR / clip.name
        if not dst.exists():
            shutil.copy(clip, dst)
            got += 1
    # Merge the remote log into runs.jsonl once (skip lines already merged).
    remote = next(dl.rglob("runs_kaggle.jsonl"), None)
    merged = 0
    if remote:
        seen = RUNS_LOG.read_text(encoding="utf-8") if RUNS_LOG.exists() else ""
        with RUNS_LOG.open("a", encoding="utf-8") as f:
            for line in remote.read_text(encoding="utf-8").splitlines():
                rec = json.loads(line)
                rec.setdefault("provider", "kaggle")
                key = f'"ts": "{rec["ts"]}", "stage": "{rec["stage"]}"'
                if key not in seen:
                    f.write(json.dumps({"ts": rec.pop("ts"), "stage": rec.pop("stage"), **rec}) + "\n")
                    merged += 1
        for line in remote.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec.get("stage") == "shots":
                print(f"  shot {rec['shot']:02d}: {rec['status']:<5} {rec.get('latency_s', 0):7.1f}s"
                      f"  {rec.get('peak_vram_gb', '-')} GB  {rec.get('error', '')[:120]}")
    print(f"  shots: {got} new clip(s) in outputs/shots, {merged} log line(s) merged into runs.jsonl")
