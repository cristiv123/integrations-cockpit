"""Ziel 3: 12 Monate ohne Sozialhilfe für den ganzen Haushalt (Dossier), vor Zuständigkeitsende."""

from __future__ import annotations

import pandas as pd

from .base import GoalResult, apply_scope, classify, finish, per_client, prepare_persons, require, scope_issues
from .ingest import Issue

REQUIRED_TABLES = ("klient", "finanzielle_unterstuetzung")
DAY = pd.Timedelta(days=1)

COLUMNS = {
    "ampel": "Ampel",
    "status": "Status Ziel 3",
    "dossier": "Dossier-Nr.",
    "klientennummer": "Klientennummer Dossierträger/-in",
    "fallfuehrung": "Fallführung",
    "verfahrensstand": "Verfahrensstand Dossierträger/-in",
    "mitglieder": "Personen im Haushalt",
    "einreise": "Einreisedatum",
    "einreisejahr": "Einreisejahr",
    "frist": "Frist Ziel 3 (Zuständigkeitsende)",
    "monate_bis_frist": "Monate bis Frist",
    "unterstuetzung_aktuell": "Unterstützung (aktuell)",
    "erreicht_am": "Ziel 3 erreicht am",
    "nachweis": "Nachweis",
    "quelle": "Quelle",
    "hinweis": "Hinweis",
    "grund_nicht_anwendbar": "Grund nicht anwendbar",
}


