"""Ziel 2: 6 Monate Arbeit ≥ 60 % am Stück oder Ausbildung Sek II / Tertiär, vor Zuständigkeitsende (VA/FL ab 16)."""

from __future__ import annotations

import pandas as pd

from .base import GoalResult, age, apply_scope, classify, finish, per_client, prepare_persons, require, scope_issues, with_client
from .ingest import Issue

REQUIRED_TABLES = ("klient",)
DAY = pd.Timedelta(days=1)

COLUMNS = {
    "ampel": "Ampel",
    "status": "Status Ziel 2",
    "klientennummer": "Klientennummer",
    "zemis": "Zemis-Nr.",
    "dossier": "Dossier-Nr.",
    "fallfuehrung": "Fallführung",
    "verfahrensstand": "Verfahrensstand",
    "alter_stichtag": "Alter am Stichtag",
    "einreise": "Einreisedatum",
    "einreisejahr": "Einreisejahr",
    "frist": "Frist Ziel 2 (Zuständigkeitsende)",
    "zust_ende_quelle": "Frist-Quelle",
    "monate_bis_frist": "Monate bis Frist",
    "erreicht_am": "Ziel 2 erreicht am",
    "nachweis": "Nachweis",
    "quelle": "Quelle",
    "hinweis": "Hinweis",
    "grund_nicht_anwendbar": "Grund nicht anwendbar",
}


