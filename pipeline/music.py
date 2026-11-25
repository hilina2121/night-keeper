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


def cue_spans(sb: dict, model: str = MODEL) -> list[dict]:
    tl = timeline.build(sb, json.loads(MANIFEST.read_text(encoding="utf-8")))
    shots = {s["id"]: s for s in tl["shots"]}
    out = []
    for i, cue in enumerate(sb["music"]["cues"]):
        start = shots[cue["from_shot"]]["start"]
        last = i == len(sb["music"]["cues"]) - 1
        end = tl["total"] if last else shots[cue["to_shot"]]["start"] + shots[cue["to_shot"]]["duration"]
        dur = round(end - start + (0 if last else XFADE_S), 1)
        h = input_hash(model, cue["caption"], cue.get("bpm"), cue.get("key"), dur)
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
    jobs = cue_spans(sb, sb["music"].get("model", MODEL))
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


# ---------------------------------------------------------------- route 2: the official Hugging Face Space
HF_SPACE = "ACE-Step/Ace-Step-v1.5"
HF_MODEL = "acestep-v15-xl-turbo"  # the Space only initialises the 4B XL turbo DiT (F15)
AUDIO_EXT = (".flac", ".mp3", ".wav")


def _audio_paths(obj) -> list[str]:
    """Collect audio file paths from a Gradio result (nested tuples / dicts / strings)."""
    found: list[str] = []
    if isinstance(obj, str):
        if obj.lower().endswith(AUDIO_EXT) and Path(obj).exists():
            found.append(obj)
    elif isinstance(obj, dict):
        for k in ("path", "value", "name"):
            found += _audio_paths(obj.get(k))
    elif isinstance(obj, (list, tuple)):
        for x in obj:
            found += _audio_paths(x)
    return list(dict.fromkeys(found))


def run_hf_v15() -> None:
    """Same jobs as `music`, run on the official ACE-Step 1.5 Space (ZeroGPU A10G) via gradio_client.

    Used because Kaggle's GPU queue was unusable on 25 Nov (FAILURES F11, F13, F15).
    LM planner ("Thinking") and its chain-of-thought rewrites are turned off so the caption, bpm and
    key from the storyboard are what is played; instrumental via the "[Instrumental]" lyrics tag.
    """
    import time
    from gradio_client import Client
    from pipeline.common import log_call

    sb = load()
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    client = None
    for job in cue_spans(sb):
        todo = [s for s in job["seeds"] if not candidate(job, s)]
        print(f"  cue {job['cue']:<8} {job['duration']:5.1f}s  {job['bpm']} bpm {job['key']:<8} "
              f"seeds {job['seeds']}  {'QUEUED' if todo else 'cached'}")
        if not todo:
            continue
        import os
        load_env()
        client = client or Client(HF_SPACE, verbose=False, token=os.environ.get("HF_TOKEN") or None)
        params = dict(selected_model=HF_MODEL, generation_mode="custom", param_4=job["caption"],
                      param_5="[Instrumental]", param_6=job["bpm"] or 0, param_7=job["key"] or "",
                      param_8="", param_10=8, param_12=False, param_13=",".join(str(s) for s in todo),
                      param_15=job["duration"], param_16=len(todo), param_27=3.0, param_28="ode",
                      param_30="flac", param_32=False, param_37=False, param_38=False, param_39=False)
        # The Space requires every argument: start from its own defaults, then override ours.
        spec = client.view_api(print_info=False, return_format="dict")["named_endpoints"]["/generation_wrapper"]
        full = {}
        for p in spec["parameters"]:
            name, default = p["parameter_name"], p.get("parameter_default")
            if default is None and p.get("component") in ("Textbox", "Dropdown"):
                default = "" if p.get("component") == "Textbox" else None
            full[name] = default
        full["simple_query_input"] = ""
        full.update(params)  # unused audio inputs (reference / source audio) stay None
        t0 = time.perf_counter()
        try:
            res = client.predict(api_name="/generation_wrapper", **full)
            paths = _audio_paths(res)[:len(todo)]
            if not paths:
                raise RuntimeError(f"no audio in result: {str(res)[:300]}")
            outs = []
            for seed, p in zip(todo, paths):
                dst = MUSIC_DIR / f"{job['cue']}_{job['hash']}_s{seed}{Path(p).suffix}"
                shutil.copy(p, dst)
                outs.append(dst.relative_to(ROOT).as_posix())
            log_call(stage="music", provider="huggingface-space", model=f"{HF_SPACE}:{HF_MODEL}",
                     params={k: v for k, v in params.items()}, seed=todo[0],
                     latency_s=time.perf_counter() - t0, status="ok", output=outs, cue=job["cue"])
            for o in outs:
                print(f"    -> {o}")
        except Exception as e:
            log_call(stage="music", provider="huggingface-space", model=f"{HF_SPACE}:{HF_MODEL}",
                     params=params, latency_s=time.perf_counter() - t0, status="error",
                     error=f"{type(e).__name__}: {e}"[:800], cue=job["cue"])
            print(f"    FAILED: {type(e).__name__}: {str(e)[:300]}")


