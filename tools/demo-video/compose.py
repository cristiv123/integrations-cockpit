"""Assemble a recording into video/integrations-cockpit-demo-<lang>.mp4 (method from KI-Wissen).

    python tools/demo-video/compose.py en

Reads build/<lang>/timeline.json + frames/ (record.mjs) and the scene MP3s (tts.py).
H.264 1920x1080 at 30 fps, AAC narration, no subtitles. A screencast frame is held until the
next one; an app recomputation longer than WAIT_OUT is played faster, with a "▶▶ ×N" badge.
"""
import json
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
AUDIO_LEAD = 0.35
FADE = 0.6
BADGE_FONT = "C\\:/Windows/Fonts/seguisym.ttf"


def timing(tl: dict):
    """Wall-clock -> output-time mapping of a recording, and the squeezed waits."""
    wait_out = tl["waitOut"]
    t0 = tl["scenes"][0]["start"]
    waits = sorted((w["a"], w["b"]) for w in tl["waits"] if w["b"] - w["a"] > wait_out)

    def out(t: float) -> float:
        shift = 0.0
        for a, b in waits:
            if t <= a:
                break
            if t < b:
                return (a - t0) - shift + (t - a) * wait_out / (b - a)
            shift += (b - a) - wait_out
        return (t - t0) - shift

    return out, waits


def scene_times(lang: str) -> tuple[dict[str, float], float]:
    """Start of every scene in the composed demo video, in seconds, and its total length."""
    tl = json.loads((HERE / "build" / lang / "timeline.json").read_text(encoding="utf-8"))
    out, _ = timing(tl)
    return {s["name"]: out(s["start"]) for s in tl["scenes"]}, out(tl["end"])


def main(lang: str) -> None:
    build = HERE / "build" / lang
    tl = json.loads((build / "timeline.json").read_text(encoding="utf-8"))
    wait_out = tl["waitOut"]
    t0 = tl["scenes"][0]["start"]
    out, waits = timing(tl)
    total = out(tl["end"])
    frames = tl["frames"]
    first = max((i for i, f in enumerate(frames) if f["t"] <= t0), default=0)
    frames = frames[first:]
    times = [max(out(f["t"]), 0.0) for f in frames]
    times[0] = 0.0
    concat = build / "frames.ffconcat"
    with concat.open("w", encoding="utf-8") as fh:
        fh.write("ffconcat version 1.0\n")
        for i, f in enumerate(frames):
            nxt = times[i + 1] if i + 1 < len(frames) else total
            fh.write(f"file 'frames/{f['file']}'\nduration {max(nxt - times[i], 0.001):.4f}\n")
        fh.write(f"file 'frames/{frames[-1]['file']}'\n")

    badges = []
    for a, b in waits:
        start = out(a)
        if (b - a) / wait_out < 3:  # a short rerun played slightly faster needs no badge
            continue
        badges.append(
            f"drawtext=fontfile='{BADGE_FONT}':text='▶▶ ×{round((b - a) / wait_out)}':"
            f"fontsize=34:fontcolor=white:box=1:boxcolor=0x1F4E78@0.85:boxborderw=14:"
            f"x=w-tw-48:y=h-th-48:enable='between(t,{start:.3f},{start + wait_out:.3f})'"
        )
    vf = ",".join(["scale=1920:1080:flags=lanczos:in_range=full:out_range=tv", "fps=30"] + badges +
                  [f"fade=t=in:st=0:d={FADE}", f"fade=t=out:st={total - FADE:.3f}:d={FADE}", "format=yuv420p"])

    inputs, filters, labels = [], [], []
    for scene in tl["scenes"]:
        mp3 = build / f"{scene['name']}.mp3"
        if not mp3.exists():
            continue
        ms = int((out(scene["start"]) + AUDIO_LEAD) * 1000)
        inputs += ["-i", str(mp3)]
        idx = len(labels) + 1
        filters.append(f"[{idx}:a]adelay={ms}|{ms}[a{idx}]")
        labels.append(f"[a{idx}]")
    filters.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0,"
                   f"afade=t=out:st={total - FADE:.3f}:d={FADE},apad,atrim=0:{total:.3f}[aout]")

    video_dir = ROOT / "video"
    video_dir.mkdir(exist_ok=True)
    mp4 = video_dir / f"integrations-cockpit-demo-{lang}.mp4"
    lang3 = {"de": "deu", "fr": "fra", "it": "ita", "en": "eng", "ro": "ron"}[lang]
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-stats",
           "-f", "concat", "-safe", "0", "-i", str(concat), *inputs,
           "-filter_complex", ";".join(filters), "-vf", vf, "-map", "0:v", "-map", "[aout]",
           "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-r", "30", "-pix_fmt", "yuv420p", "-color_range", "tv",
           "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2", "-metadata:s:a:0", f"language={lang3}",
           "-movflags", "+faststart", "-t", f"{total:.3f}", str(mp4)]
    subprocess.run(cmd, check=True, cwd=build)
    print(f"{mp4}  {total:.1f}s, {len(waits)} wait(s) squeezed, {mp4.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    for lang in sys.argv[1:] or ["en"]:
        main(lang)