def qualifying_runs(jobs: pd.DataFrame, min_pensum: float, sum_parallel: bool, max_gap_days: int) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Zeiträume (inkl. Enddatum), in denen das Pensum >= min_pensum ist; Lücken bis max_gap_days werden überbrückt."""
    if jobs.empty:
        return []
    if sum_parallel:
        deltas: dict[pd.Timestamp, float] = {}
        for von, bis, pensum in jobs[["von", "bis_eff", "pensum"]].itertuples(index=False):
            deltas[von] = deltas.get(von, 0) + pensum
            deltas[bis + DAY] = deltas.get(bis + DAY, 0) - pensum
        segments, level = [], 0.0
        days = sorted(deltas)
        for start, nxt in zip(days, days[1:]):
            level += deltas[start]
            if level >= min_pensum - 1e-9:
                segments.append((start, nxt - DAY))
    else:
        big = jobs[jobs["pensum"] >= min_pensum]
        segments = sorted(zip(big["von"], big["bis_eff"]))

    runs: list[list[pd.Timestamp]] = []
    for start, end in sorted(segments):
        if runs and start <= runs[-1][1] + DAY + pd.Timedelta(days=max_gap_days):
            runs[-1][1] = max(runs[-1][1], end)
        else:
            runs.append([start, end])
    return [(s, e) for s, e in runs]


def evaluate_goal2(tables: dict[str, pd.DataFrame], rules: dict, stichtag: pd.Timestamp,
                   persons: pd.DataFrame | None = None) -> GoalResult:
    stichtag = pd.Timestamp(stichtag).normalize()
    require(tables, REQUIRED_TABLES, 2)
    if "erwerb" not in tables and "integrationsfoerderung" not in tables:
        raise ValueError("Für Ziel 2 fehlen die Exporte: Erwerb und/oder Integrationsförderung und Ausbildung")
    g2 = rules["goal2"]
    issues: list[Issue] = []
    klient = tables["klient"].dropna(subset=["klientennummer"]).drop_duplicates("klientennummer")
    p = (persons if persons is not None else prepare_persons(tables, rules, stichtag)).copy()
    p["frist"] = p["zust_ende_eff"]
    age_ref = {"entry": p["einreise"], "deadline": p["frist"]}.get(g2.get("age_reference"), pd.Series(stichtag, index=p.index))
    p["alter_referenz"] = [age(b, r) for b, r in zip(p["geburtsdatum"], age_ref)]

    months = int(g2["min_months"])
    work_reached, running_since, running_done = {}, {}, {}
    erwerb = tables.get("erwerb")
    jobs = all_jobs = pd.DataFrame()
    if erwerb is not None and not erwerb.empty:
        jobs = with_client(erwerb, klient).dropna(subset=["von"]).copy()
        jobs["bis_eff"] = jobs["bis"].fillna(stichtag).clip(upper=stichtag)
        all_jobs = jobs
        jobs["pensum"] = pd.to_numeric(jobs["pensum"], errors="coerce")
        no_pensum = jobs["pensum"].isna().sum()
        if no_pensum:
            issues.append(Issue("Warnung", "Erwerb", "Anstellung ohne Pensum – zählt nicht für Ziel 2", int(no_pensum)))
        jobs = jobs.dropna(subset=["pensum"])
        jobs = jobs[jobs["von"] <= jobs["bis_eff"]]
        allowed = {s.lower() for s in g2.get("erwerbsstatus_counts", [])}
        if allowed:
            jobs = jobs[jobs["erwerbsstatus"].isna() | jobs["erwerbsstatus"].astype(str).str.lower().isin(allowed)]
        if g2.get("exclude_employer_pattern"):
            second = jobs["arbeitgeber"].astype(str).str.contains(g2["exclude_employer_pattern"], regex=True, na=False)
            if second.sum():
                issues.append(Issue("Info", "Erwerb", "Anstellungen im 2. Arbeitsmarkt (Programm) – zählen nicht für Ziel 2", int(second.sum())))
            jobs = jobs[~second]
        for k, grp in jobs.groupby("klientennummer"):
            for start, end in qualifying_runs(grp, float(g2["min_pensum"]), bool(g2.get("sum_parallel_jobs", True)), int(g2.get("max_gap_days", 0))):
                done = start + pd.DateOffset(months=months)
                if done - DAY <= end:
                    work_reached.setdefault(k, done)
                elif end >= stichtag:
                    running_since[k], running_done[k] = start, done

    edu_reached, edu_label = pd.Series(dtype="datetime64[ns]"), pd.Series(dtype="object")
    ifa = tables.get("integrationsfoerderung")
    if ifa is not None and not ifa.empty:
        types = {t.lower() for t in g2["education_types"]}
        col = "abschluss" if g2.get("education_counts_from") == "abschluss" else "start"
        edu = with_client(ifa[ifa["art"].astype(str).str.strip().str.lower().isin(types)], klient).dropna(subset=[col])
        edu = edu[edu[col] <= stichtag].sort_values(col).groupby("klientennummer").first()
        edu_reached = pd.to_datetime(edu[col])
        edu_label = edu["art"].astype(str) + ": " + edu["bezeichnung"].astype(str)

    paid = pd.Series(dtype="datetime64[ns]")
    zer = tables.get("integrationszielerreichung")
    if zer is not None and not zer.empty:
        paid = per_client(zer[zer["ziel"].astype(str).str.contains(g2["reached_goal_pattern"], regex=True, na=False)], klient, "erreicht_am")

    p["arbeit_erreicht"] = pd.to_datetime(pd.Series(work_reached, dtype="datetime64[ns]")).reindex(p.index)
    p["ausbildung_erreicht"] = edu_reached.reindex(p.index)
    p["zielerreichung"] = paid.reindex(p.index)
    p["erreicht_am"] = p[["arbeit_erreicht", "ausbildung_erreicht", "zielerreichung"]].min(axis=1)
    p["laufend_fertig_am"] = pd.to_datetime(pd.Series(running_done, dtype="datetime64[ns]")).reindex(p.index)
    p["nachweis"] = [
        (f"Arbeit ≥ {g2['min_pensum']} % seit {a - pd.DateOffset(months=months):%d.%m.%Y}" if pd.notna(a) and a == r
         else edu_label.get(k) if pd.notna(e) and e == r else "Zielerreichung" if pd.notna(r) else None)
        for k, a, e, r in zip(p.index, p["arbeit_erreicht"], p["ausbildung_erreicht"], p["erreicht_am"])
    ]
    p["quelle"] = [", ".join(n for n, v in (("Erwerb", a), ("Ausbildung", e), ("Zielerreichung", z)) if pd.notna(v)) or None
                   for a, e, z in zip(p["arbeit_erreicht"], p["ausbildung_erreicht"], p["zielerreichung"])]

    hints = {k: [] for k in p.index}
    for k, since in running_since.items():
        if k in hints and pd.isna(p.at[k, "erreicht_am"]):
            hints[k].append(f"Laufende Anstellung ≥ {g2['min_pensum']} % seit {since:%d.%m.%Y} – Ziel am {running_done[k]:%d.%m.%Y} erfüllt")
    _zemis_check(tables, klient, all_jobs, hints, issues)
    p["hinweis"] = [" · ".join(h) or None for h in (hints[k] for k in p.index)]

    apply_scope(p, rules, stichtag, int(g2["min_age"]), ("geburtsdatum", "frist"))
    classify(p, stichtag, float(g2.get("risk_months", 12)))
    scope_issues(p, issues, 2)
    computed = int((p["im_scope"] & (p["zust_ende_quelle"] == "berechnet")).sum())
    if computed:
        issues.append(Issue("Info", "Klient", "Ziel 2/3: Zuständigkeitsende fehlt im Export – aus Status und Daten berechnet", computed))
    return finish(2, g2, "Person", p, issues, stichtag, COLUMNS)


def _zemis_check(tables: dict, klient: pd.DataFrame, jobs: pd.DataFrame, hints: dict, issues: list[Issue]) -> None:
    """ZEMIS-Tätigkeit ohne passende Anstellung in Erwerb = möglicherweise nicht erfasste Arbeit."""
    zt = tables.get("zemis_taetigkeit")
    if zt is None or zt.empty:
        return
    zt = with_client(zt, klient).dropna(subset=["arbeitsbeginn"])
    tolerance = pd.Timedelta(days=31)
    by_client = {k: g for k, g in jobs.groupby("klientennummer")} if not jobs.empty else {}
    missing = 0
    for k, start, betrieb in zt[["klientennummer", "arbeitsbeginn", "betrieb"]].itertuples(index=False):
        g = by_client.get(k)
        if g is not None and ((g["von"] <= start + tolerance) & (g["bis_eff"] >= start - tolerance)).any():
            continue
        missing += 1
        if k in hints:
            hints[k].append(f"ZEMIS meldet Arbeit ab {start:%d.%m.%Y} ({betrieb}) – nicht in Erwerb")
    if missing:
        issues.append(Issue("Warnung", "ZEMIS Tätigkeit", "Beim Bund gemeldete Arbeit ohne passende Anstellung in Erwerb – prüfen", missing))
