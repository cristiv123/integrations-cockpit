"""Gemeinsame Bausteine für die drei Ziele: Personenbasis, Status, Fristen, Ampel, Summen."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

import pandas as pd

from .ingest import Issue

STATUS_REACHED = "Erreicht"
STATUS_REACHED_LATE = "Erreicht nach Frist"
STATUS_ON_TRACK = "Offen – auf Kurs"
STATUS_AT_RISK = "Offen – gefährdet"
STATUS_MISSED = "Frist verpasst"
STATUS_NA = "Nicht anwendbar"
STATUS_ORDER = [STATUS_REACHED, STATUS_REACHED_LATE, STATUS_ON_TRACK, STATUS_AT_RISK, STATUS_MISSED]

AMPEL = {
    STATUS_REACHED: "grün",
    STATUS_REACHED_LATE: "grün",
    STATUS_ON_TRACK: "gelb",
    STATUS_AT_RISK: "rot",
    STATUS_MISSED: "rot",
    STATUS_NA: "grau",
}
AMPEL_RANK = {"rot": 0, "gelb": 1, "grün": 2, "grau": 3}


@dataclass
class GoalResult:
    goal: int
    label: str
    short: str
    unit: str                    # "Person" | "Haushalt"
    persons: pd.DataFrame        # eine Zeile pro Einheit (Person bzw. Haushalt)
    by_worker: pd.DataFrame
    by_entry_year: pd.DataFrame
    totals: dict
    issues: list[Issue]
    stichtag: pd.Timestamp
    columns: dict[str, str] = field(default_factory=dict)  # intern -> Anzeige


def is_missing(v: object) -> bool:
    return v is None or (not isinstance(v, str) and pd.isna(v))


def base_status(value: object, suffix_pattern: str) -> str | None:
    if is_missing(value):
        return None
    return re.sub(suffix_pattern, "", str(value).strip()).strip() or None


def months_between(start: pd.Timestamp, end: pd.Timestamp) -> float | None:
    if pd.isna(start) or pd.isna(end):
        return None
    return round((end - start).days / 30.4375, 1)


def age(birth: pd.Timestamp, at: pd.Timestamp) -> int | None:
    if pd.isna(birth) or pd.isna(at):
        return None
    return at.year - birth.year - ((at.month, at.day) < (birth.month, birth.day))


def with_client(df: pd.DataFrame, klient: pd.DataFrame) -> pd.DataFrame:
    """Klientennummer ergänzen, wo eine Tabelle nur die Zemis-Nr. hat."""
    zemis_to_k = klient.dropna(subset=["zemis", "klientennummer"]).drop_duplicates("zemis").set_index("zemis")["klientennummer"]
    df = df.copy()
    if "klientennummer" not in df.columns:
        df["klientennummer"] = None
    if "zemis" in df.columns:
        missing = df["klientennummer"].isna()
        df.loc[missing, "klientennummer"] = df.loc[missing, "zemis"].map(zemis_to_k)
    return df.dropna(subset=["klientennummer"])


def per_client(df: pd.DataFrame, klient: pd.DataFrame, value_col: str, how: str = "min") -> pd.Series:
    grouped = with_client(df, klient).dropna(subset=[value_col]).groupby("klientennummer")[value_col]
    return pd.to_datetime(grouped.min() if how == "min" else grouped.max())


def status_from_history(history: pd.DataFrame | None, stichtag: pd.Timestamp) -> pd.Series:
    if history is None or history.empty:
        return pd.Series(dtype="object")
    h = history.dropna(subset=["klientennummer"]).copy()
    valid = (h["gueltig_ab"].isna() | (h["gueltig_ab"] <= stichtag)) & (h["gueltig_bis"].isna() | (h["gueltig_bis"] >= stichtag))
    return h[valid].sort_values("gueltig_ab").groupby("klientennummer")["status"].last()


def prepare_persons(tables: dict[str, pd.DataFrame], rules: dict, stichtag: pd.Timestamp) -> pd.DataFrame:
    """Eine Zeile pro Klient:in mit Status, Einreise, Asylgesuch und (ggf. berechnetem) Zuständigkeitsende."""
    klient = tables["klient"].dropna(subset=["klientennummer"]).drop_duplicates("klientennummer").copy()
    p = klient.set_index("klientennummer")

    status = p["status_aktuell"].copy()
    status = status.where(status.notna(), status_from_history(tables.get("asylverfahrensstand"), stichtag).reindex(status.index))
    p["verfahrensstand"] = status
    p["status_basis"] = status.map(lambda v: base_status(v, rules["status"]["strip_suffix_pattern"]))

    entry_cfg = rules["entry"]
    events = tables.get("asylgeschaeftsdaten")
    if events is None:
        events = pd.DataFrame(columns=["zemis", "klientennummer", "geschaeftsart", "ereignisdatum"])
    pick = "min" if entry_cfg.get("pick", "earliest") == "earliest" else "max"
    entry = per_client(events[events["geschaeftsart"] == entry_cfg["event"]], klient, "ereignisdatum", pick)
    for fallback in entry_cfg.get("fallback_events", []):
        entry = entry.combine_first(per_client(events[events["geschaeftsart"] == fallback], klient, "ereignisdatum", pick))
    p["einreise"] = pd.to_datetime(entry.reindex(p.index))
    applications = events[events["geschaeftsart"].astype(str).str.contains(entry_cfg["application_event_pattern"], regex=True, na=False)]
    p["asylgesuch"] = pd.to_datetime(per_client(applications, klient, "ereignisdatum").reindex(p.index))

    computed = [_responsibility_end(r, rules["responsibility"]) for _, r in p.iterrows()]
    p["zust_ende_eff"] = pd.to_datetime(p["zust_ende"].where(p["zust_ende"].notna(), pd.Series(computed, index=p.index)))
    p["zust_ende_quelle"] = ["Export" if pd.notna(e) else "berechnet" if pd.notna(c) else None for e, c in zip(p["zust_ende"], computed)]
    p["alter_stichtag"] = [age(b, stichtag) for b in p["geburtsdatum"]]
    p["einreisejahr"] = p["einreise"].dt.year.astype("Int64")
    return p


def _responsibility_end(r: pd.Series, cfg: dict) -> pd.Timestamp | None:
    status = r["status_basis"]
    if is_missing(status):
        return None
    if status in cfg.get("years_from_application", {}) and pd.notna(r["asylgesuch"]):
        return r["asylgesuch"] + pd.DateOffset(years=int(cfg["years_from_application"][status]))
    if status in cfg.get("years_from_entry", {}) and pd.notna(r["einreise"]):
        change = pd.Timestamp(cfg.get("rule_change_date", "2100-01-01"))
        years = cfg.get("years_from_entry_after_change", {}).get(status) if r["einreise"] >= change else None
        return r["einreise"] + pd.DateOffset(years=int(years or cfg["years_from_entry"][status]))
    return None


def scope_reason(r: pd.Series, stichtag: pd.Timestamp, cc: dict, eligible: set[str], min_age: int | None,
                 needs: tuple[str, ...] = ("einreise", "geburtsdatum")) -> str | None:
    if cc.get("require_responsibility_active") and pd.notna(r["zust_ende_eff"]) and r["zust_ende_eff"] < stichtag:
        return "Zuständigkeit beendet"
    if cc.get("exclude_after_handover") and pd.notna(r["uebergang_gemeinde"]) and r["uebergang_gemeinde"] <= stichtag:
        return "An Gemeinde übergeben"
    if is_missing(r["status_basis"]):
        return "Verfahrensstand unbekannt"
    if r["status_basis"] not in eligible:
        return f"Status {r['status_basis']} nicht Teil der Ziele"
    labels = {"einreise": "Einreisedatum fehlt", "geburtsdatum": "Geburtsdatum fehlt", "frist": "Frist unbekannt (Zuständigkeitsende fehlt)"}
    for col in needs:
        if pd.isna(r[col]):
            return labels.get(col, f"{col} fehlt")
    if min_age is not None and r.get("alter_referenz") is not None and not pd.isna(r.get("alter_referenz")) and r["alter_referenz"] < min_age:
        return f"Unter {min_age} Jahre"
    return None


def apply_scope(p: pd.DataFrame, rules: dict, stichtag: pd.Timestamp, min_age: int | None, needs: tuple[str, ...]) -> None:
    eligible = set(rules["status"]["eligible"])
    cc = rules["current_clients"]
    p["grund_nicht_anwendbar"] = [scope_reason(r, stichtag, cc, eligible, min_age, needs) for _, r in p.iterrows()]
    p["im_scope"] = p["grund_nicht_anwendbar"].isna()
    # Zielgruppe unabhängig davon, ob die Person heute noch Klient:in ist (Mustersuche über frühere Kohorten)
    p["zielgruppe"] = [scope_reason(r, stichtag, {}, eligible, min_age, needs) is None for _, r in p.iterrows()]


def classify(p: pd.DataFrame, stichtag: pd.Timestamp, risk_months: float) -> None:
    """Status und Ampel. Erwartet: im_scope, frist, erreicht_am, optional laufend_fertig_am (projizierter Abschluss)."""
    p["monate_bis_frist"] = [months_between(stichtag, f) for f in p["frist"]]
    projected = p["laufend_fertig_am"] if "laufend_fertig_am" in p.columns else pd.Series(pd.NaT, index=p.index)
    status = []
    for (_, r), proj in zip(p.iterrows(), projected):
        if not r["im_scope"]:
            status.append(STATUS_NA)
        elif pd.notna(r["erreicht_am"]) and r["erreicht_am"] <= stichtag:
            status.append(STATUS_REACHED if r["erreicht_am"] <= r["frist"] else STATUS_REACHED_LATE)
        elif r["frist"] < stichtag:
            status.append(STATUS_MISSED)
        elif r["monate_bis_frist"] <= risk_months and not (pd.notna(proj) and proj <= r["frist"]):
            status.append(STATUS_AT_RISK)
        else:
            status.append(STATUS_ON_TRACK)
    p["status"] = status
    p["ampel"] = p["status"].map(AMPEL)
    p["stichtag_ref"] = stichtag


def summary(scope: pd.DataFrame, by: str, label: str) -> pd.DataFrame:
    if scope.empty:
        return pd.DataFrame(columns=[label])
    counts = pd.crosstab(scope[by].astype("object").fillna("(leer)"), scope["status"]).reindex(columns=STATUS_ORDER, fill_value=0)
    counts.insert(0, "Im Scope", counts.sum(axis=1))
    due = counts[STATUS_REACHED] + counts[STATUS_REACHED_LATE] + counts[STATUS_MISSED]
    counts["Quote fristgerecht (fällige)"] = (counts[STATUS_REACHED] / due.where(due > 0)).round(3)
    counts["Quote erreicht (alle)"] = ((counts[STATUS_REACHED] + counts[STATUS_REACHED_LATE]) / counts["Im Scope"]).round(3)
    counts.index.name = label
    counts.columns.name = None
    return counts.reset_index()


def totals(units: pd.DataFrame, goal: int, unit: str) -> dict:
    scope = units[units["im_scope"]]
    vc = scope["status"].value_counts()
    due = vc.get(STATUS_REACHED, 0) + vc.get(STATUS_REACHED_LATE, 0) + vc.get(STATUS_MISSED, 0)
    plural = "Personen" if unit == "Person" else "Haushalte"
    reached = vc.get(STATUS_REACHED, 0) + vc.get(STATUS_REACHED_LATE, 0)
    closed = units[units["zielgruppe"] & units["frist"].notna() & (units["frist"] <= units["stichtag_ref"])] if "stichtag_ref" in units else units.iloc[0:0]
    closed_ok = (closed["erreicht_am"].notna() & (closed["erreicht_am"] <= closed["frist"])).sum() if len(closed) else 0
    return {
        f"{plural} total": len(units),
        f"Im Scope Ziel {goal}": len(scope),
        **{s: int(vc.get(s, 0)) for s in STATUS_ORDER},
        "Quote fristgerecht (fällige)": round(float(vc.get(STATUS_REACHED, 0) / due), 3) if due else None,
        "Quote erreicht (alle im Scope)": round(float(reached / len(scope)), 3) if len(scope) else None,
        "Abgeschlossene Fälle (Frist abgelaufen, inkl. frühere)": len(closed),
        "Quote fristgerecht (abgeschlossene Fälle)": round(float(closed_ok / len(closed)), 3) if len(closed) else None,
    }


def finish(goal: int, rules_goal: dict, unit: str, p: pd.DataFrame, issues: list[Issue], stichtag: pd.Timestamp,
           columns: dict[str, str]) -> GoalResult:
    units = p.reset_index()
    scope = units[units["im_scope"]]
    return GoalResult(
        goal=goal, label=rules_goal["label"], short=rules_goal.get("short", f"Ziel {goal}"), unit=unit, persons=units,
        by_worker=summary(scope, "fallfuehrung", "Fallführung"), by_entry_year=summary(scope, "einreisejahr", "Einreisejahr"),
        totals=totals(units, goal, unit), issues=issues, stichtag=stichtag, columns=columns,
    )


def restrict(result: GoalResult, mask: pd.Series) -> GoalResult:
    """Teilmenge (z.B. Fälle einer Sozialarbeiter:in) mit neu berechneten Summen."""
    units = result.persons[mask.values]
    scope = units[units["im_scope"]]
    return replace(result, persons=units, by_worker=summary(scope, "fallfuehrung", "Fallführung"),
                   by_entry_year=summary(scope, "einreisejahr", "Einreisejahr"), totals=totals(units, result.goal, result.unit))


def require(tables: dict[str, pd.DataFrame], names: tuple[str, ...], goal: int) -> None:
    missing = [t for t in names if t not in tables]
    if missing:
        raise ValueError(f"Für Ziel {goal} fehlen die Exporte: " + ", ".join(missing))


def scope_issues(p: pd.DataFrame, issues: list[Issue], goal: int, table: str = "Klient") -> None:
    for reason in ("Einreisedatum fehlt", "Geburtsdatum fehlt", "Verfahrensstand unbekannt", "Frist unbekannt (Zuständigkeitsende fehlt)"):
        n = int((p["grund_nicht_anwendbar"] == reason).sum())
        if n:
            issues.append(Issue("Warnung", table, f"Ziel {goal}: {reason} – kann nicht beurteilt werden", n))
