"""Narration for the demo video: one MP3 + one SRT per scene and language (method from KI-Wissen).

    python tools/demo-video/tts.py          # all languages in narration.json
    python tools/demo-video/tts.py en

Writes build/<lang>/<scene>.mp3, <scene>.srt and durations.json (seconds, read back from the
decoded file) – record.mjs holds every scene at least as long as its narration.
The narration text is sent to Microsoft's neural voice service; it holds no personal data.
"""
import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path

import edge_tts
import imageio_ffmpeg

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
NARRATION = json.loads((HERE / "narration.json").read_text(encoding="utf-8"))
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
RATE = "+4%"


def duration_of(path: Path) -> float:
    out = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


async def speak(lang: str) -> None:
    voice = NARRATION["voices"][lang]
    target = BUILD / lang
    target.mkdir(parents=True, exist_ok=True)
    durations = {}
    for scene, texts in NARRATION["scenes"].items():
        mp3, srt = target / f"{scene}.mp3", target / f"{scene}.srt"
        communicate = edge_tts.Communicate(texts[lang], voice, rate=RATE)
        subs = edge_tts.SubMaker()
        with mp3.open("wb") as audio:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio.write(chunk["data"])
                elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                    subs.feed(chunk)
        srt.write_text(subs.get_srt(), encoding="utf-8")
        durations[scene] = round(duration_of(mp3), 3)
        print(f"  {lang} {scene:10} {durations[scene]:6.2f}s")
    (target / "durations.json").write_text(json.dumps(durations, indent=2), encoding="utf-8")
    print(f"  {lang} total {sum(durations.values()):.1f}s")


async def main() -> None:
    for lang in sys.argv[1:] or list(NARRATION["voices"]):
        await speak(lang)


asyncio.run(main())
