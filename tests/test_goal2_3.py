import pandas as pd

from cockpit.base import STATUS_AT_RISK, STATUS_NA, STATUS_ON_TRACK, STATUS_REACHED, prepare_persons
from cockpit.goal1 import evaluate_goal1
from cockpit.goal2 import evaluate_goal2, qualifying_runs
from cockpit.goal3 import evaluate_goal3, free_spells
from cockpit.matrix import call_list, cockpit_matrix
from cockpit.rules import load_rules

T = pd.Timestamp
STICHTAG = T("2026-11-20")


def klient(k, dossier="D1", status="VA", ende="2029-01-01", birth="1990-01-01", sw="SA 1"):
    return {"klientennummer": str(k), "zemis": str(1000 + k), "dossier": dossier, "zust_beginn": T("2020-01-01"),
            "zust_ende": T(ende) if ende else pd.NaT, "uebergang_gemeinde": pd.NaT, "status_aktuell": status,
            "fallfuehrung": sw, "geburtsdatum": T(birth)}


def job(k, von, bis, pensum, arbeitgeber="Coop Bern"):
    return {"zemis": str(1000 + k), "klientennummer": str(k), "von": T(von), "bis": T(bis) if bis else pd.NaT,
            "arbeitgeber": arbeitgeber, "pensum": pensum, "erwerbsstatus": "unselbstständig"}


def entries(*ks, date="2021-01-01"):
    return pd.DataFrame([{"zemis": str(1000 + k), "klientennummer": str(k), "geschaeftsart": "Aufenthalt (Einreise)",
                          "ereignisdatum": T(date)} for k in ks])


def goal2(klienten, jobs=(), edu=(), zemis=()):
    tables = {"klient": pd.DataFrame(klienten), "asylgeschaeftsdaten": entries(*[int(k["klientennummer"]) for k in klienten]),
              "erwerb": pd.DataFrame(list(jobs), columns=["zemis", "klientennummer", "von", "bis", "arbeitgeber", "pensum", "erwerbsstatus"]),
              "integrationsfoerderung": pd.DataFrame(list(edu), columns=["zemis", "klientennummer", "start", "abschluss", "art", "bezeichnung"])}
    if zemis:
        tables["zemis_taetigkeit"] = pd.DataFrame(list(zemis))
    return evaluate_goal2(tables, load_rules(), STICHTAG).persons.set_index("klientennummer")


def test_runs_sum_parallel_jobs_and_bridge_nothing():
    jobs = pd.DataFrame({"von": [T("2024-01-01"), T("2024-01-01"), T("2024-08-01")],
                         "bis_eff": [T("2024-06-30"), T("2024-06-30"), T("2024-12-31")], "pensum": [30, 30, 80]})
    assert qualifying_runs(jobs, 60, True, 0) == [(T("2024-01-01"), T("2024-06-30")), (T("2024-08-01"), T("2024-12-31"))]
    assert qualifying_runs(jobs, 60, False, 0) == [(T("2024-08-01"), T("2024-12-31"))]
    assert qualifying_runs(jobs, 60, True, 40) == [(T("2024-01-01"), T("2024-12-31"))]


def test_goal2_work_education_and_programs():
    p = goal2(
        [klient(1), klient(2), klient(3), klient(4), klient(5)],
        jobs=[job(1, "2024-01-01", "2024-12-31", 80),
              job(2, "2024-01-01", "2024-12-31", 100, "Beschäftigungsprogramm Stadt Bern"),
              job(3, "2024-01-01", "2024-03-31", 100), job(3, "2024-04-01", "2024-07-31", 60),
              job(4, "2024-01-01", "2024-04-30", 100), job(4, "2024-06-01", "2024-09-30", 100)],
        edu=[{"zemis": "1005", "klientennummer": "5", "start": T("2025-08-01"), "abschluss": pd.NaT, "art": "Sek II", "bezeichnung": "Lehre EFZ"}],
    )
    assert p.loc["1", "erreicht_am"] == T("2024-07-01")
    assert pd.isna(p.loc["2", "erreicht_am"])          # 2. Arbeitsmarkt zählt nicht
    assert p.loc["3", "erreicht_am"] == T("2024-07-01")  # zwei Anstellungen nahtlos
    assert pd.isna(p.loc["4", "erreicht_am"])          # Unterbruch im Mai
    assert p.loc["5", "erreicht_am"] == T("2025-08-01") and p.loc["5", "nachweis"].startswith("Sek II")
    assert (p.loc[["1", "3", "5"], "status"] == STATUS_REACHED).all()


def test_goal2_running_job_keeps_case_on_track():
    p = goal2([klient(1, ende="2027-03-01"), klient(2, ende="2027-03-01")],
              jobs=[job(1, "2026-08-01", None, 100), job(2, "2026-11-01", None, 100)])
    assert p.loc["1", "status"] == STATUS_ON_TRACK       # fertig am 01.02.2027 < Frist
    assert p.loc["2", "status"] == STATUS_AT_RISK        # fertig am 01.05.2027 > Frist
    assert "Laufende Anstellung" in p.loc["1", "hinweis"]


