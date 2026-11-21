"""Ergebnisse als Excel für die tägliche Arbeit (Excel in, Excel out)."""

from __future__ import annotations

import io

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from .base import AMPEL, AMPEL_RANK, GoalResult
from .matrix import matrix_table

AMPEL_FILL = {
    "grün": PatternFill("solid", fgColor="C6EFCE"),
    "gelb": PatternFill("solid", fgColor="FFEB9C"),
    "rot": PatternFill("solid", fgColor="FFC7CE"),
    "grau": PatternFill("solid", fgColor="E7E6E6"),
}
STATUS_FILL = {s: AMPEL_FILL[a] for s, a in AMPEL.items()}
HEADER_FILL = PatternFill("solid", fgColor="1F4E78")


def unit_table(result: GoalResult, units: pd.DataFrame | None = None) -> pd.DataFrame:
    units = result.persons if units is None else units
    df = units.assign(_o=units["ampel"].map(AMPEL_RANK)).sort_values(["_o", "frist", "fallfuehrung"], na_position="last")
    cols = [c for c in result.columns if c in df.columns]
    return df[cols].rename(columns=result.columns)


person_table = unit_table


def flatten_rules(rules: dict, prefix: str = "") -> list[dict]:
    rows = []
    for k, v in rules.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            rows.extend(flatten_rules(v, key + "."))
        else:
            rows.append({"Regel": key, "Wert": ", ".join(map(str, v)) if isinstance(v, list) else str(v)})
    return rows


def build_workbook(results: GoalResult | list[GoalResult], rules: dict, issues: pd.DataFrame, sources: dict[str, str],
                   level2=None, matrix: pd.DataFrame | None = None) -> bytes:
    results = [results] if isinstance(results, GoalResult) else results
    stichtag = results[0].stichtag
    overview = [{"Kennzahl": "Stichtag", "Wert": stichtag.strftime("%d.%m.%Y")}]
    for r in results:
        overview.append({"Kennzahl": r.label, "Wert": ""})
        overview += [{"Kennzahl": f"  {k}", "Wert": v} for k, v in r.totals.items()]
    overview += [{"Kennzahl": f"Quelle {t}", "Wert": s} for t, s in sources.items()]

    sheets: dict[str, pd.DataFrame] = {"Übersicht": pd.DataFrame(overview)}
    if matrix is not None and not matrix.empty:
        sheets["Cockpit (alle Ziele)"] = matrix_table(matrix)
    for r in results:
        sheets[f"Ziel {r.goal} – {'Personen' if r.unit == 'Person' else 'Haushalte'}"] = unit_table(r)
        sheets[f"Ziel {r.goal} – Fallführung"] = r.by_worker
        sheets[f"Ziel {r.goal} – Einreisejahr"] = r.by_entry_year
    sheets["Datenqualität"] = issues
    sheets["Annahmen"] = pd.DataFrame(flatten_rules(rules))
    if level2 is not None and not level2.groups.empty:
        from .level2 import CAVEAT

        g = level2.goal
        notes = level2.insights + ["", CAVEAT, f"Gruppen mit weniger als {level2.min_group_size} Einheiten werden nicht ausgewiesen."]
        sheets[f"Muster Z{g} – Überblick"] = pd.DataFrame({f"Erkenntnisse Ziel {g}": notes})
        sheets[f"Muster Z{g} – Merkmale"] = level2.strength
        sheets[f"Muster Z{g} – Gruppen"] = level2.groups
        sheets[f"Muster Z{g} – Kombinationen"] = level2.combinations

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name[:31], index=False)
            _style(xw.sheets[name[:31]], df)
    return buf.getvalue()


def _style(ws: Worksheet, df: pd.DataFrame) -> None:
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    ws.freeze_panes = "A2"
    if ws.max_row > 1:
        ws.auto_filter.ref = ws.dimensions

    for idx, col in enumerate(df.columns, start=1):
        letter = get_column_letter(idx)
        series = df[col]
        width = max([len(str(col))] + [len(str(v)) for v in series.head(200) if v is not None and not (isinstance(v, float) and pd.isna(v))])
        ws.column_dimensions[letter].width = min(max(10, width + 2), 60)
        if pd.api.types.is_datetime64_any_dtype(series):
            for cell in ws[letter][1:]:
                cell.number_format = "DD.MM.YYYY"
        if str(col).startswith("Quote") or "Intervall" in str(col):
            for cell in ws[letter][1:]:
                cell.number_format = "0.0%"
        if col == "Ampel":
            for cell in ws[letter][1:]:
                if fill := AMPEL_FILL.get(cell.value):
                    for c in ws[cell.row]:
                        c.fill = fill
        elif str(col).startswith("Ziel ") and "·" in str(col) or col == "Priorität":
            for cell in ws[letter][1:]:
                if fill := STATUS_FILL.get(cell.value) or AMPEL_FILL.get(cell.value):
                    cell.fill = fill
