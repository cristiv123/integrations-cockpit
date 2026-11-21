"""Ziel 1: Sprache A1 innert 3 Jahren ab Einreise (VA/FL ab 16)."""

from __future__ import annotations

import re

import pandas as pd

from .base import (AMPEL, STATUS_AT_RISK, STATUS_MISSED, STATUS_NA, STATUS_ON_TRACK, STATUS_REACHED,  # noqa: F401
                   STATUS_REACHED_LATE, GoalResult, age, apply_scope, classify, finish, per_client, prepare_persons,
                   require, restrict, scope_issues, with_client)
from .ingest import Issue

LEVELS = ["A0", "A1", "A2", "B1", "B2", "C1", "C2"]
REQUIRED_TABLES = ("klient", "asylgeschaeftsdaten", "sprachstand")

COLUMNS = {
    "ampel": "Ampel",
    "status": "Status Ziel 1",
    "klientennummer": "Klientennummer",
    "zemis": "Zemis-Nr.",
    "dossier": "Dossier-Nr.",
    "fallfuehrung": "Fallführung",
    "verfahrensstand": "Verfahrensstand",
    "geburtsdatum": "Geburtsdatum",
    "alter_stichtag": "Alter am Stichtag",
    "einreise": "Einreisedatum",
    "einreisejahr": "Einreisejahr",
    "frist": "Frist Ziel 1",
    "monate_bis_frist": "Monate bis Frist",
    "erreicht_am": "A1 erreicht am",
    "nachweis": "Nachweis",
    "quelle": "Quelle",
    "grund_nicht_anwendbar": "Grund nicht anwendbar",
}


def level_rank(value: object) -> int | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    m = re.match(r"\s*([ABC][0-2])", str(value).upper())
    return LEVELS.index(m.group(1)) if m and m.group(1) in LEVELS else None


def evaluate_goal1(tables: dict[str, pd.DataFrame], rules: dict, stichtag: pd.Timestamp,
                   persons: pd.DataFrame | None = None) -> GoalResult:
    stichtag = pd.Timestamp(stichtag).normalize()
    require(tables, REQUIRED_TABLES, 1)
    issues: list[Issue] = []
    g1 = rules["goal1"]
    klient = tables["klient"].dropna(subset=["klientennummer"]).drop_duplicates("klientennummer")
    p = (persons if persons is not None else prepare_persons(tables, rules, stichtag)).copy()

    p["frist"] = p["einreise"] + pd.DateOffset(years=int(g1["deadline_years"]))
    age_ref = {"entry": p["einreise"], "deadline": p["frist"]}.get(g1.get("age_reference"), pd.Series(stichtag, index=p.index))
    p["alter_referenz"] = [age(b, r) for b, r in zip(p["geburtsdatum"], age_ref)]

    sprach = tables["sprachstand"].copy()
    min_rank = LEVELS.index(g1["min_level"])
    langs = {s.lower() for s in g1.get("languages", [])}
    proofs = {s.lower() for s in g1.get("accepted_proofs", [])}
    qualifies = sprach["niveau"].map(level_rank).fillna(-1) >= min_rank
    if langs:
        qualifies &= sprach["sprache"].astype(str).str.strip().str.lower().isin(langs)
    if proofs:
        qualifies &= sprach["nachweis"].astype(str).str.strip().str.lower().isin(proofs)
    qual = sprach[qualifies]
    undated = qual["datum"].isna().sum()
    if undated:
        issues.append(Issue("Warnung", "Sprachstand", "Gültiger A1-Nachweis ohne 'Datum Erreichung' – zählt nicht", int(undated)))
    first_proof = with_client(qual.dropna(subset=["datum"]), klient).sort_values("datum").groupby("klientennummer").first()

    reached_paid = pd.Series(dtype="datetime64[ns]")
    zer = tables.get("integrationszielerreichung")
    if zer is not None and not zer.empty:
        reached_paid = per_client(zer[zer["ziel"].astype(str).str.contains(g1["reached_goal_pattern"], regex=True, na=False)],
                                  klient, "erreicht_am")

    p["a1_sprachstand"] = pd.to_datetime(first_proof["datum"]).reindex(p.index)
    p["a1_zielerreichung"] = reached_paid.reindex(p.index)
    p["erreicht_am"] = p[["a1_sprachstand", "a1_zielerreichung"]].min(axis=1)
    p["nachweis"] = (first_proof["nachweis"].astype(str) + " · " + first_proof["niveau"].astype(str)).reindex(p.index)
    p["quelle"] = [
        "Zielerreichung + Sprachstand" if pd.notna(s) and pd.notna(z) else "Zielerreichung" if pd.notna(z) else "Sprachstand" if pd.notna(s) else None
        for s, z in zip(p["a1_sprachstand"], p["a1_zielerreichung"])
    ]

    apply_scope(p, rules, stichtag, int(g1["min_age"]), ("einreise", "geburtsdatum"))
    classify(p, stichtag, float(g1.get("risk_months", 6)))

    scope_issues(p, issues, 1)
    only_paid = p["a1_zielerreichung"].notna() & p["a1_sprachstand"].isna()
    if only_paid.sum():
        issues.append(Issue("Info", "Sprachstand", "Ziel 1 in Zielerreichung erfasst, aber kein passender Sprachstand-Nachweis", int(only_paid.sum())))
    unpaid = p["im_scope"] & p["a1_sprachstand"].notna() & p["a1_zielerreichung"].isna() & (p["a1_sprachstand"] <= p["frist"])
    if unpaid.sum():
        issues.append(Issue("Info", "Integrationszielerreichung",
                            "Ziel 1: A1 fristgerecht nachgewiesen, aber (noch) nicht als erreichtes Ziel erfasst – Abgeltung prüfen", int(unpaid.sum())))
    return finish(1, g1, "Person", p, issues, stichtag, COLUMNS)


__all__ = ["evaluate_goal1", "level_rank", "restrict", "GoalResult", "AMPEL", "STATUS_REACHED", "STATUS_REACHED_LATE",
           "STATUS_ON_TRACK", "STATUS_AT_RISK", "STATUS_MISSED", "STATUS_NA"]
