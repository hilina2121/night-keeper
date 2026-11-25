"""Stage: music (ACE-Step 1.5 on a Kaggle GPU) and the score built from the chosen candidates.

    python -m pipeline music                   upload one job per cue (3 candidates each) and push the Kaggle notebook
    python -m pipeline music-import <folder>   copy candidates downloaded from Kaggle into outputs/music, merge logs
    python -m pipeline music-score             join the chosen candidate of each cue into one score (crossfade)

Spotting: each cue in storyboard.json covers a range of shots. Its duration comes from the timeline
(which the narration sets), plus an overlap for the crossfade into the next cue. Choose a candidate
by setting that cue's "chosen_seed"; the assembly stage then uses the joined score instead of the
placeholder drone.

Caching: a candidate is named <cue>_<hash>_s<seed>.wav, hash = (caption, bpm, key, duration, model).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from pipeline import timeline
from pipeline.common import OUTPUTS, ROOT, RUNS_LOG, load_env, require
from pipeline.narration import MANIFEST
from pipeline.storyboard import input_hash, load

MODEL = "ACE-Step 1.5 turbo"
MUSIC_DIR = OUTPUTS / "music"
DATASET_SLUG = "night-keeper-music-input"
KERNEL_SLUG = "night-keeper-music"
RUNNER = ROOT / "kaggle" / "ace_runner.py"
N_CANDIDATES = 3
XFADE_S = 3.0


def cue_spans(sb: dict) -> list[dict]:
    tl = timeline.build(sb, json.loads(MANIFEST.read_text(encoding="utf-8")))
    shots = {s["id"]: s for s in tl["shots"]}
    out = []
    for i, cue in enumerate(sb["music"]["cues"]):
        start = shots[cue["from_shot"]]["start"]
        last = i == len(sb["music"]["cues"]) - 1
        end = tl["total"] if last else shots[cue["to_shot"]]["start"] + shots[cue["to_shot"]]["duration"]
        dur = round(end - start + (0 if last else XFADE_S), 1)
        h = input_hash(MODEL, cue["caption"], cue.get("bpm"), cue.get("key"), dur)
        seeds = [300 + 10 * i + k for k in range(N_CANDIDATES)]
        out.append({"cue": cue["id"], "hash": h, "start": start, "duration": dur, "caption": cue["caption"],
                    "bpm": cue.get("bpm"), "key": cue.get("key", ""), "seeds": seeds,
                    "chosen_seed": cue.get("chosen_seed")})
    return out


def candidate(job: dict, seed: int) -> Path | None:
    hits = sorted(MUSIC_DIR.glob(f"{job['cue']}_{job['hash']}_s{seed}.*"))
    return hits[0] if hits else None


def run() -> None:
    from pipeline.shots import kaggle  # same CLI wrapper (token from .env, utf-8 output)
    load_env()
    user = require("KAGGLE_USERNAME")
    sb = load()
    jobs = [j for j in cue_spans(sb) if not all(candidate(j, s) for s in j["seeds"])]
    for j in cue_spans(sb):
        state = "QUEUED" if j in jobs else "cached"
        print(f"  cue {j['cue']:<8} {j['duration']:5.1f}s  {j['bpm']} bpm {j['key']:<8} seeds {j['seeds']}  {state}")
    if not jobs:
        print("  music: all candidates exist")
        return
    ds = OUTPUTS / "kaggle" / "music_input"
    shutil.rmtree(ds, ignore_errors=True)
    ds.mkdir(parents=True)
    (ds / "music_jobs.json").write_text(json.dumps({"jobs": jobs}, indent=2), encoding="utf-8")
    (ds / "dataset-metadata.json").write_text(json.dumps(
        {"title": "Night Keeper music input", "id": f"{user}/{DATASET_SLUG}", "licenses": [{"name": "other"}]}),
        encoding="utf-8")
    ref = f"{user}/{DATASET_SLUG}"
    if "ready" in kaggle("datasets", "status", ref, check=False).lower():
        print("  " + kaggle("datasets", "version", "-p", str(ds), "-m", f"{len(jobs)} cue(s)")[-200:])
    else:
        print("  " + kaggle("datasets", "create", "-p", str(ds))[-200:])

    kd = OUTPUTS / "kaggle" / "music_kernel"
    shutil.rmtree(kd, ignore_errors=True)
    kd.mkdir(parents=True)
    shutil.copy(RUNNER, kd / "ace_runner.py")
    (kd / "kernel-metadata.json").write_text(json.dumps({
        "id": f"{user}/{KERNEL_SLUG}", "title": KERNEL_SLUG, "code_file": "ace_runner.py",
        "language": "python", "kernel_type": "script", "is_private": True,
        "enable_gpu": True, "enable_internet": True, "dataset_sources": [ref],
        "competition_sources": [], "kernel_sources": []}, indent=2), encoding="utf-8")
    # --no-run: API-started GPU runs sat in the queue for 10+ hours (FAILURES F11). The notebook is
    # created here and started by hand in the Kaggle editor, where the queue actually moves.
    print("  " + kaggle("kernels", "push", "-p", str(kd), "--no-run"))
    print(f"  open https://www.kaggle.com/code/{user}/{KERNEL_SLUG} -> Edit -> GPU T4 x2 + Internet on -> Run All")


def import_outputs(folder: str) -> None:
    """Copy candidates (and any Wan clips) from a folder downloaded from Kaggle, merge its log lines."""
    src = Path(folder)
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    got = 0
    for f in list(src.rglob("*.wav")) + list(src.rglob("*.flac")) + list(src.rglob("*.mp3")):
        if "_s" in f.stem and not (MUSIC_DIR / f.name).exists():
            shutil.copy(f, MUSIC_DIR / f.name)
            got += 1
    from pipeline.shots import SHOTS_DIR
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    for f in src.rglob("shot_*.mp4"):
        if not (SHOTS_DIR / f.name).exists():
            shutil.copy(f, SHOTS_DIR / f.name)
            got += 1
    merged = merge_logs(src)
    print(f"  imported {got} file(s), merged {merged} log line(s) into runs.jsonl")


def merge_logs(src: Path) -> int:
    seen = RUNS_LOG.read_text(encoding="utf-8") if RUNS_LOG.exists() else ""
    merged = 0
    with RUNS_LOG.open("a", encoding="utf-8") as out:
        for logf in src.rglob("runs_kaggle.jsonl"):
            for line in logf.read_text(encoding="utf-8").splitlines():
                rec = json.loads(line)
                key = f'"ts": "{rec["ts"]}", "stage": "{rec["stage"]}"'
                if key in seen:
                    continue
                rec.setdefault("provider", "kaggle")
                out.write(json.dumps({"ts": rec.pop("ts"), "stage": rec.pop("stage"), **rec}) + "\n")
                seen += key
                merged += 1
    return merged


def score_path(sb: dict) -> Path | None:
    """The joined score for the chosen candidates, or None if a cue has no choice yet."""
    jobs = cue_spans(sb)
    picks = [candidate(j, j["chosen_seed"]) if j["chosen_seed"] is not None else None for j in jobs]
    if not all(picks):
        return None
    h = input_hash("score", [p.name for p in picks], [j["start"] for j in jobs], XFADE_S)
    out = MUSIC_DIR / f"score_{h}.wav"
    if out.exists():
        return out
    # Each cue starts at its shot; consecutive cues overlap by XFADE_S and crossfade.
    args, chain = [], ""
    for i, p in enumerate(picks):
        args += ["-i", str(p)]
    chain = "[0:a]aresample=48000,aformat=channel_layouts=stereo[c0]"
    prev = "c0"
    for i in range(1, len(picks)):
        chain += (f";[{i}:a]aresample=48000,aformat=channel_layouts=stereo[r{i}]"
                  f";[{prev}][r{i}]acrossfade=d={XFADE_S}:c1=tri:c2=tri[c{i}]")
        prev = f"c{i}"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args, "-filter_complex", chain,
                    "-map", f"[{prev}]", str(out)], check=True)
    print(f"  score: {out.relative_to(ROOT).as_posix()} from {', '.join(p.name for p in picks)}")
    return out
