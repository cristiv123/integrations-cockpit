"""Fallakte: pro Person die drei Ziel-Ampeln und ein Zeitstrahl aus den Rohtabellen.

Diese Schicht rechnet nichts neu: die Ampeln kommen aus den bereits berechneten
Ziel-Ergebnissen (``GoalResult.persons``), der Zeitstrahl aus den ingest-Rohtabellen
(Feldnamen aus ``schema.py``). Reine Daten-Aufbereitung – kein Streamlit, kein altair,
damit die Logik testbar bleibt.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .base import GoalResult, with_client

# Reihenfolge der Spuren im Zeitstrahl (von oben nach unten)
SPUREN = ["Sprache", "Kurse & Ausbildung", "Arbeit", "Sozialhilfe (Haushalt)"]

# Ab diesem Pensum (%) gilt eine Anstellung für Ziel 2 und wird hervorgehoben
PENSUM_HERVORHEBUNG = 60.0

EREIGNIS_SPALTEN = ["spur", "typ", "start", "ende", "label", "detail", "hervorgehoben"]

DEFAULT_LABELS = {
    1: "Ziel 1 · Sprache A1",
    2: "Ziel 2 · Arbeit / Ausbildung",
    3: "Ziel 3 · Ohne Sozialhilfe",
}


@dataclass
class Fallakte:
    klientennummer: str
    zemis: object = None
    dossier: object = None
    verfahrensstand: object = None
    alter: object = None
    ziele: list[dict] = field(default_factory=list)   # [{goal, label, status, ampel}]
    ereignisse: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=EREIGNIS_SPALTEN))
    marker: dict = field(default_factory=dict)         # Name -> Timestamp


def _notna(v: object) -> bool:
    return not (v is None or (not isinstance(v, str) and pd.isna(v)))


def _get(row, col):
    if row is None or col not in row.index:
        return None
    v = row[col]
    return v if _notna(v) else None


def _klient_df(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    kl = tables.get("klient")
    if kl is None or kl.empty:
        return pd.DataFrame(columns=["klientennummer", "zemis"])
    return kl.dropna(subset=["klientennummer"]).drop_duplicates("klientennummer")


def _row_by(result: GoalResult | None, key_col: str, key: object):
    """Zeile einer Einheit (Person bzw. Haushalt) im Ziel-Ergebnis, oder None."""
    if result is None or key is None:
        return None
    df = result.persons
    if key_col not in df.columns:
        return None
    hit = df[df[key_col].astype("object") == key]
    return hit.iloc[0] if len(hit) else None


def _person_rows(tables: dict[str, pd.DataFrame], source: str, klientennummer: str, klient: pd.DataFrame) -> pd.DataFrame:
    """Rohzeilen einer über Klientennummer/Zemis verknüpften Tabelle für eine Person."""
    df = tables.get(source)
    if df is None or df.empty:
        return pd.DataFrame()
    linked = with_client(df, klient)
    return linked[linked["klientennummer"].astype("object") == klientennummer]


def person_options(results: dict[int, GoalResult]) -> list[dict]:
    """Auswahlliste: eine Person je Klientennummer mit Status und Alter (für das Selectbox)."""
    base = results.get(1) or next(iter(results.values()), None)
    if base is None:
        return []
    cols = base.persons
    out = []
    for _, r in cols.sort_values("klientennummer").iterrows():
        out.append({
            "klientennummer": r["klientennummer"],
            "verfahrensstand": _get(r, "verfahrensstand"),
            "alter": _get(r, "alter_stichtag"),
        })
    # Doppelte Klientennummern (sollte es nicht geben) zusammenfallen lassen
    seen, unique = set(), []
    for o in out:
        if o["klientennummer"] in seen:
            continue
        seen.add(o["klientennummer"])
        unique.append(o)
    return unique


def _append_punkte(rows: list[dict], person: pd.DataFrame) -> None:
    if person.empty or "datum" not in person.columns:
        return
    for _, r in person.dropna(subset=["datum"]).iterrows():
        niveau = _get(r, "niveau")
        teile = [t for t in (_get(r, "sprache"), _get(r, "nachweis")) if t]
        rows.append({
            "spur": "Sprache", "typ": "punkt",
            "start": r["datum"], "ende": r["datum"],
            "label": str(niveau) if niveau else "?",
            "detail": " · ".join(str(t) for t in teile) or None,
            "hervorgehoben": False,
        })


def _append_balken(rows: list[dict], person: pd.DataFrame, spur: str, start_col: str, end_col: str,
                   stichtag: pd.Timestamp, label_fn, hervor_fn=None, detail_fn=None) -> None:
    if person.empty or start_col not in person.columns:
        return
    for _, r in person.dropna(subset=[start_col]).iterrows():
        start = r[start_col]
        laufend = not _notna(r.get(end_col))
        ende = stichtag if laufend else r[end_col]
        if _notna(ende) and ende < start:
            ende = start
        rows.append({
            "spur": spur, "typ": "balken",
            "start": start, "ende": ende,
            "label": label_fn(r),
            "detail": (detail_fn(r) if detail_fn else None),
            "hervorgehoben": bool(hervor_fn(r)) if hervor_fn else False,
        })


def build_fallakte(tables: dict[str, pd.DataFrame], stichtag, klientennummer: str,
                   results: dict[int, GoalResult], goal_labels: dict[int, str] | None = None) -> Fallakte:
    """Fallakte einer Person: Ziel-Ampeln (aus results) und Zeitstrahl (aus Rohtabellen)."""
    stichtag = pd.Timestamp(stichtag).normalize()
    labels = goal_labels or DEFAULT_LABELS
    k = str(klientennummer)
    klient = _klient_df(tables)

    base = _row_by(results.get(1), "klientennummer", k)
    if base is None:
        base = _row_by(results.get(2), "klientennummer", k)
    dossier = _get(base, "dossier")
    zemis = _get(base, "zemis")

    ziele: list[dict] = []
    for g in (1, 2, 3):
        res = results.get(g)
        if res is None:
            continue
        row = _row_by(res, "dossier", dossier) if g == 3 else _row_by(res, "klientennummer", k)
        ziele.append({
            "goal": g,
            "label": labels.get(g, f"Ziel {g}"),
            "status": _get(row, "status"),
            "ampel": _get(row, "ampel"),
        })

    rows: list[dict] = []
    _append_punkte(rows, _person_rows(tables, "sprachstand", k, klient))

    kurse = _person_rows(tables, "integrationsfoerderung", k, klient)
    _append_balken(
        rows, kurse, "Kurse & Ausbildung", "start", "abschluss", stichtag,
        label_fn=lambda r: str(_get(r, "bezeichnung") or _get(r, "art") or "Kurs"),
        detail_fn=lambda r: " · ".join(str(t) for t in (_get(r, "art"), _get(r, "institution")) if t) or None,
    )

    def pensum(r):
        return pd.to_numeric(r.get("pensum"), errors="coerce")

    erwerb = _person_rows(tables, "erwerb", k, klient)
    _append_balken(
        rows, erwerb, "Arbeit", "von", "bis", stichtag,
        label_fn=lambda r: (f"{pensum(r):.0f} %" if _notna(pensum(r)) else str(_get(r, "arbeitgeber") or "Anstellung")),
        hervor_fn=lambda r: _notna(pensum(r)) and pensum(r) >= PENSUM_HERVORHEBUNG,
        detail_fn=lambda r: " · ".join(str(t) for t in (_get(r, "arbeitgeber"), _get(r, "erwerbsstatus")) if t) or None,
    )

    fin = tables.get("finanzielle_unterstuetzung")
    if fin is not None and not fin.empty and dossier is not None:
        hh = fin[fin["dossier"].astype("object") == dossier]
        _append_balken(
            rows, hh, "Sozialhilfe (Haushalt)", "gueltig_von", "gueltig_bis", stichtag,
            label_fn=lambda r: str(_get(r, "unterstuetzung") or "Unterstützung"),
            detail_fn=lambda r: _get(r, "hauptgrund_beendigung"),
        )

    ereignisse = pd.DataFrame(rows, columns=EREIGNIS_SPALTEN)
    if not ereignisse.empty:
        ereignisse["spur"] = pd.Categorical(ereignisse["spur"], categories=SPUREN, ordered=True)
        ereignisse = ereignisse.sort_values(["spur", "start"]).reset_index(drop=True)

    marker = {
        "Einreise": _get(base, "einreise"),
        "Frist A1": _get(_row_by(results.get(1), "klientennummer", k), "frist"),
        "Zuständigkeitsende": _get(base, "zust_ende_eff"),
        "Heute": stichtag,
    }
    marker = {name: pd.Timestamp(v) for name, v in marker.items() if _notna(v)}

    return Fallakte(
        klientennummer=k, zemis=zemis, dossier=dossier,
        verfahrensstand=_get(base, "verfahrensstand"), alter=_get(base, "alter_stichtag"),
        ziele=ziele, ereignisse=ereignisse, marker=marker,
    )