# ---------------------------------------------------------------- route 3: ACE-Step v1 Space (works)
V1_SPACE = "victor/ace-step-jam"  # official Spaces both broken on 25 Nov (F15, F16); MIT
V1_MODEL = "ACE-Step via victor/ace-step-jam"


def run_hf(only_one: bool = False) -> None:
    """Score candidates on the ACE-Step v1 Space (ZeroGPU A10G, Apache 2.0), one call per seed.

    The 1.5 Space could not load its own model on 25 Nov (FAILURES F15), so the film's score comes
    from ACE-Step v1, the same team's previous open model. v1 has no bpm/key fields: they are
    written into the tags. "[instrumental]" keeps vocals out.
    """
    import os
    import time
    from gradio_client import Client
    from pipeline.common import log_call

    load_env()
    sb = load()
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    client = None
    for job in cue_spans(sb, V1_MODEL):
        for seed in job["seeds"]:
            if candidate(job, seed):
                print(f"  cue {job['cue']:<8} seed {seed}: cached")
                continue
            client = client or Client(V1_SPACE, verbose=False, token=os.environ.get("HF_TOKEN") or None)
            tags = f"{job['caption']}, {job['bpm']} bpm, {job['key']}"
            params = dict(prompt=tags, lyrics="[instrumental]", audio_duration=job["duration"],
                          infer_step=8, guidance_scale=7.0, seed=seed, lora_name_or_path="", lora_weight=0.8)
            print(f"  cue {job['cue']:<8} seed {seed}: GENERATING {job['duration']}s")
            t0 = time.perf_counter()
            try:
                res = client.predict(api_name="/generate", **params)
                data_uri = next((x for x in (res if isinstance(res, (list, tuple)) else [res])
                                 if isinstance(x, str) and x.startswith("data:audio")), None)
                if data_uri:  # this Space returns the audio inline as a base64 data URI
                    import base64
                    head, b64 = data_uri.split(",", 1)
                    ext = ".wav" if "wav" in head else ".mp3" if "mpeg" in head or "mp3" in head else ".flac"
                    dst = MUSIC_DIR / f"{job['cue']}_{job['hash']}_s{seed}{ext}"
                    dst.write_bytes(base64.b64decode(b64))
                else:
                    paths = _audio_paths(res)
                    if not paths:
                        raise RuntimeError(f"no audio in result: {str(res)[:300]}")
                    dst = MUSIC_DIR / f"{job['cue']}_{job['hash']}_s{seed}{Path(paths[0]).suffix}"
                    shutil.copy(paths[0], dst)
                log_call(stage="music", provider="huggingface-space", model=f"{V1_SPACE}", params=params,
                         seed=seed, latency_s=time.perf_counter() - t0, status="ok",
                         output=dst.relative_to(ROOT).as_posix(), cue=job["cue"])
                print(f"    -> {dst.relative_to(ROOT).as_posix()}  ({time.perf_counter() - t0:.0f}s)")
            except Exception as e:
                log_call(stage="music", provider="huggingface-space", model=f"{V1_SPACE}", params=params,
                         seed=seed, latency_s=time.perf_counter() - t0, status="error",
                         error=f"{type(e).__name__}: {e}"[:800], cue=job["cue"])
                print(f"    FAILED: {type(e).__name__}: {str(e)[:300]}")
                return
            if only_one:
                return
