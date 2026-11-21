import io
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from cockpit.ingest import detect_table, load_exports, parse_date

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("headers,table", [
    (["Klient/-in Zemis-Nr.", "Klientennummer", "Asylgeschäftsart", "Ereignisdatum", "Erledigung", "Erledigungscode", "Erledigungsdatum"], "asylgeschaeftsdaten"),
    (["Zemis Nummer", "Klientennummer", "Dossier-Nr.", "Verfahrensstand Gültig ab", "Verfahrensstand Gültig bis", "Verfahrensstand"], "asylverfahrensstand"),
    (["Klient/-in Zemis-Nr.", "Klientennummer", "Von", "Bis", "Arbeitgeber Name", "Arbeitgeber Ort", "Pensum %", "Erwerbsstatus"], "erwerb"),
    (["Zemis Nummer", "Klientennummer", "Arbeitsbeginn", "Verpflichtet bis", "Betrieb"], "zemis_taetigkeit"),
    (["Dossier-Nr.", "Unterstützung", "Finanzielle Unterstützung Gültig von", "Finanzielle Unterstützung Gültig bis", "Hauptgrund Beendigung Unterstützung"], "finanzielle_unterstuetzung"),
    (["Klientennummer", "Zemis Nummer", "Zuständigkeitsende", "Geburtsdatum (für «ab 16 J.»)", "Fallführung (Sozialarbeiter:in)"], "klient"),
    (["Klient/-in Zemis-Nr.", "Klientennummer", "Sprache", "Sprachniveau (A0 … C2)", "Art (Nachweis)", "Datum Erreichung"], "sprachstand"),
])
def test_detect_table(headers, table):
    detected, mapping = detect_table(headers)
    assert detected == table
    assert len(mapping) == len(headers)


def test_detect_prefix_headers_map_to_right_fields():
    _, mapping = detect_table(["Klientennummer", "Zuständigkeitsende", "Geburtsdatum (für «ab 16 J.»)", "Verfahrensstand (aktuell)"])
    assert mapping["Geburtsdatum (für «ab 16 J.»)"] == "geburtsdatum"
    assert mapping["Verfahrensstand (aktuell)"] == "status_aktuell"


@pytest.mark.parametrize("value,expected", [
    ("03.05.2024", "2024-05-03"), ("3.5.24", "2024-05-03"), (datetime(2024, 5, 3, 14, 0), "2024-05-03"),
    (45415, "2024-05-03"), ("2024-05-03", "2024-05-03"),
])
def test_parse_swiss_dates(value, expected):
    assert parse_date(value) == pd.Timestamp(expected)


def test_parse_invalid_date():
    with pytest.raises(ValueError):
        parse_date("31.02.2023")
    assert parse_date("") is None and parse_date(None) is None


def _xlsx(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


def test_load_reports_unknown_file_and_bad_dates():
    good = pd.DataFrame({"Zemis Nummer": [12345678], "Klientennummer": [12345], "Arbeitsbeginn": ["31.02.2024"], "Verpflichtet bis": ["01.03.2024"], "Betrieb": ["Adecco"]})
    junk = pd.DataFrame({"foo": [1], "bar": [2]})
    res = load_exports([("zemis.xlsx", _xlsx(good)), ("junk.xlsx", _xlsx(junk))])
    msgs = res.issues_frame()["Meldung"].tolist()
    assert "zemis_taetigkeit" in res.tables
    assert res.tables["zemis_taetigkeit"].loc[0, "klientennummer"] == "12345"
    assert any("keiner bekannten Tabelle" in m for m in msgs)
    assert any("Ungültiges Datum" in m for m in msgs)


def test_received_templates_are_recognized():
    templates = sorted((ROOT / "doc").glob("Hackathon_*.xlsx"))
    if not templates:
        pytest.skip("Vorlagen nicht vorhanden")
    res = load_exports([(p.name, p.read_bytes()) for p in templates])
    assert len(res.tables) == len(templates)