def test_goal2_zemis_without_erwerb():
    p = goal2([klient(1)], jobs=[], zemis=[{"zemis": "1001", "klientennummer": "1", "arbeitsbeginn": T("2025-03-01"), "betrieb": "Adecco"}])
    assert "ZEMIS meldet Arbeit ab 01.03.2025" in p.loc["1", "hinweis"]


def test_responsibility_end_is_computed_when_missing():
    tables = {"klient": pd.DataFrame([klient(1, status="B-FL", ende=None), klient(2, status="VA", ende=None)]),
              "asylgeschaeftsdaten": pd.concat([entries(1, 2), pd.DataFrame([{"zemis": "1001", "klientennummer": "1",
                                                "geschaeftsart": "Asylgesuch in CH (Kt normal, Kat. III)", "ereignisdatum": T("2021-01-05")}])])}
    p = prepare_persons(tables, load_rules(), STICHTAG)
    assert p.loc["1", "zust_ende_eff"] == T("2026-01-05")
    assert p.loc["2", "zust_ende_eff"] == T("2028-01-01")
    assert (p["zust_ende_quelle"] == "berechnet").all()


def fin(dossier, art, von, bis=None):
    return {"dossier": dossier, "unterstuetzung": art, "gueltig_von": T(von), "gueltig_bis": T(bis) if bis else pd.NaT}


def test_free_spells():
    rows = pd.DataFrame([fin("D1", "Sozialhilfe", "2022-01-01", "2023-03-31"), fin("D1", "Keine Unterstützung", "2023-04-01"),
                         fin("D1", "Nothilfe", "2024-01-01", "2024-02-29")])
    spells = free_spells(rows, {"sozialhilfe", "nothilfe"}, STICHTAG)
    assert spells == [(T("2023-04-01"), T("2023-12-31")), (T("2024-03-01"), STICHTAG)]


def test_goal3_household():
    tables = {
        "klient": pd.DataFrame([klient(1, "D1"), klient(2, "D1", birth="1992-01-01"), klient(3, "D2"), klient(4, "D3", status="S"), klient(5, "D4")]),
        "asylgeschaeftsdaten": entries(1, 2, 3, 4, 5),
        "finanzielle_unterstuetzung": pd.DataFrame([
            fin("D1", "Sozialhilfe", "2021-03-01", "2024-05-31"), fin("D1", "Keine Unterstützung", "2024-06-01"),
            fin("D2", "Sozialhilfe", "2021-03-01", "2026-03-31"), fin("D2", "Keine Unterstützung", "2026-04-01"),
            fin("D3", "Sozialhilfe", "2021-03-01"),
        ]),
    }
    h = evaluate_goal3(tables, load_rules(), STICHTAG).persons.set_index("dossier")
    assert h.loc["D1", "status"] == STATUS_REACHED and h.loc["D1", "erreicht_am"] == T("2025-06-01")
    assert h.loc["D1", "klientennummer"] == "1" and h.loc["D1", "mitglieder"] == 2
    assert h.loc["D2", "status"] == STATUS_ON_TRACK and "Ohne Sozialhilfe seit 01.04.2026" in h.loc["D2", "hinweis"]
    assert h.loc["D3", "status"] == STATUS_NA
    assert h.loc["D4", "grund_nicht_anwendbar"] == "Keine Daten zur finanziellen Unterstützung"


def test_cockpit_call_list_household_goal_only_for_head():
    rules = load_rules()
    tables = {
        "klient": pd.DataFrame([klient(1, "D1", ende="2027-02-01"), klient(2, "D1", ende="2027-02-01", birth="1993-01-01")]),
        "asylgeschaeftsdaten": entries(1, 2, date="2024-06-01"),
        "sprachstand": pd.DataFrame(columns=["zemis", "klientennummer", "sprache", "niveau", "nachweis", "datum"]),
        "erwerb": pd.DataFrame(columns=["zemis", "klientennummer", "von", "bis", "arbeitgeber", "pensum", "erwerbsstatus"]),
        "finanzielle_unterstuetzung": pd.DataFrame([fin("D1", "Sozialhilfe", "2024-09-01")]),
    }
    persons = prepare_persons(tables, rules, STICHTAG)
    m = cockpit_matrix(evaluate_goal1(tables, rules, STICHTAG, persons), evaluate_goal2(tables, rules, STICHTAG, persons),
                       evaluate_goal3(tables, rules, STICHTAG, persons))
    calls = {c["klientennummer"]: [t for _, t in c["gruende"]] for c in call_list(m)}
    assert any(t.startswith("Ziel 3") for t in calls["1"])
    assert not any(t.startswith("Ziel 3") for t in calls["2"])
    assert all(c["prioritaet"] == "rot" for c in call_list(m))
