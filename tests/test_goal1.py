import pandas as pd
import pytest

from cockpit.goal1 import (STATUS_AT_RISK, STATUS_MISSED, STATUS_NA, STATUS_ON_TRACK, STATUS_REACHED,
                           STATUS_REACHED_LATE, evaluate_goal1, level_rank)
from cockpit.rules import load_rules

T = pd.Timestamp
STICHTAG = T("2026-11-20")


def klient(k, status="VA", birth="1990-01-01", ende="2030-01-01", uebergang=None, sw="SA 1"):
    return {"klientennummer": str(k), "zemis": str(1000 + k), "dossier": "D1", "zust_beginn": T("2020-01-01"),
            "zust_ende": T(ende) if ende else pd.NaT, "uebergang_gemeinde": T(uebergang) if uebergang else pd.NaT,
            "status_aktuell": status, "fallfuehrung": sw, "geburtsdatum": T(birth) if birth else pd.NaT}


def entry(k, d, art="Aufenthalt (Einreise)"):
    return {"zemis": str(1000 + k), "klientennummer": str(k), "geschaeftsart": art, "ereignisdatum": T(d)}


def proof(k, d, niveau="A1", nachweis="Zertifikat telc", sprache="Deutsch", by_zemis=False):
    return {"zemis": str(1000 + k), "klientennummer": None if by_zemis else str(k), "sprache": sprache,
            "niveau": niveau, "nachweis": nachweis, "datum": T(d) if d else pd.NaT}


def run(klienten, events, proofs, zer=None):
    tables = {
        "klient": pd.DataFrame(klienten),
        "asylgeschaeftsdaten": pd.DataFrame(events),
        "sprachstand": pd.DataFrame(proofs, columns=["zemis", "klientennummer", "sprache", "niveau", "nachweis", "datum"]),
    }
    if zer is not None:
        tables["integrationszielerreichung"] = pd.DataFrame(zer)
    res = evaluate_goal1(tables, load_rules(), STICHTAG)
    return res, res.persons.set_index("klientennummer")


def test_status_categories():
    res, p = run(
        [klient(1), klient(2), klient(3), klient(4), klient(5)],
        [entry(1, "2022-01-10"), entry(2, "2022-01-10"), entry(3, "2022-01-10"), entry(4, "2024-03-01"), entry(5, "2025-01-01")],
        [proof(1, "2023-05-01"), proof(2, "2025-06-01")],
    )
    assert p.loc["1", "status"] == STATUS_REACHED
    assert p.loc["2", "status"] == STATUS_REACHED_LATE
    assert p.loc["3", "status"] == STATUS_MISSED
    assert p.loc["4", "status"] == STATUS_AT_RISK  # Frist 01.03.2027 = 3.3 Monate
    assert p.loc["5", "status"] == STATUS_ON_TRACK
    assert p.loc["1", "frist"] == T("2025-01-10")
    assert res.totals["Quote fristgerecht (fällige)"] == pytest.approx(1 / 3, abs=0.001)


def test_scope_reasons():
    _, p = run(
        [klient(1, status="S"), klient(2, status="N (Asylsuchende)"), klient(3, ende="2025-01-01"),
         klient(4, uebergang="2026-01-01"), klient(5, birth="2015-01-01"), klient(6, status="B-FL+5"), klient(7)],
        [entry(k, "2024-01-01") for k in (1, 2, 3, 4, 5, 6)],
        [],
    )
    assert p.loc["1", "grund_nicht_anwendbar"].startswith("Status S")
    assert p.loc["2", "grund_nicht_anwendbar"].startswith("Status N")
    assert p.loc["3", "grund_nicht_anwendbar"] == "Zuständigkeit beendet"
    assert p.loc["4", "grund_nicht_anwendbar"] == "An Gemeinde übergeben"
    assert p.loc["5", "grund_nicht_anwendbar"] == "Unter 16 Jahre"
    assert p.loc["6", "im_scope"]  # Suffix +5 wird auf B-FL abgebildet
    assert p.loc["7", "grund_nicht_anwendbar"] == "Einreisedatum fehlt"
    assert (p.loc[["1", "2", "3", "4", "5", "7"], "status"] == STATUS_NA).all()


