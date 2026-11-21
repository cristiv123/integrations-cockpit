"""Excel-Exporte einlesen: Tabelle anhand der Spalten erkennen, normalisieren, Datumswerte parsen."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from .schema import KEY_COLUMNS, TABLES

_SWISS_DATE_FORMATS = ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y")


def normalize_header(text: object) -> str:
    s = str(text).strip().lower()
    s = re.sub(r"[^\wäöüéèàß%]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


@dataclass
class Issue:
    severity: str  # Fehler | Warnung | Info
    table: str
    message: str
    count: int = 1

    def as_row(self) -> dict:
        return {"Schwere": self.severity, "Tabelle": self.table, "Meldung": self.message, "Anzahl": self.count}


@dataclass
class LoadResult:
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)

    def issues_frame(self) -> pd.DataFrame:
        return pd.DataFrame([i.as_row() for i in self.issues], columns=["Schwere", "Tabelle", "Meldung", "Anzahl"])


def map_columns(headers: list[object], table: str) -> dict[str, str]:
    """Spaltenüberschrift -> kanonisches Feld. Erst exakte Treffer, dann Präfix (z.B. 'Geburtsdatum (für «ab 16 J.»)')."""
    spec = TABLES[table]["columns"]
    normalized = {h: normalize_header(h) for h in headers}
    mapping: dict[str, str] = {}
    assigned: set[str] = set()

    for header, norm in normalized.items():
        for fld, aliases in spec.items():
            if fld not in assigned and norm in (normalize_header(a) for a in aliases):
                mapping[header] = fld
                assigned.add(fld)
                break

    for header, norm in normalized.items():
        if header in mapping:
            continue
        best: tuple[int, str] | None = None
        for fld, aliases in spec.items():
            if fld in assigned:
                continue
            for alias in aliases:
                a = normalize_header(alias)
                if len(a) > 5 and norm.startswith(a) and (best is None or len(a) > best[0]):
                    best = (len(a), fld)
        if best:
            mapping[header] = best[1]
            assigned.add(best[1])
    return mapping


def detect_table(headers: list[object]) -> tuple[str | None, dict[str, str]]:
    best: tuple[int, str, dict[str, str]] | None = None
    for table, spec in TABLES.items():
        mapping = map_columns(headers, table)
        if not set(spec["signature"]) <= set(mapping.values()):
            continue
        if best is None or len(mapping) > best[0]:
            best = (len(mapping), table, mapping)
    return (best[1], best[2]) if best else (None, {})


def parse_date(value: object) -> pd.Timestamp | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.normalize()
    if hasattr(value, "year") and hasattr(value, "month"):
        return pd.Timestamp(value).normalize()
    if isinstance(value, (int, float)) and 10000 < value < 80000:
        return (pd.Timestamp("1899-12-30") + pd.Timedelta(days=float(value))).normalize()
    text = str(value).strip()
    if not text:
        return None
    for fmt in _SWISS_DATE_FORMATS:
        try:
            return pd.to_datetime(text, format=fmt).normalize()
        except (ValueError, TypeError):
            continue
    raise ValueError(text)


def _parse_date_column(df: pd.DataFrame, col: str, table: str, issues: list[Issue]) -> None:
    parsed, bad = [], []
    for v in df[col].tolist():
        try:
            parsed.append(parse_date(v))
        except ValueError:
            parsed.append(None)
            bad.append(str(v))
    df[col] = pd.to_datetime(pd.Series(parsed, index=df.index, dtype="object"))
    if bad:
        sample = ", ".join(sorted(set(bad))[:3])
        issues.append(Issue("Warnung", TABLES[table]["label"], f"Ungültiges Datum in '{col}' (z.B. {sample})", len(bad)))


def _clean_key(series: pd.Series) -> pd.Series:
    def clean(v: object) -> str | None:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        s = str(v).strip()
        return s or None

    return series.map(clean).astype("object")


def read_frame(df: pd.DataFrame, source: str, result: LoadResult) -> None:
    table, mapping = detect_table(list(df.columns))
    if table is None:
        result.issues.append(Issue("Warnung", source, "Datei keiner bekannten Tabelle zugeordnet – ignoriert"))
        return
    label = TABLES[table]["label"]
    unknown = [str(c) for c in df.columns if c not in mapping]
    if unknown:
        result.issues.append(Issue("Info", label, "Unbekannte Spalten ignoriert: " + ", ".join(unknown), len(unknown)))

    out = df[list(mapping)].rename(columns=mapping).dropna(how="all").reset_index(drop=True)
    for fld in TABLES[table]["columns"]:
        if fld not in out.columns:
            out[fld] = None
    for key in KEY_COLUMNS:
        if key in out.columns:
            out[key] = _clean_key(out[key])
    for col in TABLES[table]["dates"]:
        _parse_date_column(out, col, table, result.issues)

    if table in result.tables:
        result.issues.append(Issue("Info", label, f"Mehrere Dateien – zusammengeführt ({source})"))
        out = pd.concat([result.tables[table], out], ignore_index=True)
        result.sources[table] += f", {source}"
    else:
        result.sources[table] = source
    result.tables[table] = out


def load_exports(files: list[tuple[str, bytes | BinaryIO]]) -> LoadResult:
    result = LoadResult()
    for name, content in files:
        data = content if isinstance(content, bytes) else content.read()
        try:
            sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, dtype=object)
        except Exception as exc:  # noqa: BLE001 – jede kaputte Datei soll gemeldet, nicht abgestürzt werden
            result.issues.append(Issue("Fehler", name, f"Datei nicht lesbar: {exc}"))
            continue
        for sheet_name, df in sheets.items():
            if df.empty:
                continue
            read_frame(df, name if len(sheets) == 1 else f"{name} [{sheet_name}]", result)

    _check_keys(result)
    return result


def load_directory(path: str | Path) -> LoadResult:
    files = sorted(Path(path).glob("*.xlsx"))
    return load_exports([(f.name, f.read_bytes()) for f in files if not f.name.startswith("~$")])


def _check_keys(result: LoadResult) -> None:
    klient = result.tables.get("klient")
    if klient is None:
        return
    dupes = klient["klientennummer"].dropna().duplicated().sum()
    if dupes:
        result.issues.append(Issue("Fehler", "Klient", "Klientennummer mehrfach vorhanden", int(dupes)))
    known_k = set(klient["klientennummer"].dropna())
    known_z = set(klient["zemis"].dropna())
    for table, df in result.tables.items():
        if table == "klient":
            continue
        if "klientennummer" in df.columns and df["klientennummer"].notna().any():
            orphans = df["klientennummer"].notna() & ~df["klientennummer"].isin(known_k)
        elif "zemis" in df.columns:
            orphans = df["zemis"].notna() & ~df["zemis"].isin(known_z)
        else:
            continue
        if orphans.sum():
            result.issues.append(
                Issue("Warnung", TABLES[table]["label"], "Zeilen ohne passende Person in Klient", int(orphans.sum()))
            )
