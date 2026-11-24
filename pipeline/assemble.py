"""Stage: final assembly (FFmpeg, local). Builds the film in 9:16 and 16:9 from the storyboard.

    python -m pipeline assemble

1. Picture, one segment per shot (1440x1440, 24 fps, exactly the shot's timeline duration):
   - the Wan clip for the shot's current hash if it exists (first 0.25 s trimmed, gently slowed
     or held on its last frame if shorter than the shot);
   - otherwise a Ken Burns move over the keyframe, chosen from the shot's `camera` field
     (push-in, pan, or a very slow drift for "static"), the brief's fallback.
   Segments are cached by a hash of their source file and timing.
2. Sound: narration placed on the timeline, score (or placeholder) ducked under it with
   sidechaincompress, loudness-normalised to -14 LUFS / -1 dBTP. Built once, shared by both exports.
3. Each aspect ratio: centre crop of the square master (keyframes are composed with the subject in
   the middle), fade in from / out to black, burned-in subtitles inside the safe area, end card.

Output: outputs/final/night_keeper_9x16.mp4, night_keeper_16x9.mp4, night_keeper.srt
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from pipeline import timeline
from pipeline.common import OUTPUTS, ROOT, log_call
from pipeline.keyframes import file_hash
from pipeline.narration import MANIFEST
from pipeline.radio_cut import PLACEHOLDER
from pipeline.storyboard import input_hash, load

FINAL = OUTPUTS / "final"
SEG_DIR = FINAL / "segments"
SQUARE = 1440
FPS = 24
TRIM_HEAD_S = 0.25  # "many clips have a weak first half second" (brief)
ASPECTS = {
    # crop of the square master, output size, subtitle style (libass units, PlayResY 288)
    "9x16": {"crop": (810, 1440), "size": (1080, 1920), "font": 9, "margin_v": 70},
    "16x9": {"crop": (1440, 810), "size": (1920, 1080), "font": 14, "margin_v": 14},
}


def ffmpeg(args: list[str], what: str, **log_extra) -> None:
    t0 = time.perf_counter()
    res = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args],
                         cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    latency = time.perf_counter() - t0
    if res.returncode != 0:
        log_call(stage=f"assemble:{what}", provider="local", model="ffmpeg", latency_s=latency,
                 status="error", error=res.stderr[-1500:], **log_extra)
        raise SystemExit(f"ffmpeg ({what}) failed:\n{res.stderr[-3000:]}")
    log_call(stage=f"assemble:{what}", provider="local", model="ffmpeg", latency_s=latency, status="ok", **log_extra)


def ken_burns(camera: str, frames: int, index: int) -> str:
    """zoompan expressions for a camera move over a still. Consecutive static shots alternate drift."""
    n = max(frames - 1, 1)
    cam = camera.lower()
    centre = "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    if "push" in cam:
        z, xy = f"z='1+0.10*on/{n}'", centre
    elif "pan right" in cam:
        z, xy = "z='1.12'", f"x='(iw-iw/zoom)*on/{n}':y='ih/2-(ih/zoom/2)'"
    elif "pan left" in cam:
        z, xy = "z='1.12'", f"x='(iw-iw/zoom)*(1-on/{n})':y='ih/2-(ih/zoom/2)'"
    else:  # static: a barely visible drift so the frame stays alive; alternate in/out
        z = f"z='1.06-0.05*on/{n}'" if index % 2 else f"z='1.01+0.05*on/{n}'"
        xy = centre
    return f"{z}:{xy}"


def segment(shot: dict, tl_shot: dict, keyframe: Path, clip: Path | None, index: int) -> Path:
    dur = tl_shot["duration"]
    frames = round(dur * FPS)
    src = clip or keyframe
    method = "clip" if clip else "kenburns"
    h = input_hash(method, file_hash(src), frames, shot["camera"], index % 2, SQUARE)
    out = SEG_DIR / f"seg_{shot['id']:02d}_{h}.mp4"
    if out.exists():
        return out
    SEG_DIR.mkdir(parents=True, exist_ok=True)
    enc = ["-r", str(FPS), "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-an"]
    if clip:
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                str(clip)], capture_output=True, text=True)
        usable = max(float(probe.stdout.strip() or 0) - TRIM_HEAD_S, 0.5)
        slow = min(max(dur / usable, 1.0), 1.5)  # slow down at most 1.5x, then hold the last frame
        vf = (f"trim=start={TRIM_HEAD_S},setpts=(PTS-STARTPTS)*{slow:.3f},fps={FPS},"
              f"scale={SQUARE}:{SQUARE}:flags=lanczos,tpad=stop_mode=clone:stop_duration={dur},"
              f"trim=duration={dur}")
        ffmpeg(["-i", str(src), "-vf", vf, *enc, str(out)], "segment", shot=shot["id"], method=method)
    else:
        # Upscale first so zoompan's integer pixel steps do not judder.
        vf = (f"scale=4096:4096:flags=lanczos,zoompan={ken_burns(shot['camera'], frames, index)}"
              f":d={frames}:s={SQUARE}x{SQUARE}:fps={FPS}")
        ffmpeg(["-loop", "1", "-i", str(src), "-vf", vf, "-frames:v", str(frames), *enc, str(out)],
               "segment", shot=shot["id"], method=method)
    return out


def current_clip(sb: dict, shot_id: int) -> Path | None:
    from pipeline.shots import SHOTS_DIR, plan
    job = next(j for j in plan(sb) if j["shot"] == shot_id)
    p = SHOTS_DIR / job["out"]
    return p if p.exists() else None


def mix_audio(sb: dict, tl: dict, out: Path) -> None:
    voiced = [s for s in tl["shots"] if s["voice_file"]]
    total, duck = tl["total"], sb["music"].get("duck", {})
    args: list[str] = []
    for s in voiced:
        args += ["-i", s["voice_file"]]
    g = [f"[{i}:a]aresample=48000,adelay={int(s['voice_start'] * 1000)}:all=1[v{i}]" for i, s in enumerate(voiced)]
    g.append("".join(f"[v{i}]" for i in range(len(voiced))) + f"amix=inputs={len(voiced)}:normalize=0:"
             f"duration=longest,apad=whole_dur={total},aformat=channel_layouts=stereo,asplit=2[voice][key]")
    chosen = sb["music"].get("chosen")
    if chosen:
        args += ["-stream_loop", "-1", "-i", chosen]
        g.append(f"[{len(voiced)}:a]aresample=48000,atrim=duration={total},aformat=channel_layouts=stereo,"
                 f"afade=t=in:d=2,afade=t=out:st={total - 4}:d=4,volume=0.8[mus]")
    else:
        g.append(f"aevalsrc='{PLACEHOLDER}':s=48000:d={total},lowpass=f=900,afade=t=in:d=2,"
                 f"afade=t=out:st={total - 3}:d=3,aformat=channel_layouts=stereo,volume=0.6[mus]")
    g.append(f"[mus][key]sidechaincompress=threshold={duck.get('threshold', 0.02)}:ratio={duck.get('ratio', 6)}"
             f":attack={duck.get('attack_ms', 300)}:release={duck.get('release_ms', 1500)}[ducked]")
    g.append("[ducked][voice]amix=inputs=2:normalize=0,loudnorm=I=-14:TP=-1:LRA=11,aresample=48000[a]")
    ffmpeg([*args, "-filter_complex", ";".join(g), "-map", "[a]", "-t", str(total), "-c:a", "pcm_s16le",
            str(out.relative_to(ROOT))], "mix", music=chosen or "placeholder")


def run() -> None:
    sb = load()
    tl = timeline.build(sb, json.loads(MANIFEST.read_text(encoding="utf-8")))
    kf = json.loads((OUTPUTS / "keyframes" / "manifest.json").read_text(encoding="utf-8"))
    FINAL.mkdir(parents=True, exist_ok=True)

    segs, used = [], []
    for i, (shot, tls) in enumerate(zip(sb["shots"], tl["shots"])):
        clip = current_clip(sb, shot["id"])
        seg = segment(shot, tls, ROOT / kf[str(shot["id"])]["file"], clip, i)
        segs.append(seg)
        used.append("Wan clip" if clip else "Ken Burns")
        print(f"  shot {shot['id']:02d}: {tls['duration']:5.2f}s  {used[-1]:<9}  {seg.name}")
    # End card: black, its text comes from the subtitle track (centred).
    end = SEG_DIR / f"endcard_{tl['end_card']['duration']}s.mp4"
    if not end.exists():
        ffmpeg(["-f", "lavfi", "-i", f"color=c=black:s={SQUARE}x{SQUARE}:r={FPS}:d={tl['end_card']['duration']}",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(end.relative_to(ROOT))], "segment", shot="end_card")
    concat = FINAL / "concat.txt"
    concat.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in [*segs, end]), encoding="utf-8")
    master = FINAL / "master_square.mp4"
    ffmpeg(["-f", "concat", "-safe", "0", "-i", str(concat.relative_to(ROOT)), "-c", "copy",
            str(master.relative_to(ROOT))], "concat")

    srt = FINAL / "night_keeper.srt"
    srt.write_text(timeline.srt(tl), encoding="utf-8")
    (FINAL / "timeline.json").write_text(json.dumps(tl, indent=2, ensure_ascii=False), encoding="utf-8")
    mix = FINAL / "mix.wav"
    mix_audio(sb, tl, mix)

    total = tl["total"]
    fade_out_at = tl["end_card"]["start"] - 1.0
    for name, a in ASPECTS.items():
        (cw, ch), (w, h) = a["crop"], a["size"]
        sub = srt.relative_to(ROOT).as_posix()
        if w > h:
            # 16:9: a centre crop of the square cut off heads (shot 4, FAILURES F12). Show the whole
            # square instead, over a blurred, darkened copy of itself filling the sides.
            frame = (f"split=2[bg][fg];[bg]scale={w}:{w},crop={w}:{h},boxblur=40:2,eq=brightness=-0.12[bgb];"
                     f"[fg]scale={h}:{h}:flags=lanczos[fgs];[bgb][fgs]overlay=(W-w)/2:0")
        else:
            frame = f"crop={cw}:{ch},scale={w}:{h}:flags=lanczos"
        vf = (f"{frame},fade=t=in:d=1.0,fade=t=out:st={fade_out_at:.2f}:d=1.0,"
              f"subtitles={sub}:force_style='FontName=Arial,FontSize={a['font']},Alignment=2,"
              f"MarginV={a['margin_v']},Outline=1,Shadow=0'")
        out = FINAL / f"night_keeper_{name}.mp4"
        ffmpeg(["-i", str(master.relative_to(ROOT)), "-i", str(mix.relative_to(ROOT)), "-vf", vf,
                "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                "-t", str(total), str(out.relative_to(ROOT))], f"export_{name}",
               output=out.relative_to(ROOT).as_posix(), duration_s=total,
               shots_wan=used.count("Wan clip"), shots_kenburns=used.count("Ken Burns"))
        print(f"  {name}: {out.relative_to(ROOT).as_posix()}  ({total:.1f}s)")
