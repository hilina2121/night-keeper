"""Runs ON KAGGLE (GPU T4 x2): animate keyframes with Wan 2.2 TI2V-5B (image-to-video).

Input dataset (/kaggle/input/<slug>/): jobs.json + the keyframe images it names.
Output (/kaggle/working/): clips/shot_XX_<hash>.mp4 and runs_kaggle.jsonl, one line per clip.

Each clip is written as soon as it is done, so a timeout or crash keeps the finished ones.
With 2 GPUs, jobs are split between two worker processes (one per GPU).

The local stage (pipeline/shots.py) builds jobs.json, pushes this script, and downloads the results.
"""
import glob
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

WORK = "/kaggle/working"
CLIPS = os.path.join(WORK, "clips")
LOG = os.path.join(WORK, "runs_kaggle.jsonl")
MODEL_ID = "Wan-AI/Wan2.2-TI2V-5B-Diffusers"


def log(rec):
    rec["ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with open(LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps(rec), flush=True)


def worker(gpu, jobs, input_dir):
    """Generate the given jobs on one GPU."""
    os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu)
    import torch
    from diffusers import AutoencoderKLWan, WanImageToVideoPipeline
    from diffusers.utils import export_to_video, load_image

    t0 = time.time()
    # T4 has no fast bfloat16, so the transformer runs in float16; the VAE stays in float32,
    # which the diffusers docs recommend to avoid colour/NaN problems in decoding.
    vae = AutoencoderKLWan.from_pretrained(MODEL_ID, subfolder="vae", torch_dtype=torch.float32)
    pipe = WanImageToVideoPipeline.from_pretrained(MODEL_ID, vae=vae, torch_dtype=torch.float16)
    pipe.enable_model_cpu_offload()  # 16 GB T4: keep only the active part of the model on the GPU
    load_s = time.time() - t0
    log({"stage": "shots:load", "gpu": gpu, "model": MODEL_ID, "latency_s": round(load_s, 1), "status": "ok"})

    for job in jobs:
        out = os.path.join(CLIPS, job["out"])
        if os.path.exists(out):
            continue
        rec = {"stage": "shots", "provider": "kaggle", "model": MODEL_ID, "shot": job["shot"],
               "hash": job["hash"], "seed": job["seed"], "gpu": f"T4#{gpu}",
               "params": {k: job[k] for k in ("prompt", "negative_prompt", "width", "height",
                                              "num_frames", "steps", "guidance", "fps")}}
        t1 = time.time()
        try:
            torch.cuda.reset_peak_memory_stats()
            image = load_image(os.path.join(input_dir, job["keyframe"])).resize((job["width"], job["height"]))
            frames = pipe(image=image, prompt=job["prompt"], negative_prompt=job["negative_prompt"],
                          height=job["height"], width=job["width"], num_frames=job["num_frames"],
                          num_inference_steps=job["steps"], guidance_scale=job["guidance"],
                          generator=torch.Generator("cpu").manual_seed(job["seed"])).frames[0]
            export_to_video(frames, out, fps=job["fps"])
            rec.update(status="ok", output=f"clips/{job['out']}",
                       peak_vram_gb=round(torch.cuda.max_memory_allocated() / 1e9, 2))
        except Exception as e:  # keep going: one failed shot must not cost the others
            rec.update(status="error", error=f"{type(e).__name__}: {e}"[:800])
            torch.cuda.empty_cache()
        rec["latency_s"] = round(time.time() - t1, 1)
        rec["gpu_minutes"] = round(rec["latency_s"] / 60, 2)
        log(rec)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        gpu, input_dir = int(sys.argv[2]), sys.argv[3]
        jobs = json.load(open(os.path.join(input_dir, "jobs.json")))["jobs"]
        mine = [j for i, j in enumerate(jobs) if i % int(sys.argv[4]) == gpu]
        worker(gpu, mine, input_dir)
        return

    t0 = time.time()
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U", "diffusers>=0.35", "transformers",
                    "accelerate", "ftfy", "imageio", "imageio-ffmpeg"], check=True)
    log({"stage": "shots:setup", "latency_s": round(time.time() - t0, 1), "status": "ok"})
    os.makedirs(CLIPS, exist_ok=True)
    input_dir = os.path.dirname(glob.glob("/kaggle/input/**/jobs.json", recursive=True)[0])
    jobs = json.load(open(os.path.join(input_dir, "jobs.json")))["jobs"]

    import torch
    n_gpu = max(1, min(torch.cuda.device_count(), len(jobs)))
    log({"stage": "shots:plan", "jobs": len(jobs), "gpus": torch.cuda.device_count(),
         "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None, "status": "ok"})
    # Download the weights once, before the workers start, so they do not race.
    from huggingface_hub import snapshot_download
    t1 = time.time()
    snapshot_download(MODEL_ID)
    log({"stage": "shots:download", "model": MODEL_ID, "latency_s": round(time.time() - t1, 1), "status": "ok"})

    # Only a script run has a file to re-launch. In an interactive notebook sys.argv[0] is
    # ipykernel_launcher.py, and re-launching that started kernels instead of workers (FAILURES F13).
    me = globals().get("__file__")
    if me and os.path.exists(me) and not me.endswith("ipykernel_launcher.py"):
        procs = [subprocess.Popen([sys.executable, me, "--worker", str(g), input_dir, str(n_gpu)])
                 for g in range(n_gpu)]
        for p in procs:
            p.wait()
    else:  # cannot re-launch this file: fall back to one GPU in this process
        log({"stage": "shots:plan", "note": "no script path; running on one GPU", "status": "ok"})
        worker(0, jobs, input_dir)
    log({"stage": "shots:done", "latency_s": round(time.time() - t0, 1), "status": "ok"})


if __name__ == "__main__":
    main()
