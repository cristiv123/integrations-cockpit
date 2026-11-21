"""One local page that shows a single deck slide, scaled to the window, for the video.

    python tools/demo-video/build_slides.py      # -> pitch/deck/slides.html, open with ?s=<slide id>
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "pitch" / "deck" / "project"

BASE_CSS = """
* { margin: 0 }
html, body { width: 100%; height: 100%; overflow: hidden; background: #14213D }
body > section { display: none; width: 1920px; height: 1080px; position: absolute; left: 0; top: 0;
  transform-origin: 0 0; box-sizing: border-box; overflow: hidden }
body > section.show { display: flex }
aside { display: none !important }
x-shape, x-icon { display: block }
x-shape[kind=ellipse] { border-radius: 50% }
x-shape[kind=arrow-right] { clip-path: polygon(0 32%, 58% 32%, 58% 0, 100% 50%, 58% 100%, 58% 68%, 0 68%) }
table { border-collapse: collapse }
th, td { padding: .35em .6em; text-align: left; border-bottom: 2px solid #0002; vertical-align: top }
"""

SCRIPT = """
const id = new URLSearchParams(location.search).get('s') || 'cover';
const s = document.getElementById(id) || document.querySelector('section');
s.classList.add('show');
const fit = () => {
  const k = Math.min(innerWidth / 1920, innerHeight / 1080);
  s.style.transform = `translate(${(innerWidth - 1920 * k) / 2}px, ${(innerHeight - 1080 * k) / 2}px) scale(${k})`;
};
fit(); addEventListener('resize', fit);
"""


def main() -> None:
    deck = json.loads((PROJECT / "deck.json").read_text(encoding="utf-8"))
    fonts = "".join(f'<link rel="stylesheet" href="{f["href"]}">' for f in deck["faces"].values() if "href" in f)
    slides = "".join((PROJECT / "slides" / f"{sid}.html").read_text(encoding="utf-8") for sid in deck["order"])
    css = (PROJECT / "deck.css").read_text(encoding="utf-8")
    out = ROOT / "pitch" / "deck" / "slides.html"
    out.write_text(f"<!doctype html><html><head><meta charset='utf-8'><title>{deck['title']}</title>{fonts}"
                   f"<style>{BASE_CSS}</style><style>{css}</style></head><body>{slides}<script>{SCRIPT}</script></body></html>",
                   encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
