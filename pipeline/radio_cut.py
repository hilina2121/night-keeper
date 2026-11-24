"""Stage: radio cut (the audio animatic).

Narration over placeholder music on a black screen, with burned-in subtitles,
ducking and loudness normalisation. Used for user test 1, before any pictures exist.

Output: outputs/radio/radio_cut.mp4 (9:16) + radio_cut.srt + timeline.json
"""
from __future__ import annotations

import json
import subprocess
import time

from pipeline.common import OUTPUTS, ROOT, log_call
from pipeline.narration import MANIFEST
from pipeline.storyboard import load
from pipeline import timeline

OUT_DIR = OUTPUTS / "radio"

# Placeholder score: a soft A-minor drone that swells slowly. Real score comes from ACE-Step later.
PLACEHOLDER = ("0.10*sin(2*PI*110*t)+0.08*sin(2*PI*164.81*t)+0.06*sin(2*PI*220*t)"
               "+0.04*sin(2*PI*261.63*t)*(0.5+0.5*sin(2*PI*0.07*t))")


def run() -> None:
    sb = load()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    tl = timeline.build(sb, manifest)
    total = tl["total"]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "timeline.json").write_text(json.dumps(tl, indent=2, ensure_ascii=False), encoding="utf-8")
    srt_path = OUT_DIR / "radio_cut.srt"
    srt_path.write_text(timeline.srt(tl), encoding="utf-8")

    voiced = [s for s in tl["shots"] if s["voice_file"]]
    duck = sb["music"].get("duck", {})
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for s in voiced:
        cmd += ["-i", s["voice_file"]]

    graph = []
    for i, s in enumerate(voiced):
        ms = int(s["voice_start"] * 1000)
        graph.append(f"[{i}:a]aresample=48000,adelay={ms}:all=1[v{i}]")
    graph.append("".join(f"[v{i}]" for i in range(len(voiced)))
                 + f"amix=inputs={len(voiced)}:normalize=0:duration=longest,"
                   f"apad=whole_dur={total},aformat=channel_layouts=stereo,asplit=2[voice][key]")
    graph.append(f"aevalsrc='{PLACEHOLDER}':s=48000:d={total},lowpass=f=900,"
                 f"afade=t=in:d=2,afade=t=out:st={total - 3}:d=3,aformat=channel_layouts=stereo,volume=0.6[mus]")
    graph.append(f"[mus][key]sidechaincompress=threshold={duck.get('threshold', 0.02)}"
                 f":ratio={duck.get('ratio', 6)}:attack={duck.get('attack_ms', 300)}"
                 f":release={duck.get('release_ms', 1500)}[ducked]")
    graph.append("[ducked][voice]amix=inputs=2:normalize=0,loudnorm=I=-14:TP=-1:LRA=11,aresample=48000[a]")
    sub = srt_path.relative_to(ROOT).as_posix()
    graph.append(f"color=c=black:s=1080x1920:r=24:d={total},"
                 f"subtitles={sub}:force_style='FontName=Arial,FontSize=10,Alignment=2,MarginV=90,Outline=1'[v]")

    out = OUT_DIR / "radio_cut.mp4"
    cmd += ["-filter_complex", ";".join(graph), "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
            "-c:a", "aac", "-b:a", "192k", "-t", str(total), str(out.relative_to(ROOT))]

    t0 = time.perf_counter()
    res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    latency = time.perf_counter() - t0
    if res.returncode != 0:
        log_call(stage="radio_cut", provider="local", model="ffmpeg", latency_s=latency,
                 status="error", error=res.stderr[-1500:])
        raise SystemExit(f"ffmpeg failed:\n{res.stderr}")
    log_call(stage="radio_cut", provider="local", model="ffmpeg", latency_s=latency, status="ok",
             output=out.relative_to(ROOT).as_posix(), duration_s=total,
             params={"loudnorm": "I=-14:TP=-1", "duck": duck})
    print(f"  radio cut: {out.relative_to(ROOT).as_posix()}  ({total:.1f}s, built in {latency:.1f}s)")