def free_spells(rows: pd.DataFrame, assistance: set[str], stichtag: pd.Timestamp) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Zeiträume ohne Sozialhilfe zwischen dem ersten erfassten Eintrag und dem Stichtag."""
    rows = rows.dropna(subset=["gueltig_von"])
    if rows.empty:
        return []
    start = rows["gueltig_von"].min()
    help_rows = rows[rows["unterstuetzung"].astype(str).str.strip().str.lower().isin(assistance)]
    intervals = sorted((v, (b if pd.notna(b) else stichtag)) for v, b in zip(help_rows["gueltig_von"], help_rows["gueltig_bis"]))
    spells, cursor = [], start
    for v, b in intervals:
        if v > cursor:
            spells.append((cursor, min(v - DAY, stichtag)))
        cursor = max(cursor, b + DAY)
    if cursor <= stichtag:
        spells.append((cursor, stichtag))
    return [(s, e) for s, e in spells if s <= e and s <= stichtag]


def household_heads(tables: dict[str, pd.DataFrame], persons: pd.DataFrame, stichtag: pd.Timestamp) -> pd.Series:
    """Dossier-Nr. -> Klientennummer der Dossierträger:in (sonst älteste Person im Dossier)."""
    heads: dict[str, str] = {}
    dp = tables.get("dossierperson")
    if dp is not None and not dp.empty:
        active = dp[(dp["bis"].isna() | (dp["bis"] >= stichtag)) & dp["beziehung"].astype(str).str.startswith("Dossierträger")]
        heads = active.dropna(subset=["dossier", "klientennummer"]).drop_duplicates("dossier").set_index("dossier")["klientennummer"].to_dict()
    oldest = persons.dropna(subset=["dossier"]).sort_values("geburtsdatum").reset_index().drop_duplicates("dossier").set_index("dossier")["klientennummer"]
    for dossier, k in oldest.items():
        if dossier not in heads or heads[dossier] not in persons.index:
            heads[dossier] = k
    return pd.Series(heads, dtype="object")


def evaluate_goal3(tables: dict[str, pd.DataFrame], rules: dict, stichtag: pd.Timestamp,
                   persons: pd.DataFrame | None = None) -> GoalResult:
    stichtag = pd.Timestamp(stichtag).normalize()
    require(tables, REQUIRED_TABLES, 3)
    g3 = rules["goal3"]
    issues: list[Issue] = []
    klient = tables["klient"].dropna(subset=["klientennummer"]).drop_duplicates("klientennummer")
    persons = persons if persons is not None else prepare_persons(tables, rules, stichtag)

    heads = household_heads(tables, persons, stichtag)
    heads = heads[heads.isin(persons.index)]
    h = persons.loc[heads.values].copy()
    h["dossier"] = heads.index
    h = h.reset_index().set_index("dossier")
    members = persons.dropna(subset=["dossier"]).groupby("dossier")
    h["mitglieder"] = members.size().reindex(h.index)
    mode = g3.get("household_deadline", "dossiertraeger")
    if mode in ("latest", "earliest"):
        agg = members["zust_ende_eff"].max() if mode == "latest" else members["zust_ende_eff"].min()
        h["frist"] = agg.reindex(h.index)
    else:
        h["frist"] = h["zust_ende_eff"]

    fin = tables["finanzielle_unterstuetzung"].dropna(subset=["dossier"])
    assistance = {a.lower() for a in g3["assistance_types"]}
    months = int(g3["min_months"])
    reached, running_since, running_done, has_data = {}, {}, {}, set(fin["dossier"])
    for dossier, rows in fin.groupby("dossier"):
        for start, end in free_spells(rows, assistance, stichtag):
            done = start + pd.DateOffset(months=months)
            if done - DAY <= end:
                reached.setdefault(dossier, done)
            elif end >= stichtag:
                running_since[dossier], running_done[dossier] = start, done

    paid = pd.Series(dtype="datetime64[ns]")
    zer = tables.get("integrationszielerreichung")
    if zer is not None and not zer.empty:
        by_person = per_client(zer[zer["ziel"].astype(str).str.contains(g3["reached_goal_pattern"], regex=True, na=False)], klient, "erreicht_am")
        paid = by_person.rename("d").to_frame().join(persons["dossier"]).groupby("dossier")["d"].min()

    h["finanz_erreicht"] = pd.to_datetime(pd.Series(reached, dtype="datetime64[ns]")).reindex(h.index)
    h["zielerreichung"] = pd.to_datetime(paid).reindex(h.index)
    h["erreicht_am"] = h[["finanz_erreicht", "zielerreichung"]].min(axis=1)
    h["laufend_fertig_am"] = pd.to_datetime(pd.Series(running_done, dtype="datetime64[ns]")).reindex(h.index)
    h["nachweis"] = [f"Ohne Sozialhilfe seit {f - pd.DateOffset(months=months):%d.%m.%Y}" if pd.notna(f) and f == r
                     else "Zielerreichung" if pd.notna(r) else None for f, r in zip(h["finanz_erreicht"], h["erreicht_am"])]
    h["quelle"] = [", ".join(n for n, v in (("Finanzielle Unterstützung", f), ("Zielerreichung", z)) if pd.notna(v)) or None
                   for f, z in zip(h["finanz_erreicht"], h["zielerreichung"])]
    h["hinweis"] = [f"Ohne Sozialhilfe seit {running_since[d]:%d.%m.%Y} – Ziel am {running_done[d]:%d.%m.%Y} erfüllt"
                    if d in running_since and pd.isna(r) else None for d, r in zip(h.index, h["erreicht_am"])]

    apply_scope(h, rules, stichtag, None, ("frist",))
    no_data = h["im_scope"] & ~h.index.isin(list(has_data))
    if no_data.sum():
        issues.append(Issue("Warnung", "Finanzielle Unterstützung", "Haushalt ohne Einträge – Ziel 3 kann nicht beurteilt werden", int(no_data.sum())))
        h.loc[no_data, "grund_nicht_anwendbar"] = "Keine Daten zur finanziellen Unterstützung"
        h.loc[no_data, "im_scope"] = False
    h.loc[~h.index.isin(list(has_data)), "zielgruppe"] = False
    classify(h, stichtag, float(g3.get("risk_months", 12)))
    scope_issues(h, issues, 3)
    h.index.name = "dossier"
    return finish(3, g3, "Haushalt", h, issues, stichtag, COLUMNS)
