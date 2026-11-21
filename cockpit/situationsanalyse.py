"""Situationsanalyse (Freitext) -> strukturierte Merkmale pro Person.

Zwei Methoden: 'regeln' (Schlüsselwörter, schnell, nachvollziehbar) und 'llm' (lokales Modell via Ollama,
nichts verlässt den Rechner). Vor der Extraktion werden Namen, Telefon, Adresse und Nummern entfernt.
Das Ergebnis ist eine Excel-Datei, die Fachpersonen prüfen/korrigieren und dann wie einen Export hochladen.

    python -m cockpit.situationsanalyse data/situationsanalysen --methode llm --out data/synthetic/Situationsanalyse_Merkmale.xlsx
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from xml.etree import ElementTree

import pandas as pd

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

FEATURES: dict[str, dict] = {
    "psychische_belastung": {
        "label": "Psychische Belastung",
        "values": ["ja", "nein"],
        "definition": "ja = Hinweise auf psychische Belastung (z.B. Schlafstörungen, Depression, Trauma/PTBS, Behandlung, starke Sorgen, "
                      "Konzentrationsprobleme); nein = ausdrücklich stabil/belastbar.",
        "rules": {"ja": r"schlafstörung|depress|ptbs|trauma|psychiatr|niedergeschlagen|belastende erinnerung|albtr[äa]um|kaum konzentrieren|erschöpft|sorgen um",
                  "nein": r"psychisch stabil|ausgeglichen|keine psychischen|belastbar"},
    },
    "lernmotivation": {
        "label": "Lernmotivation",
        "values": ["hoch", "mittel", "tief"],
        "definition": "Motivation für Deutschlernen/Kurse/Arbeit gemäss Einschätzung: hoch = sehr motiviert, Eigeninitiative, engagiert; "
                      "mittel = grundsätzlich motiviert, aber schwankend oder braucht Anstoss; tief = wenig Interesse, verpasst Termine, andere Prioritäten.",
        "rules": {"hoch": r"sehr motiviert|eigeninitiative|engagiert|klare ziele|hoch motiviert",
                  "tief": r"wenig interesse|keinen sinn|kein sinn|motivation gering|oft verpasst|unmotiviert",
                  "mittel": r"grundsätzlich motiviert|schwankend|braucht .*unterstützung"},
    },
    "lerntempo": {
        "label": "Lerntempo",
        "values": ["schnell", "mittel", "langsam"],
        "definition": "Lerntempo beim Sprachenlernen: schnell, mittel (üblich/normal) oder langsam (viele Wiederholungen, tut sich schwer).",
        "rules": {"schnell": r"lernt schnell|rasche fortschritte", "langsam": r"lernt langsam|wiederholungen|tut sich schwer",
                  "mittel": r"üblichen bereich|normal mit|durchschnittlich"},
    },
    "betreuung_hindernis": {
        "label": "Betreuungspflichten als Hindernis",
        "values": ["ja", "nein"],
        "definition": "ja = Kinderbetreuung/Betreuungspflichten schränken die Verfügbarkeit für Kurse oder Arbeit ein; "
                      "nein = verfügbar, Betreuung geregelt oder keine Betreuungspflichten.",
        "rules": {"ja": r"kein kita|eingeschränkt wegen|wegen der betreuung|betreut die kleinen kinder|nur an .{0,20}vormittag",
                  "nein": r"voll verfügbar|keine betreuungspflichten|zeitlich flexibel|kita geregelt"},
    },
    "soziales_netz": {
        "label": "Soziales Netz",
        "values": ["gut", "schwach"],
        "definition": "gut = vernetzt, Kontakte, Freiwillige/Tandem, unterstützende Verwandte; schwach = isoliert, kaum Kontakte.",
        "rules": {"gut": r"gut vernetzt|verwandte in bern|tandem|viele kontakte|quartiertreff",
                  "schwach": r"kaum soziale kontakte|isoliert|kaum jemanden"},
    },
}
UNKNOWN = "unklar"
_PII_LABELS = re.compile(r"^(name|vorname|telefon|e-mail|strasse|plz|n-nr|vers\.?-n|zemis-nr|zust\. sar|geburtsdatum|einreisedatum)\b", re.I)
_PLACEHOLDER = re.compile(r"\b(hd|gs|dd)_\w+|Element auswählen|☐")


@dataclass
class PersonSection:
    index: int
    zemis: str | None
    text: str
    note: str = ""


@dataclass
class ParsedDocument:
    name: str
    dossier: str | None
    persons: list[PersonSection] = field(default_factory=list)


def read_paragraphs(name: str, data: bytes) -> list[str]:
    suffix = Path(name).suffix.lower()
    if suffix == ".docx":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            root = ElementTree.fromstring(z.read("word/document.xml"))
        # alle w:t eines Absatzes, auch innerhalb von Inhaltssteuerelementen (w:sdt) der Word-Vorlage
        return ["".join(t.text or "" for t in p.iter(f"{W}t")).strip() for p in root.iter(f"{W}p")]
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return [line.strip() for page in reader.pages for line in (page.extract_text() or "").splitlines()]
    return data.decode("utf-8", errors="replace").splitlines()


def parse_document(name: str, paragraphs: list[str]) -> ParsedDocument:
    m = re.search(r"(D\d+\.\d+)", name)
    doc = ParsedDocument(name=name, dossier=m.group(1) if m else None)
    personalia: dict[int, dict] = {}
    household: list[str] = []
    sections: dict[int, dict] = {}
    top, sub = 0, 0

    for line in (p for p in paragraphs if p.strip()):
        h = re.match(r"^(\d+)\.(\d+)?\s+(.*)$", line)
        if h and len(line) < 160 and not line.endswith(":"):
            top, sub = int(h.group(1)), int(h.group(2) or 0)
            if top >= 3 and sub == 0:
                birth = re.search(r"(\d{2}\.\d{2}\.\d{4})", h.group(3))
                sections[top] = {"birth": birth.group(1) if birth else None, "lines": []}
            continue
        if top == 1 and sub:
            info = personalia.setdefault(sub, {})
            if z := re.search(r"Zemis-Nr\.?:\s*(\d{6,})", line):
                info["zemis"] = z.group(1)
            if b := re.search(r"Geburtsdatum:\s*(\d{2}\.\d{2}\.\d{4})", line):
                info["birth"] = b.group(1)
        elif top == 2:
            household.append(line)
        elif top >= 3:
            sections[top]["lines"].append(line)

    for idx, sec in sorted(sections.items()):
        match = next((p for p in personalia.values() if sec["birth"] and p.get("birth") == sec["birth"]), None)
        note = ""
        if match is None:
            match = personalia.get(idx - 2, {})
            note = "Zuordnung über Reihenfolge" if match else "Zemis-Nr. nicht gefunden"
        text = "\n".join(_clean(household) + _clean(sec["lines"]))
        doc.persons.append(PersonSection(index=idx, zemis=match.get("zemis"), text=text, note=note))
    return doc


def _clean(lines: list[str]) -> list[str]:
    out = []
    for line in lines:
        if _PII_LABELS.match(line):
            continue
        line = _PLACEHOLDER.sub("", line).strip()
        if line:
            out.append(line)
    return out


def extract_rules(text: str) -> dict[str, str]:
    low = text.lower()
    result = {}
    for feat, spec in FEATURES.items():
        result[feat] = next((v for v, pattern in spec["rules"].items() if re.search(pattern, low)), UNKNOWN)
    return result


def _llm_schema() -> dict:
    return {"type": "object",
            "properties": {f: {"type": "string", "enum": spec["values"] + [UNKNOWN]} for f, spec in FEATURES.items()},
            "required": list(FEATURES)}


def _llm_prompt() -> str:
    lines = ["Du liest einen Ausschnitt aus einer Situationsanalyse des Asylsozialdienstes über eine Person.",
             "Bestimme für jedes Merkmal genau einen Wert. Stütze dich nur auf den Text; wenn der Text zum Merkmal nichts sagt: unklar.",
             "Merkmale:"]
    lines += [f"- {f}: {spec['definition']}" for f, spec in FEATURES.items()]
    lines.append("Antworte nur mit JSON.")
    return "\n".join(lines)


def extract_llm(text: str, model: str = "qwen3:4b", url: str = "http://localhost:11434") -> dict[str, str]:
    import requests

    resp = requests.post(f"{url}/api/chat", timeout=600, json={
        "model": model, "stream": False, "think": False, "format": _llm_schema(), "options": {"temperature": 0},
        "messages": [{"role": "system", "content": _llm_prompt()}, {"role": "user", "content": text}],
    })
    resp.raise_for_status()
    data = json.loads(resp.json()["message"]["content"])
    return {f: data.get(f, UNKNOWN) if data.get(f) in FEATURES[f]["values"] + [UNKNOWN] else UNKNOWN for f in FEATURES}


def llm_available(model: str, url: str = "http://localhost:11434") -> bool:
    import requests

    try:
        tags = requests.get(f"{url}/api/tags", timeout=3).json()
    except Exception:  # noqa: BLE001
        return False
    return any(m.get("name") == model for m in tags.get("models", []))


def extract_documents(
    files: list[tuple[str, bytes]],
    method: str = "regeln",
    model: str = "qwen3:4b",
    workers: int = 1,
    cache_path: Path | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> pd.DataFrame:
    sections = []
    for name, data in files:
        doc = parse_document(name, read_paragraphs(name, data))
        sections += [(doc, p) for p in doc.persons]

    cache = _load_cache(cache_path)
    lock = threading.Lock()

    def run(item: tuple[ParsedDocument, PersonSection]) -> dict:
        doc, person = item
        key = hashlib.sha256(f"{method}|{model}|{person.text}".encode()).hexdigest()
        if key not in cache:
            value = extract_llm(person.text, model) if method == "llm" else extract_rules(person.text)
            with lock:
                cache[key] = value
                _append_cache(cache_path, key, value)
        return {"Zemis-Nr.": person.zemis, "Dossier-Nr.": doc.dossier, "Datei": doc.name,
                "Methode": f"LLM lokal ({model})" if method == "llm" else "Regeln",
                **{FEATURES[f]["label"]: v for f, v in cache[key].items()}, "Hinweis": person.note or None}

    # progress runs on the calling thread: Streamlit refuses UI calls from worker threads (NoSessionContext)
    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for done, row in enumerate(pool.map(run, sections), start=1):
            rows.append(row)
            if progress:
                progress(done, len(sections))
    return pd.DataFrame(rows)


def _load_cache(path: Path | None) -> dict[str, dict]:
    cache: dict[str, dict] = {}
    if path and path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            cache[entry["key"]] = entry["value"]
    return cache


def _append_cache(path: Path | None, key: str, value: dict) -> None:
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"key": key, "value": value}, ensure_ascii=False) + "\n")


def evaluate(extracted: pd.DataFrame, truth: pd.DataFrame) -> pd.DataFrame:
    """Übereinstimmung der Extraktion mit der Ground Truth (nur synthetische Daten)."""
    t = truth.assign(**{"Zemis-Nr.": truth["Zemis-Nr."].astype(str)})
    merged = extracted.merge(t, on="Zemis-Nr.", suffixes=("", "_wahr"))
    rows = []
    for f, spec in FEATURES.items():
        hit = merged[spec["label"]] == merged[f]
        rows.append({"Merkmal": spec["label"], "Personen": len(merged), "Trefferquote": round(hit.mean(), 3),
                     "davon 'unklar' korrekt erkannt": int(((merged[f] == UNKNOWN) & hit).sum())})
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder")
    ap.add_argument("--methode", choices=["regeln", "llm"], default="regeln")
    ap.add_argument("--model", default="qwen3:4b")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--out", default="Situationsanalyse_Merkmale.xlsx")
    ap.add_argument("--cache", help="JSONL-Cache, damit ein abgebrochener LLM-Lauf fortgesetzt werden kann")
    ap.add_argument("--truth", help="Ground-Truth-CSV (nur synthetische Daten) für die Auswertung")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    paths = sorted(p for p in Path(args.folder).iterdir() if p.suffix.lower() in (".docx", ".pdf", ".txt"))[: args.limit]
    if args.methode == "llm" and not llm_available(args.model):
        sys.exit(f"Ollama-Modell {args.model} nicht erreichbar (http://localhost:11434).")

    def progress(i: int, n: int) -> None:
        if i % 10 == 0 or i == n:
            print(f"{i}/{n}", flush=True)

    cache = Path(args.cache) if args.cache else None
    df = extract_documents([(p.name, p.read_bytes()) for p in paths], args.methode, args.model, args.workers, cache, progress)
    df.to_excel(args.out, index=False)
    print(f"{len(df)} Personen -> {args.out}")
    if args.truth:
        print(evaluate(df, pd.read_csv(args.truth, dtype={"Zemis-Nr.": str})).to_string(index=False))


if __name__ == "__main__":
    main()
