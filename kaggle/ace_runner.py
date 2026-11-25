"""Runs ON KAGGLE (GPU T4): score candidates with ACE-Step 1.5 (turbo DiT, no LM planner).

Input dataset (/kaggle/input/<slug>/music_jobs.json): one job per music cue, each with a caption,
bpm, key, duration and the seeds of the candidates to make.
Output (/kaggle/working/): music/<cue>_<hash>_s<seed>.wav and runs_kaggle.jsonl.

Choices, from the ACE-Step 1.5 docs (docs/en/INFERENCE.md):
- turbo DiT (`acestep-v15-turbo`), 8 steps, shift 3.0, ODE sampler; guidance is fixed to 1.0 for turbo;
- the 5 Hz LM "thinking" planner is OFF: it may rewrite the caption and choose its own bpm/key,
  and we want the spotting notes in storyboard.json to be what is played;
- instrumental=True (a score must leave room for the narrator);
- offload_to_cpu=True, recommended below 20 GB VRAM (a T4 has 16 GB).
Licence: code MIT; the model card says generated music may be used commercially.
"""
import glob
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

WORK = "/kaggle/working"
OUT = os.path.join(WORK, "music")
LOG = os.path.join(WORK, "runs_kaggle.jsonl")
REPO = "/kaggle/temp/ACE-Step-1.5"


def log(rec):
    rec["ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with open(LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps(rec), flush=True)


def setup():
    t0 = time.time()
    if not os.path.exists(REPO):
        subprocess.run(["git", "clone", "--depth", "1", "https://github.com/ACE-Step/ACE-Step-1.5.git", REPO], check=True)
        # --no-deps first would miss real requirements; a normal editable install keeps Kaggle's torch
        # if it already satisfies the pin.
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-e", REPO], check=True)
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    os.environ.setdefault("ACESTEP_INIT_LLM", "false")  # pure DiT mode: no LM planner
    log({"stage": "music:setup", "latency_s": round(time.time() - t0, 1), "status": "ok"})


def run_jobs():
    from acestep.handler import AceStepHandler
    from acestep.inference import GenerationConfig, GenerationParams, generate_music
    from acestep.llm_inference import LLMHandler

    os.makedirs(OUT, exist_ok=True)
    jobs = json.load(open(glob.glob("/kaggle/input/**/music_jobs.json", recursive=True)[0]))["jobs"]

    t0 = time.time()
    dit = AceStepHandler()
    status = dit.initialize_service(project_root=REPO, config_path="acestep-v15-turbo",
                                    device="cuda", offload_to_cpu=True)
    llm = LLMHandler()  # not initialised: thinking=False never calls it
    log({"stage": "music:load", "model": "ACE-Step/Ace-Step1.5 acestep-v15-turbo",
         "latency_s": round(time.time() - t0, 1), "status": "ok", "init": str(status)[:200]})

    for job in jobs:
        todo = [s for s in job["seeds"] if not glob.glob(os.path.join(OUT, f"{job['cue']}_{job['hash']}_s{s}.*"))]
        if not todo:
            continue
        params = GenerationParams(
            task_type="text2music", caption=job["caption"], lyrics="[Instrumental]", instrumental=True,
            bpm=job["bpm"], keyscale=job["key"], timesignature="", duration=job["duration"],
            inference_steps=8, shift=3.0, infer_method="ode", thinking=False,
            use_cot_metas=False, use_cot_caption=False, use_cot_language=False)
        config = GenerationConfig(batch_size=len(todo), seeds=todo, use_random_seed=False, audio_format="wav")
        rec = {"stage": "music", "provider": "kaggle", "model": "ACE-Step 1.5 turbo", "cue": job["cue"],
               "hash": job["hash"], "seeds": todo,
               "params": {k: job[k] for k in ("caption", "bpm", "key", "duration")}}
        t1 = time.time()
        try:
            tmp = os.path.join(OUT, "tmp_" + job["cue"])
            result = generate_music(dit, llm, params=params, config=config, save_dir=tmp)
            if not result.success:
                raise RuntimeError(str(result.error))
            outs = []
            for a in result.audios:
                seed = (a.get("params") or {}).get("seed", todo[len(outs)])
                ext = os.path.splitext(a["path"])[1]
                dst = os.path.join(OUT, f"{job['cue']}_{job['hash']}_s{seed}{ext}")
                os.replace(a["path"], dst)
                outs.append(os.path.basename(dst))
            rec.update(status="ok", outputs=outs,
                       time_costs=(result.extra_outputs or {}).get("time_costs"))
        except Exception as e:
            rec.update(status="error", error=f"{type(e).__name__}: {e}"[:800])
        rec["latency_s"] = round(time.time() - t1, 1)
        rec["gpu_minutes"] = round(rec["latency_s"] / 60, 2)
        log(rec)


setup()
run_jobs()
