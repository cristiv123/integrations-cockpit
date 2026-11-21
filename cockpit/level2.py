"""Level 2/3: Was haben Personen bzw. Haushalte gemeinsam, die ein Ziel fristgerecht erreichen?

Ausgewiesen werden nur Gruppen (mind. `min_group_size` Personen), nie ein Wert pro Person.
Zusammenhänge sind beschreibend – sie zeigen, wo genauer hingeschaut werden sollte, nicht Ursachen.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

import pandas as pd

from .base import GoalResult
from .situationsanalyse import FEATURES as SA_FEATURES

NO_SA = "keine Situationsanalyse"
SMALL = "Übrige (kleine Gruppen)"
UNINFORMATIVE = {NO_SA, "unbekannt", "unklar"}
MIN_EXTRA = 0.05
CAVEAT = ("Zusammenhänge sind beschreibend, nicht ursächlich. Kurse und Massnahmen werden gezielt an Personen mit grösserem "
          "Bedarf vergeben – eine tiefere Quote bei Kursbesuchenden heisst nicht, dass der Kurs schadet.")


@dataclass
class Level2Result:
    goal: int
    unit: str
    population: int
    reached: int
    rate: float
    groups: pd.DataFrame        # Merkmal × Gruppe
    strength: pd.DataFrame      # Merkmal-Rangliste
    combinations: pd.DataFrame  # Zweier-Kombinationen
    insights: list[str]
    min_group_size: int


def _bins(values: pd.Series, edges: list[float], labels: list[str]) -> pd.Series:
    return pd.cut(pd.to_numeric(values, errors="coerce"), bins=edges, labels=labels, right=False).astype("object").fillna("unbekannt")


def _months(a: pd.Series, b: pd.Series) -> pd.Series:
    return (b - a).dt.days / 30.4375


def build_features(pop: pd.DataFrame, tables: dict[str, pd.DataFrame], include_case_worker: bool = False) -> pd.DataFrame:
    """Merkmale pro Person (nur intern; ausgegeben werden ausschliesslich Gruppenwerte)."""
    f = pd.DataFrame(index=pop.index)
    age = (pop["einreise"] - pop["geburtsdatum"]).dt.days / 365.25
    f["Alter bei Einreise"] = _bins(age, [0, 16, 25, 35, 45, 200], ["unter 16", "16–24", "25–34", "35–44", "45+"])
    f["Geschlecht"] = pop["geschlecht"].fillna("unbekannt")
    f["Nationalität"] = pop["nationalitaet"].fillna("unbekannt")
    f["Muttersprache"] = pop["muttersprache"].fillna("unbekannt")
    f["Schuljahre vor Einreise"] = _bins(pop["schuljahre"], [0, 4, 9, 12, 100], ["0–3", "4–8", "9–11", "12+"])
    f["Lateinisch alphabetisiert"] = pop["lateinisch_alphabetisiert"].fillna("unbekannt")
    f["Höchste Ausbildung"] = pop["ausbildung"].fillna("unbekannt")
    f["Arbeitserfahrung vor Einreise"] = _bins(pop["arbeitserfahrung"], [0, 1, 6, 100], ["keine", "1–5 Jahre", "6+ Jahre"])
    f["Einreisejahr"] = pop["einreisejahr"].astype("object").fillna("unbekannt")
    if include_case_worker:
        f["Fallführung"] = pop["fallfuehrung"].fillna("unbekannt")

    dp = tables.get("dossierperson")
    if dp is not None and not dp.empty:
        rel = dp.dropna(subset=["klientennummer"]).drop_duplicates("klientennummer").set_index("klientennummer")["beziehung"]
        role = pop["klientennummer"].map(rel)
        f["Rolle im Haushalt"] = role.map(lambda r: "Dossierträger/-in" if r == "Dossierträger/-in"
                                          else "Partner/-in" if isinstance(r, str) and ("Ehe" in r or "Partner" in r or "Konkubinat" in r)
                                          else "Kind" if r == "Tochter / Sohn" else "andere/unbekannt")
        size = dp.groupby("dossier")["klientennummer"].nunique()
        f["Haushaltsgrösse"] = _bins(pop["dossier"].map(size), [1, 2, 3, 5, 100], ["1", "2", "3–4", "5+"])

    klient = tables["klient"].dropna(subset=["klientennummer"]).drop_duplicates("klientennummer")
    births = klient[["dossier", "geburtsdatum"]].dropna()
    small_kids = []
    for _, r in pop.iterrows():
        b = births[births["dossier"] == r["dossier"]]["geburtsdatum"]
        age_at_entry = (r["einreise"] - b).dt.days / 365.25
        small_kids.append("ja" if ((age_at_entry >= -1) & (age_at_entry < 4)).any() else "nein")
    f["Kleinkind (<4) im Haushalt bei Einreise"] = small_kids

    ifa = tables.get("integrationsfoerderung")
    if ifa is not None and not ifa.empty:
        courses = ifa.dropna(subset=["klientennummer", "start"])
        courses = courses[courses["art"].astype(str).str.contains("Deutsch|Sprach|Alphabet", case=False, na=False)]
        merged = courses.merge(pop[["klientennummer", "einreise", "frist"]], on="klientennummer")
        merged = merged[merged["start"] <= merged["frist"]]
        first = merged.groupby("klientennummer").agg(start=("start", "min"), einreise=("einreise", "first"),
                                                     stunden=("stunden", lambda s: pd.to_numeric(s, errors="coerce").max()))
        delay = _months(first["einreise"], first["start"])
        start_label = pd.cut(delay, [-1000, 6.01, 12.01, 1000], labels=["≤ 6 Monate", "7–12 Monate", "> 12 Monate"]).astype("object")
        f["Erster Deutschkurs nach Einreise"] = pop["klientennummer"].map(start_label).fillna("kein Kurs vor Frist")
        intensity = _bins(first["stunden"], [0, 8, 16, 1000], ["< 8 Std./Woche", "8–15 Std./Woche", "16+ Std./Woche"])
        f["Kursintensität (max.)"] = pop["klientennummer"].map(intensity).fillna("kein Kurs vor Frist")
        alpha = set(ifa[ifa["art"].astype(str).str.contains("Alphabet", case=False, na=False)]["klientennummer"].dropna())
        f["Alphabetisierungskurs besucht"] = pop["klientennummer"].isin(alpha).map({True: "ja", False: "nein"})

    ub = tables.get("unterbringung")
    if ub is not None and not ub.empty:
        ub = ub.dropna(subset=["klientennummer", "von"])
        at = pop.set_index("klientennummer")["einreise"] + pd.DateOffset(months=12)
        housing = {}
        for k, grp in ub.groupby("klientennummer"):
            if k not in at.index:
                continue
            t = at[k]
            row = grp[(grp["von"] <= t) & (grp["bis"].isna() | (grp["bis"] >= t))]
            if not row.empty:
                art = str(row.iloc[-1]["art"])
                housing[k] = "Kollektivunterkunft" if "Kollektiv" in art else "Wohnung/WG" if art in ("Wohnung", "WG") else art
        f["Wohnform 12 Monate nach Einreise"] = pop["klientennummer"].map(housing).fillna("unbekannt")

    sa = tables.get("situationsanalyse_merkmale")
    if sa is not None and not sa.empty:
        by_zemis = sa.dropna(subset=["zemis"]).drop_duplicates("zemis").set_index("zemis")
        for feat, spec in SA_FEATURES.items():
            f[f"SA: {spec['label']}"] = pop["zemis"].map(by_zemis[feat]).fillna(NO_SA)
    return f


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (math.nan, math.nan)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (centre - half, centre + half)


def _group_rows(feature: str, labels: pd.Series, outcome: pd.Series, overall: float, k: int) -> list[dict]:
    counts = pd.crosstab(labels, outcome).reindex(columns=[False, True], fill_value=0)
    small = counts[counts.sum(axis=1) < k]
    counts = counts[counts.sum(axis=1) >= k]
    if not small.empty and small.values.sum() >= k:
        counts.loc[SMALL] = small.sum()
    rows = []
    for group, (miss, hit) in counts.iterrows():
        n = int(miss + hit)
        lo, hi = wilson(int(hit), n)
        rate = hit / n
        rows.append({"Merkmal": feature, "Gruppe": str(group), "Personen": n, "Erreicht fristgerecht": int(hit),
                     "Quote": round(rate, 3), "Differenz zu gesamt (Prozentpunkte)": round((rate - overall) * 100, 1),
                     "95%-Intervall von": round(lo, 3), "95%-Intervall bis": round(hi, 3),
                     "Auffällig": "ja" if lo > overall or hi < overall else "nein"})
    return rows


def _cramers_v(labels: pd.Series, outcome: pd.Series) -> float:
    table = pd.crosstab(labels, outcome)
    if table.shape[0] < 2 or table.shape[1] < 2:
        return 0.0
    n = table.values.sum()
    expected = table.sum(axis=1).values[:, None] * table.sum(axis=0).values[None, :] / n
    chi2 = (((table.values - expected) ** 2) / expected).sum()
    return round(math.sqrt(chi2 / n), 3)


def analyse(result: GoalResult, tables: dict[str, pd.DataFrame], rules: dict,
            extra: dict[str, pd.Series] | None = None) -> Level2Result:
    """extra: zusätzliche Merkmale (Label -> Wert pro Klientennummer), z.B. 'A1 erreicht' für Ziel 2/3."""
    cfg = rules.get("level2", {})
    k = int(cfg.get("min_group_size", 10))
    p = result.persons
    pop = p[p["zielgruppe"] & p["frist"].notna() & (p["frist"] <= result.stichtag)].reset_index(drop=True)
    outcome = (pop["erreicht_am"].notna() & (pop["erreicht_am"] <= pop["frist"])).rename("erreicht")
    plural = "Personen" if result.unit == "Person" else "Haushalte"
    if len(pop) < k:
        empty = pd.DataFrame()
        return Level2Result(result.goal, result.unit, len(pop), int(outcome.sum()), math.nan, empty, empty, empty,
                            [f"Zu wenige {plural} mit abgelaufener Frist ({len(pop)}) für eine Auswertung."], k)
    overall = float(outcome.mean())
    feats = build_features(pop, tables, bool(cfg.get("include_case_worker", False)))
    for label, values in (extra or {}).items():
        feats[label] = pop["klientennummer"].map(values).fillna("unbekannt").values

    group_rows, strength_rows = [], []
    for col in feats.columns:
        rows = _group_rows(col, feats[col], outcome, overall, k)
        group_rows += rows
        shown = [r for r in rows if r["Gruppe"] != SMALL]
        if len(shown) >= 2:
            rates = [r["Quote"] for r in shown]
            strength_rows.append({"Merkmal": col, "Zusammenhang (Cramérs V)": _cramers_v(feats[col], outcome),
                                  "Spannweite Quote (Prozentpunkte)": round((max(rates) - min(rates)) * 100, 1),
                                  "Gruppen ausgewiesen": len(shown),
                                  "Auffällige Gruppen": sum(r["Auffällig"] == "ja" for r in shown)})
    groups = pd.DataFrame(group_rows)
    strength = pd.DataFrame(strength_rows).sort_values("Zusammenhang (Cramérs V)", ascending=False).reset_index(drop=True)

    single = {(r["Merkmal"], r["Gruppe"]): r["Quote"] for r in group_rows}
    combo_rows = []
    top = [m for m in strength["Merkmal"] if m != "Einreisejahr"][:8]
    for a, b in itertools.combinations(top, 2):
        informative = ~feats[a].isin(UNINFORMATIVE) & ~feats[b].isin(UNINFORMATIVE)
        labels = (feats[a].astype(str) + "  &  " + feats[b].astype(str))[informative]
        for r in _group_rows(f"{a} × {b}", labels, outcome[informative], overall, k):
            if r["Gruppe"] == SMALL or r["Auffällig"] != "ja":
                continue
            ga, gb = r["Gruppe"].split("  &  ")
            ra, rb = single.get((a, ga)), single.get((b, gb))
            if ra is None or rb is None:
                continue
            # nur Kombinationen, die mehr zeigen als jedes Merkmal allein
            extra = r["Quote"] - max(ra, rb) if r["Quote"] > overall else min(ra, rb) - r["Quote"]
            if extra >= MIN_EXTRA:
                combo_rows.append({**r, "Zusatz ggü. Einzelmerkmal (Prozentpunkte)": round(extra * 100, 1)})
    combos = pd.DataFrame(combo_rows)
    if not combos.empty:
        combos = (combos.assign(_abs=combos["Differenz zu gesamt (Prozentpunkte)"].abs())
                  .sort_values("_abs", ascending=False).drop(columns="_abs").head(int(cfg.get("top_combinations", 12))))

    return Level2Result(result.goal, result.unit, len(pop), int(outcome.sum()), overall, groups, strength,
                        combos.reset_index(drop=True), _insights(groups, strength, overall, len(pop), result.short, plural), k)


def _insights(groups: pd.DataFrame, strength: pd.DataFrame, overall: float, n: int, short: str, plural: str) -> list[str]:
    if groups.empty:
        return []
    notable = groups[(groups["Auffällig"] == "ja") & (groups["Gruppe"] != SMALL) & ~groups["Gruppe"].isin(UNINFORMATIVE)
                     & (groups["Merkmal"] != "Einreisejahr")]
    dative = "Haushalten" if plural == "Haushalte" else plural
    out = [f"Von {n} {dative} mit abgelaufener Frist haben {overall:.0%} {short} fristgerecht erreicht."]
    if not strength.empty:
        out.append("Stärkste Zusammenhänge: " + ", ".join(strength["Merkmal"].head(4)) + ".")
    for _, r in notable.sort_values("Differenz zu gesamt (Prozentpunkte)", ascending=False).head(3).iterrows():
        out.append(f"▲ {r['Merkmal']} = {r['Gruppe']}: {r['Quote']:.0%} erreichen {short} fristgerecht (n = {r['Personen']}).")
    for _, r in notable.sort_values("Differenz zu gesamt (Prozentpunkte)").head(3).iterrows():
        out.append(f"▼ {r['Merkmal']} = {r['Gruppe']}: nur {r['Quote']:.0%} (n = {r['Personen']}).")
    return out
