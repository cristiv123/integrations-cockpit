"""Cockpit: alle drei Ziele pro Person und die Anrufliste für Sozialarbeitende."""

from __future__ import annotations

import pandas as pd

from .base import AMPEL_RANK, STATUS_AT_RISK, STATUS_ON_TRACK, GoalResult

OPEN = (STATUS_AT_RISK, STATUS_ON_TRACK)


def cockpit_matrix(r1: GoalResult, r2: GoalResult | None, r3: GoalResult | None) -> pd.DataFrame:
    m = r1.persons[["klientennummer", "zemis", "dossier", "fallfuehrung", "verfahrensstand", "alter_stichtag"]].copy()
    m = _join(m, r1, 1, "klientennummer")
    if r2 is not None:
        m = _join(m, r2, 2, "klientennummer")
    if r3 is not None:
        m = _join(m, r3, 3, "dossier")
        heads = set(r3.persons["klientennummer"])
        m["z3_scope"] = m["z3_scope"] & m["klientennummer"].isin(heads)
    scopes = [c for c in m.columns if c.endswith("_scope")]
    m = m[m[scopes].fillna(False).any(axis=1)].copy()

    goals = [g for g in (1, 2, 3) if f"z{g}_status" in m.columns]
    is_open = {g: m[f"z{g}_scope"].fillna(False).astype(bool) & m[f"z{g}_status"].isin(OPEN) for g in goals}
    open_ampeln = pd.concat([m[f"z{g}_ampel"].where(is_open[g]) for g in goals], axis=1)
    m["prioritaet"] = open_ampeln.apply(lambda row: min((a for a in row if isinstance(a, str)), key=AMPEL_RANK.get, default=None), axis=1)
    m["naechste_offene_frist"] = pd.concat([m[f"z{g}_frist"].where(is_open[g]) for g in goals], axis=1).min(axis=1)
    return m.sort_values(["prioritaet", "naechste_offene_frist"], key=lambda s: s.map(AMPEL_RANK) if s.name == "prioritaet" else s,
                         na_position="last").reset_index(drop=True)


def _join(m: pd.DataFrame, r: GoalResult, goal: int, key: str) -> pd.DataFrame:
    cols = {"status": f"z{goal}_status", "ampel": f"z{goal}_ampel", "frist": f"z{goal}_frist", "monate_bis_frist": f"z{goal}_monate",
            "im_scope": f"z{goal}_scope"}
    if "hinweis" in r.persons.columns:
        cols["hinweis"] = f"z{goal}_hinweis"
    part = r.persons[[key, *cols]].drop_duplicates(key).rename(columns=cols)
    return m.merge(part, on=key, how="left")


WHY = {
    1: "kein anerkannter A1-Nachweis",
    2: "noch keine 6 Monate Arbeit ≥ 60 % bzw. Ausbildung Sek II/Tertiär",
    3: "Haushalt noch nicht 12 Monate ohne Sozialhilfe",
}


def call_list(m: pd.DataFrame, limit: int = 15) -> list[dict]:
    """Wen rufe ich diese Woche an – und warum? Rot vor gelb, dann nach nächster offener Frist."""
    out = []
    for _, r in m[m["prioritaet"].notna()].head(limit).iterrows():
        reasons = []
        for g in (1, 2, 3):
            if r.get(f"z{g}_status") in OPEN and r.get(f"z{g}_scope"):
                text = f"Ziel {g}: {WHY[g]} – Frist {r[f'z{g}_frist']:%d.%m.%Y} (in {r[f'z{g}_monate']:.0f} Monaten)"
                hint = r.get(f"z{g}_hinweis")
                if isinstance(hint, str):
                    text += f". {hint}"
                reasons.append((r[f"z{g}_ampel"], text))
        out.append({"klientennummer": r["klientennummer"], "verfahrensstand": r["verfahrensstand"], "alter": r["alter_stichtag"],
                    "prioritaet": r["prioritaet"], "gruende": sorted(reasons, key=lambda x: AMPEL_RANK[x[0]])})
    return out


MATRIX_COLUMNS = {
    "prioritaet": "Priorität",
    "klientennummer": "Klientennummer",
    "zemis": "Zemis-Nr.",
    "dossier": "Dossier-Nr.",
    "fallfuehrung": "Fallführung",
    "verfahrensstand": "Verfahrensstand",
    "alter_stichtag": "Alter",
    "z1_status": "Ziel 1 · Sprache",
    "z1_frist": "Frist Ziel 1",
    "z2_status": "Ziel 2 · Arbeit/Ausbildung",
    "z2_frist": "Frist Ziel 2",
    "z3_status": "Ziel 3 · ohne Sozialhilfe (Haushalt)",
    "z3_frist": "Frist Ziel 3",
    "naechste_offene_frist": "Nächste offene Frist",
}


def matrix_table(m: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in MATRIX_COLUMNS if c in m.columns]
    return m[cols].rename(columns=MATRIX_COLUMNS)
