"""Professional cut of the demo video (techniques from maria-antartica), 1080p.

    python tools/demo-video/polish.py en
    python tools/demo-video/polish.py en --reuse-app   # keep the framed recording, redo the final cut only

Needs: build/<lang>/timeline.json + video/integrations-cockpit-demo-<lang>.mp4 (record.mjs + compose.py),
build/cards/*.mp4 (render_cards.ps1, Remotion), build/<lang>/*.mp3 + *.srt (tts.py).
Writes video/integrations-cockpit-pitch-<lang>.mp4 and .srt.

- Remotion cards replace the static slides (title, challenge, data protection, end).
- The screen recording sits in a frame on a dark backdrop (rounded corners, soft shadow), with slow
  push-ins on three key moments and chapter labels.
- Cross-dissolves between cards and demo.
- Burned-in English subtitles (ASS) plus a separate .srt.
- Music bed (Pixabay) with ducking under the narration, EQ dip for speech, loudness -14 LUFS / -1 dBTP.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFilter

import compose

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
W, H, FPS = 1920, 1080, 30
XF = 0.6                      # cross-dissolve, seconds
LEAD = 0.35                   # narration starts this long after its scene
APP_W, APP_H, APP_X, APP_Y = 1680, 945, 120, 58   # the framed recording
RADIUS = 18
MUSIC = HERE / "assets" / "music" / "documentary-atlasaudio.mp3"
MUSIC_VOL = 0.42

CHAPTERS = {
    "data": "01 · EXCEL IN",
    "cockpit": "02 · A TRAFFIC LIGHT FOR EVERY GOAL",
    "calls": "03 · WHO DO I CALL THIS WEEK?",
    "money": "04 · GOALS REACHED, NOT CLAIMED",
    "patterns": "05 · WHAT MAKES THE DIFFERENCE",
    "excel": "06 · EXCEL OUT",
}
# Push-ins: scene, from/to seconds after the scene start, centre in recording pixels (1920x1080), zoom.
ZOOMS = [
    ("calls", 8.5, 14.0, 1140, 700, 1.40),
    ("money", 6.0, 11.5, 1250, 650, 1.45),
    ("patterns", 11.0, 14.5, 1420, 610, 1.55),
]
RAMP = 0.9


def run(args: list[str]) -> None:
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-stats", "-y", *args], check=True)


def duration_of(path: Path) -> float:
    out = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


# ── stills for the frame ──────────────────────────────────────────────────────

def make_stills(build: Path) -> None:
    bg = Image.new("RGB", (W, H))
    px = bg.load()
    cx, cy = W / 2, H * 0.35
    for y in range(H):
        for x in range(0, W):
            d = min(1.0, (((x - cx) / (W * 0.62)) ** 2 + ((y - cy) / (H * 0.75)) ** 2) ** 0.5)
            a, b = (0x1E, 0x31, 0x60), (0x0B, 0x14, 0x28)
            px[x, y] = tuple(int(a[i] + (b[i] - a[i]) * d) for i in range(3))
    draw = ImageDraw.Draw(bg)
    for y in range(0, H, 64):
        for x in range(0, W, 64):
            draw.ellipse((x, y, x + 3, y + 3), fill=(0x2C, 0x3B, 0x5E))
    bg.save(build / "bg.png")

    mask = Image.new("L", (APP_W, APP_H), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, APP_W - 1, APP_H - 1), RADIUS, fill=255)
    mask.save(build / "mask.png")

    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((APP_X, APP_Y + 18, APP_X + APP_W, APP_Y + APP_H + 18), RADIUS, fill=(0, 0, 0, 150))
    shadow.filter(ImageFilter.GaussianBlur(28)).save(build / "shadow.png")


# ── push-in expressions ───────────────────────────────────────────────────────

def zoom_exprs(windows: list[tuple[float, float, float, float, float]]) -> tuple[str, str, str]:
    """Smooth zoom/centre as ffmpeg expressions of the input time `it` (zoompan)."""
    z_terms, x_terms, y_terms = [], [], []
    for a, b, cx, cy, z in windows:
        u = f"clip((it-{a:.3f})/{RAMP},0,1)"
        v = f"clip(({b:.3f}-it)/{RAMP},0,1)"
        s = f"({u}*{u}*(3-2*{u})*{v}*{v}*(3-2*{v}))"
        z_terms.append(f"{z - 1:.3f}*{s}")
        x_terms.append(f"{cx - W / 2:.1f}*{s}")
        y_terms.append(f"{cy - H / 2:.1f}*{s}")
    zoom = "1+" + "+".join(z_terms) if z_terms else "1"
    cx = f"{W / 2}+" + "+".join(x_terms) if x_terms else f"{W / 2}"
    cy = f"{H / 2}+" + "+".join(y_terms) if y_terms else f"{H / 2}"
    return zoom, cx, cy


# ── subtitles ─────────────────────────────────────────────────────────────────

def srt_cues(path: Path) -> list[tuple[float, float, str]]:
    def secs(s: str) -> float:
        h, m, rest = s.split(":")
        return int(h) * 3600 + int(m) * 60 + float(rest.replace(",", "."))
    cues = []
    for block in path.read_text(encoding="utf-8").strip().split("\n\n"):
        lines = block.strip().splitlines()
        if len(lines) >= 3:
            a, b = (secs(x.strip()) for x in lines[1].split("-->"))
            cues.append((a, b, " ".join(lines[2:]).strip()))
    return cues


def chunk(a: float, b: float, text: str, max_chars: int = 62) -> list[tuple[float, float, str]]:
    """Split a long sentence into subtitle-sized pieces, timed by their share of the characters."""
    words, parts, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > max_chars:
            parts.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        parts.append(cur)
    total = sum(len(p) for p in parts)
    out, t = [], a
    for p in parts:
        d = (b - a) * len(p) / total
        out.append((t, t + d, p))
        t += d
    return out


def ass_time(t: float) -> str:
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms % 3600000 // 60000:02d}:{ms % 60000 // 1000:02d},{ms % 1000:03d}"


ASS_HEAD = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Sub,Segoe UI Semibold,44,&H00FFFFFF,&H00FFFFFF,&H00180C06,&H96000000,0,0,0,0,100,100,0,0,1,2.6,1.4,2,200,200,36,1
Style: Chap,Segoe UI,25,&H008AB9F2,&H008AB9F2,&H183D2114,&H183D2114,1,0,0,0,100,100,3,0,3,9,0,7,128,0,14,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""


# ── the cut ───────────────────────────────────────────────────────────────────

def main(lang: str) -> None:
    build = HERE / "build" / lang
    cards = HERE / "build" / "cards"
    raw = ROOT / "video" / f"integrations-cockpit-demo-{lang}.mp4"
    starts, raw_total = compose.scene_times(lang)
    narr = {s: build / f"{s}.mp3" for s in starts}
    durs = json.loads((build / "durations.json").read_text(encoding="utf-8"))
    make_stills(build)

    # 1. The framed recording with push-ins: from the "data" scene to the "outro" scene. The data scene
    # opens on the previous slide while the app loads, so the cut starts once the app is ready and that
    # first frame is held instead.
    a0, a1 = starts["data"], starts["outro"]
    tl = json.loads((build / "timeline.json").read_text(encoding="utf-8"))
    out, _ = compose.timing(tl)
    data_wall = next(s["start"] for s in tl["scenes"] if s["name"] == "data")
    first_wait = min((w for w in tl["waits"] if w["a"] >= data_wall), key=lambda w: w["a"])
    ready = out(first_wait["b"]) + 0.25
    card_d = {c: duration_of(cards / f"{c}.mp4") for c in ("Titel", "Ziele", "Datenschutz", "Abspann")}
    app_start = card_d["Titel"] + card_d["Ziele"] - 2 * XF
    # Hold the first frame if the opening narration would still be running.
    pad = max(0.0, 0.5 + durs["intro"] + 0.25 - (app_start + LEAD))
    rel = {s: starts[s] - a0 + pad for s in CHAPTERS}
    windows = []
    for scene, f, t, x, y, z in ZOOMS:
        windows.append((rel[scene] + f, rel[scene] + t, APP_X + x * APP_W / W, APP_Y + y * APP_H / H, z))
    zx, cx, cy = zoom_exprs(windows)
    app = build / "app_framed.mp4"
    hold = (ready - a0) + pad
    if REUSE_APP and app.exists():
        print("1/2 framed recording (reused)")
    else:
        print("1/2 framed recording")
        render_app(raw, build, app, ready, a1, hold, zx, cx, cy)
    app_d = duration_of(app)
    final_cut(lang, build, cards, card_d, app, app_d, rel, durs, narr)


def render_app(raw: Path, build: Path, app: Path, ready: float, a1: float, hold: float, zx: str, cx: str, cy: str) -> None:
    run(["-ss", f"{ready:.3f}", "-to", f"{a1:.3f}", "-i", str(raw), "-i", str(build / "bg.png"), "-i", str(build / "shadow.png"),
         "-i", str(build / "mask.png"), "-filter_complex",
         f"[0:v]fps={FPS},tpad=start_mode=clone:start_duration={hold:.3f},scale={APP_W}:{APP_H}:flags=lanczos,format=rgba[a];"
         f"[3:v]format=gray[m];[a][m]alphamerge[am];[1:v][2:v]overlay=0:0[b];[b][am]overlay={APP_X}:{APP_Y},"
         f"scale={W * 2}:{H * 2}:flags=bicubic,"
         f"zoompan=z='{zx}':x='clip(({cx})*2-iw/zoom/2,0,iw-iw/zoom)':y='clip(({cy})*2-ih/zoom/2,0,ih-ih/zoom)':d=1:s={W}x{H}:fps={FPS},"
         f"format=yuv420p[v]", "-map", "[v]", "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-r", str(FPS), str(app)])


def final_cut(lang: str, build: Path, cards: Path, card_d: dict, app: Path, app_d: float, rel: dict, durs: dict, narr: dict) -> None:
    # 2. Timeline: cards and demo joined by cross-dissolves.
    seq = [("Titel", cards / "Titel.mp4", card_d["Titel"]), ("Ziele", cards / "Ziele.mp4", card_d["Ziele"]),
           ("app", app, app_d), ("Datenschutz", cards / "Datenschutz.mp4", card_d["Datenschutz"]),
           ("Abspann", cards / "Abspann.mp4", card_d["Abspann"])]
    offsets, acc = [0.0], seq[0][2]
    for _, _, d in seq[1:]:
        offsets.append(acc - XF)
        acc += d - XF
    total = acc
    start_of = {name: off for (name, _, _), off in zip(seq, offsets)}
    app_t0 = start_of["app"]

    # Narration placement, subtitles and chapters on the final timeline.
    place = {"intro": 0.5, "outro": start_of["Datenschutz"] + 0.4}
    for s in CHAPTERS:
        place[s] = app_t0 + rel[s] + LEAD
    srt = []
    for scene, t in sorted(place.items(), key=lambda kv: kv[1]):
        for a, b, text in srt_cues(build / f"{scene}.srt"):
            srt += chunk(t + a, t + b, text)
    srt.sort()
    # Never two subtitles at once: libass would stack them.
    srt = [(a, min(b, srt[i + 1][0] - 0.04) if i + 1 < len(srt) else b, t) for i, (a, b, t) in enumerate(srt)]
    events = [f"Dialogue: 0,{ass_time(a)},{ass_time(b)},Sub,,0,0,0,,{t}" for a, b, t in srt]
    scene_list = list(CHAPTERS)
    for i, s in enumerate(scene_list):
        a = app_t0 + rel[s] + 0.2
        b = app_t0 + (rel[scene_list[i + 1]] if i + 1 < len(scene_list) else app_d) - 0.2
        events.append(f"Dialogue: 1,{ass_time(a)},{ass_time(b)},Chap,,0,0,0,,{{\\fad(400,300)}}{CHAPTERS[s]}")
    (build / "pitch.ass").write_text(ASS_HEAD + "\n".join(events) + "\n", encoding="utf-8")
    # Not named after the video: players would load it automatically on top of the burned-in subtitles.
    out_srt = ROOT / "video" / f"pitch-subtitles-{lang}.srt"
    out_srt.write_text("\n".join(f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{t}\n" for i, (a, b, t) in enumerate(srt, 1)), encoding="utf-8")

    # Video graph.
    inputs, vf = [], []
    for i, (_, path, _) in enumerate(seq):
        inputs += ["-i", str(path)]
        vf.append(f"[{i}:v]fps={FPS},format=yuv420p,setsar=1,settb=AVTB[s{i}]")
    prev = "s0"
    for i in range(1, len(seq)):
        vf.append(f"[{prev}][s{i}]xfade=transition=fade:duration={XF}:offset={offsets[i]:.3f}[x{i}]")
        prev = f"x{i}"
    vf.append(f"[{prev}]subtitles=pitch.ass,format=yuv420p[vout]")

    # Audio graph: narration lines + music bed ducked under them, then loudness for the web.
    n_video = len(seq)
    af, labels = [], []
    for k, (scene, t) in enumerate(sorted(place.items(), key=lambda kv: kv[1])):
        idx = n_video + k
        inputs += ["-i", str(narr[scene])]
        ms = int(t * 1000)
        af.append(f"[{idx}:a]aresample=48000,aformat=channel_layouts=stereo,adelay={ms}|{ms}[n{k}]")
        labels.append(f"[n{k}]")
    music_idx = n_video + len(labels)
    inputs += ["-i", str(MUSIC)]
    af.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0,apad,atrim=0:{total:.3f},asplit=2[voice][key]")
    af.append(f"[{music_idx}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{total:.3f},volume={MUSIC_VOL},"
              f"equalizer=f=1500:t=h:w=2500:g=-4,afade=t=in:st=0:d=1.5,afade=t=out:st={total - 3.5:.3f}:d=3.5[mus]")
    af.append("[mus][key]sidechaincompress=threshold=0.02:ratio=8:attack=15:release=900[duck]")
    af.append("[duck][voice]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1:LRA=11,"
              "aresample=48000,aformat=channel_layouts=stereo[aout]")

    mp4 = ROOT / "video" / f"integrations-cockpit-pitch-{lang}.mp4"
    print(f"2/2 final cut, {total:.1f}s")
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-stats", "-y", *inputs,
                    "-filter_complex", ";".join(vf + af), "-map", "[vout]", "-map", "[aout]",
                    "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-r", str(FPS), "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-metadata:s:a:0", "language=eng",
                    "-movflags", "+faststart", "-t", f"{total:.3f}", str(mp4)], check=True, cwd=build)
    print(f"{mp4}  {total:.1f}s, {mp4.stat().st_size / 1e6:.1f} MB\n{out_srt}")


REUSE_APP = "--reuse-app" in sys.argv  # only subtitles/music/cards changed: keep build/<lang>/app_framed.mp4

if __name__ == "__main__":
    for lang in [a for a in sys.argv[1:] if not a.startswith("--")] or ["en"]:
        main(lang)
