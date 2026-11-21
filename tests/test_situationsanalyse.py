import json
from datetime import date

import pandas as pd
import pytest

from cockpit import situationsanalyse as sa
from synth.generate import generate, write_situationsanalysen


@pytest.fixture(scope="module")
def documents(tmp_path_factory):
    out = tmp_path_factory.mktemp("sa")
    rows = generate(households=25, seed=3, stichtag=date(2026, 11, 20))
    truth = pd.read_csv(write_situationsanalysen(rows["_situationsanalyse"], out / "docs", seed=3), dtype={"Zemis-Nr.": str})
    files = [(p.name, p.read_bytes()) for p in sorted((out / "docs").glob("*.docx"))]
    return rows["_situationsanalyse"], files, truth


def test_sections_are_linked_by_zemis(documents):
    docs, files, _ = documents
    parsed = sa.parse_document(files[0][0], sa.read_paragraphs(*files[0]))
    expected = {str(p["zemis"]) for d in docs if d["dossier"] == parsed.dossier for p in d["persons"]}
    assert {p.zemis for p in parsed.persons} == expected


def test_personal_data_removed_before_extraction(documents):
    docs, files, _ = documents
    name, data = files[0]
    parsed = sa.parse_document(name, sa.read_paragraphs(name, data))
    doc = next(d for d in docs if d["dossier"] == parsed.dossier)
    for section in parsed.persons:
        for p in doc["persons"]:
            assert p["nachname"] not in section.text and str(p["zemis"]) not in section.text
        assert "Telefon" not in section.text and "Name:" not in section.text


def test_rule_extraction_matches_truth(documents):
    _, files, truth = documents
    ev = sa.evaluate(sa.extract_documents(files, "regeln"), truth)
    assert (ev["Trefferquote"] > 0.95).all()


@pytest.mark.parametrize("text,feature,value", [
    ("Psychischer Gesundheitszustand:\nLeidet unter depressiven Verstimmungen.", "psychische_belastung", "ja"),
    ("Wirkt ausgeglichen und belastbar.", "psychische_belastung", "nein"),
    ("Lerntempo:\n", "lerntempo", "unklar"),
    ("Verfügbarkeit stark eingeschränkt wegen Kinderbetreuung.", "betreuung_hindernis", "ja"),
])
def test_rules(text, feature, value):
    assert sa.extract_rules(text)[feature] == value


def test_llm_output_is_sanitised(monkeypatch):
    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": json.dumps({"psychische_belastung": "vielleicht", "lernmotivation": "hoch"})}}

    import requests

    monkeypatch.setattr(requests, "post", lambda *a, **k: Resp())
    out = sa.extract_llm("irgendein Text")
    assert out["psychische_belastung"] == "unklar"
    assert out["lernmotivation"] == "hoch"
    assert out["soziales_netz"] == "unklar"


def test_plain_text_and_cache(tmp_path):
    text = "1.1 Dossierträger/-in\nZemis-Nr.: 12345678\n2. Situationsanalyse\nIsoliert.\n3. Individuelle Potenzialerhebung von X\nLernt schnell und selbständig."
    cache = tmp_path / "c.jsonl"
    df = sa.extract_documents([("bericht.txt", text.encode())], "regeln", cache_path=cache)
    assert df.loc[0, "Zemis-Nr."] == "12345678"
    assert df.loc[0, "Lerntempo"] == "schnell" and df.loc[0, "Soziales Netz"] == "schwach"
    assert cache.exists() and len(cache.read_text().splitlines()) == 1