def test_age_reference_is_deadline():
    # 14 bei Einreise, 17 bei Frist -> im Scope (age_reference: deadline)
    _, p = run([klient(1, birth="2009-06-01")], [entry(1, "2023-06-15")], [])
    assert p.loc["1", "im_scope"]


def test_proof_rules():
    _, p = run(
        [klient(k) for k in range(1, 7)],
        [entry(k, "2024-01-01") for k in range(1, 7)],
        [
            proof(1, "2024-06-01", nachweis="Kursbestätigung"),       # zählt nicht
            proof(2, "2024-06-01", niveau="A0"),                       # zu tief
            proof(3, "2024-06-01", sprache="Englisch"),                # falsche Sprache
            proof(4, "2024-06-01", niveau="B1", nachweis="Schulbesuch Schweiz"),
            proof(5, "2024-06-01", by_zemis=True),                     # nur Zemis-Nr. vorhanden
            proof(6, None),                                            # Datum fehlt
        ],
    )
    assert pd.isna(p.loc["1", "erreicht_am"])
    assert pd.isna(p.loc["2", "erreicht_am"])
    assert pd.isna(p.loc["3", "erreicht_am"])
    assert p.loc["4", "erreicht_am"] == T("2024-06-01")
    assert p.loc["5", "erreicht_am"] == T("2024-06-01")
    assert pd.isna(p.loc["6", "erreicht_am"])


def test_earliest_proof_and_zielerreichung():
    _, p = run(
        [klient(1), klient(2)],
        [entry(1, "2023-01-01"), entry(2, "2023-01-01")],
        [proof(1, "2025-02-01", niveau="A2"), proof(1, "2024-03-01", nachweis="Zertifikat fide")],
        zer=[{"zemis": "1002", "ziel": "Ziel 1: Sprache A1", "erreicht_am": T("2024-09-01")}],
    )
    assert p.loc["1", "erreicht_am"] == T("2024-03-01")
    assert p.loc["1", "nachweis"].startswith("Zertifikat fide")
    assert p.loc["2", "erreicht_am"] == T("2024-09-01")
    assert p.loc["2", "quelle"] == "Zielerreichung"


def test_entry_fallback_birth_in_switzerland():
    _, p = run([klient(1, birth="2010-01-01")], [entry(1, "2010-01-01", art="Aufenthalt (Geburt)")], [])
    assert p.loc["1", "einreise"] == T("2010-01-01")


def test_missing_required_table():
    with pytest.raises(ValueError, match="sprachstand"):
        evaluate_goal1({"klient": pd.DataFrame([klient(1)]), "asylgeschaeftsdaten": pd.DataFrame([entry(1, "2024-01-01")])},
                       load_rules(), STICHTAG)


@pytest.mark.parametrize("value,expected", [("A1", 1), ("a2", 2), ("B1.1", 3), ("C2", 6), ("A0", 0), ("x", None), (None, None)])
def test_level_rank(value, expected):
    assert level_rank(value) == expected


def test_status_mit_suffix_und_klammer_kommen_in_den_scope():
    """"B-RSFL+7"/"VA (...)" sind gültige Zielstatus und dürfen nicht an Suffix/Klammer scheitern."""
    res, p = run(
        [klient(1, status="B-RSFL+7"), klient(2, status="VA (vorläufig aufgenommen)"), klient(3, status="N (Asylsuchende)")],
        [entry(1, "2022-01-10"), entry(2, "2022-01-10"), entry(3, "2022-01-10")],
        [],
    )
    # Suffix "+7" entfernt -> B-RSFL ist eligible -> im Scope, nicht "Nicht anwendbar"
    assert p.loc["1", "status_basis"] == "B-RSFL"
    assert p.loc["1", "im_scope"] and p.loc["1", "status"] != STATUS_NA
    # Klammer-Zusatz entfernt -> VA ist eligible -> im Scope
    assert p.loc["2", "status_basis"] == "VA"
    assert p.loc["2", "im_scope"] and p.loc["2", "status"] != STATUS_NA
    # N bleibt (korrekt) ausserhalb der Ziele, wird aber sauber auf "N" normalisiert
    assert p.loc["3", "status_basis"] == "N"
    assert not p.loc["3", "im_scope"]
