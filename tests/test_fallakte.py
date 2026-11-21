"""Tests für die Fallakte-Aufbereitung (cockpit/fallakte.py).

Kleine, von Hand gebaute Tabellen – kein Zugriff auf data/synthetic. Es wird nur geprüft,
dass die Fallakte die bereits berechneten Ziel-Ampeln übernimmt und den Zeitstrahl korrekt
aus den Rohtabellen zusammensetzt (keine neuen Regeln).
"""

import pandas as pd

from cockpit.base import STATUS_REACHED
from cockpit.fallakte import PENSUM_HERVORHEBUNG, build_fallakte, person_options
from cockpit.goal1 import evaluate_goal1
from cockpit.goal2 import evaluate_goal2
from cockpit.goal3 import evaluate_goal3
from cockpit.rules import load_rules

T = pd.Timestamp
STICHTAG = T("2026-11-20")


def make_tables():
    klient = pd.DataFrame([{
        "klientennummer": "1", "zemis": "1001", "dossier": "D1",
        "zust_beginn": T("2020-01-01"), "zust_ende": T("2030-01-01"), "uebergang_gemeinde": pd.NaT,
        "status_aktuell": "VA", "fallfuehrung": "SA 1", "geburtsdatum": T("1990-01-01"),
    }])
    events = pd.DataFrame([
        {"zemis": "1001", "klientennummer": "1", "geschaeftsart": "Aufenthalt (Einreise)", "ereignisdatum": T("2022-01-10")},
    ])
    sprachstand = pd.DataFrame([
        {"zemis": "1001", "klientennummer": "1", "sprache": "Deutsch", "niveau": "A1",
         "nachweis": "Zertifikat telc", "datum": T("2024-05-01")},
    ])
    erwerb = pd.DataFrame([
        {"zemis": "1001", "klientennummer": "1", "von": T("2023-01-01"), "bis": T("2023-12-31"),
         "arbeitgeber": "Firma A", "pensum": 80, "erwerbsstatus": "unselbstständig"},
        {"zemis": "1001", "klientennummer": "1", "von": T("2024-01-01"), "bis": T("2024-06-30"),
         "arbeitgeber": "Firma B", "pensum": 40, "erwerbsstatus": "unselbstständig"},
    ])
    integrationsfoerderung = pd.DataFrame([
        {"zemis": "1001", "klientennummer": "1", "start": T("2022-06-01"), "abschluss": T("2022-12-01"),
         "art": "Sek II", "bezeichnung": "Lehre", "stunden": 40, "institution": "GIBB"},
    ])
    finanzielle_unterstuetzung = pd.DataFrame([
        {"dossier": "D1", "unterstuetzung": "Sozialhilfe", "gueltig_von": T("2022-02-01"),
         "gueltig_bis": T("2023-02-01"), "hauptgrund_beendigung": "Erwerb"},
    ])
    return {
        "klient": klient, "asylgeschaeftsdaten": events, "sprachstand": sprachstand,
        "erwerb": erwerb, "integrationsfoerderung": integrationsfoerderung,
        "finanzielle_unterstuetzung": finanzielle_unterstuetzung,
    }


def make_results(tables):
    rules = load_rules()
    return {
        1: evaluate_goal1(tables, rules, STICHTAG),
        2: evaluate_goal2(tables, rules, STICHTAG),
        3: evaluate_goal3(tables, rules, STICHTAG),
    }


def test_basisfelder_und_ampeln_aus_ergebnissen():
    tables = make_tables()
    results = make_results(tables)
    fa = build_fallakte(tables, STICHTAG, "1", results)

    assert fa.klientennummer == "1"
    assert fa.dossier == "D1"
    assert fa.verfahrensstand == "VA"
    # Alle drei Ziele vorhanden und mit einem Status versehen
    assert {z["goal"] for z in fa.ziele} == {1, 2, 3}
    assert all(z["status"] is not None and z["ampel"] is not None for z in fa.ziele)
    # Ziel 1: A1 am 01.05.2024 vor Frist (10.01.2025) -> erreicht; identisch zum Ziel-Ergebnis
    z1 = next(z for z in fa.ziele if z["goal"] == 1)
    assert z1["status"] == STATUS_REACHED
    p1 = results[1].persons.set_index("klientennummer")
    assert z1["status"] == p1.loc["1", "status"]


def test_zeitstrahl_spuren_und_pensum_hervorhebung():
    tables = make_tables()
    fa = build_fallakte(tables, STICHTAG, "1", make_results(tables))
    ev = fa.ereignisse

    sprache = ev[ev["spur"] == "Sprache"]
    assert len(sprache) == 1 and sprache.iloc[0]["typ"] == "punkt" and sprache.iloc[0]["label"] == "A1"

    arbeit = ev[ev["spur"] == "Arbeit"]
    assert len(arbeit) == 2
    # Genau die 80-%-Stelle (>= 60) ist hervorgehoben, die 40-%-Stelle nicht
    assert arbeit["hervorgehoben"].sum() == 1
    hervor = arbeit[arbeit["hervorgehoben"]].iloc[0]
    assert hervor["label"] == "80 %"
    assert PENSUM_HERVORHEBUNG == 60.0

    assert len(ev[ev["spur"] == "Kurse & Ausbildung"]) == 1
    # Sozialhilfe wird über das Dossier (Haushalt) gezogen
    assert len(ev[ev["spur"] == "Sozialhilfe (Haushalt)"]) == 1


def test_marker_enthalten_schluesseldaten():
    tables = make_tables()
    fa = build_fallakte(tables, STICHTAG, "1", make_results(tables))
    assert {"Einreise", "Frist A1", "Zuständigkeitsende", "Heute"} <= set(fa.marker)
    # Frist A1 = Einreise + 3 Jahre
    assert fa.marker["Frist A1"] == fa.marker["Einreise"] + pd.DateOffset(years=3)
    assert fa.marker["Heute"] == STICHTAG


def test_person_options_liste():
    tables = make_tables()
    opts = person_options(make_results(tables))
    assert [o["klientennummer"] for o in opts] == ["1"]
    assert opts[0]["verfahrensstand"] == "VA"
    assert opts[0]["alter"] == 36  # geboren 1990, Stichtag 2026


def test_fehlende_tabelle_kein_absturz():
    tables = make_tables()
    results = make_results(tables)
    tables.pop("erwerb")  # Zeitstrahl muss auch ohne eine Quelle funktionieren
    fa = build_fallakte(tables, STICHTAG, "1", results)
    assert fa.ereignisse[fa.ereignisse["spur"] == "Arbeit"].empty
    assert len(fa.ereignisse[fa.ereignisse["spur"] == "Sprache"]) == 1
