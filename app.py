"""Integrations-Cockpit – Streamlit-Oberfläche.  Start:  streamlit run app.py"""

from __future__ import annotations

import io
from datetime import date
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from cockpit.base import STATUS_AT_RISK, STATUS_MISSED, STATUS_ON_TRACK, STATUS_ORDER, STATUS_REACHED, STATUS_REACHED_LATE, prepare_persons, restrict
from cockpit.export import build_workbook, unit_table
from cockpit.fallakte import PENSUM_HERVORHEBUNG, SPUREN, build_fallakte, person_options
from cockpit.goal1 import evaluate_goal1
from cockpit.goal2 import evaluate_goal2
from cockpit.goal3 import evaluate_goal3
from cockpit.ingest import load_exports
from cockpit.level2 import CAVEAT, analyse
from cockpit.matrix import call_list, cockpit_matrix, matrix_table
from cockpit.rules import read_rules_text, rules_from_text
from cockpit.situationsanalyse import FEATURES as SA_FEATURES
from cockpit.situationsanalyse import evaluate as evaluate_extraction
from cockpit.situationsanalyse import extract_documents, llm_available

ROOT = Path(__file__).parent
SYNTH_DIR = ROOT / "data" / "synthetic"
SA_MERKMALE = {"Regeln": SYNTH_DIR / "Situationsanalyse_Merkmale.xlsx",
               "LLM lokal": ROOT / "data" / "situationsanalyse_merkmale_llm.xlsx"}
GROUND_TRUTH = ROOT / "data" / "situationsanalyse_ground_truth.csv"
LLM_MODEL = "qwen3:4b"
AMPEL_ICON = {"grün": "🟢", "gelb": "🟡", "rot": "🔴", "grau": "⚪"}
STATUS_ICON = {STATUS_REACHED: "🟢", STATUS_REACHED_LATE: "🟢", STATUS_ON_TRACK: "🟡", STATUS_AT_RISK: "🔴", STATUS_MISSED: "🔴"}
PCT = st.column_config.NumberColumn(format="percent")
GOALS = {1: ("Ziel 1 · Sprache A1", evaluate_goal1), 2: ("Ziel 2 · Arbeit / Ausbildung", evaluate_goal2),
         3: ("Ziel 3 · Ohne Sozialhilfe", evaluate_goal3)}
DATE_COLS = ("Geburtsdatum", "Einreisedatum", "A1 erreicht am", "Ziel 2 erreicht am", "Ziel 3 erreicht am", "Nächste offene Frist")

st.set_page_config(page_title="Integrations-Cockpit", page_icon="🧭", layout="wide")


@st.cache_data(show_spinner="Exporte werden gelesen …")
def load(files: tuple[tuple[str, bytes], ...]):
    return load_exports(list(files))


# rules_text is part of the cache key, so an edited rules.yaml takes effect at the next rerun
@st.cache_data(show_spinner="Ziele werden berechnet …")
def evaluate_all(files: tuple[tuple[str, bytes], ...], stichtag: date, rules_text: str):
    loaded, rules, ts = load(files), rules_from_text(rules_text), pd.Timestamp(stichtag)
    results, errors = {}, {}
    try:
        persons = prepare_persons(loaded.tables, rules, ts)
    except KeyError as exc:
        return results, {0: f"Export Klient fehlt oder ist unvollständig ({exc})"}, None
    for goal, (_, fn) in GOALS.items():
        try:
            results[goal] = fn(loaded.tables, rules, ts, persons)
        except ValueError as exc:
            errors[goal] = str(exc)
    matrix = cockpit_matrix(results[1], results.get(2), results.get(3)) if 1 in results else None
    return results, errors, matrix


@st.cache_data(show_spinner="Muster werden berechnet …")
def level2_for(files: tuple[tuple[str, bytes], ...], stichtag: date, goal: int, rules_text: str):
    results, _, _ = evaluate_all(files, stichtag, rules_text)
    extra = None
    if goal > 1 and 1 in results:
        p1 = results[1].persons.set_index("klientennummer")
        extra = {"Ziel 1 (A1) erreicht": p1["erreicht_am"].notna().map({True: "ja", False: "nein"})}
    return analyse(results[goal], load(files).tables, rules_from_text(rules_text), extra)


def synthetic_files(sa_method: str) -> tuple[tuple[str, bytes], ...]:
    paths = [p for p in sorted(SYNTH_DIR.glob("*.xlsx")) if not p.name.startswith("Situationsanalyse_Merkmale")]
    if SA_MERKMALE[sa_method].exists():
        paths.append(SA_MERKMALE[sa_method])
    return tuple((p.name, p.read_bytes()) for p in paths)


def with_icons(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in df.columns:
        if col.startswith("Ziel ") and "·" in col or col.startswith("Status Ziel"):
            df[col] = df[col].map(lambda s: f"{STATUS_ICON.get(s, '⚪')} {s}" if isinstance(s, str) else s)
    if "Priorität" in df.columns:
        df["Priorität"] = df["Priorität"].map(lambda a: AMPEL_ICON.get(a, "") if isinstance(a, str) else "")
    if "Ampel" in df.columns:
        df.insert(0, "", df.pop("Ampel").map(AMPEL_ICON))
    return df


def date_config(df: pd.DataFrame) -> dict:
    return {c: st.column_config.DateColumn(format="DD.MM.YYYY") for c in df.columns if c in DATE_COLS or str(c).startswith("Frist")}


def fallakte_chart(fa) -> alt.LayerChart:
    """Zeitstrahl einer Person: Balken (Kurse, Arbeit, Sozialhilfe), Punkte (Sprache), Marker-Linien."""
    ev = fa.ereignisse
    y = alt.Y("spur:N", title=None, scale=alt.Scale(domain=SPUREN))
    layers: list = []
    balken = ev[ev["typ"] == "balken"] if not ev.empty else ev
    if not balken.empty:
        layers.append(alt.Chart(balken).mark_bar(height=16, cornerRadius=3).encode(
            x=alt.X("start:T", title=None), x2="ende:T", y=y,
            color=alt.Color("hervorgehoben:N", scale=alt.Scale(domain=[True, False], range=["#1F4E78", "#9DB3C8"]), legend=None),
            tooltip=[alt.Tooltip("spur:N", title="Spur"), alt.Tooltip("label:N", title="Eintrag"),
                     alt.Tooltip("start:T", title="von", format="%d.%m.%Y"), alt.Tooltip("ende:T", title="bis", format="%d.%m.%Y"),
                     alt.Tooltip("detail:N", title="Detail")]))
    punkte = ev[ev["typ"] == "punkt"] if not ev.empty else ev
    if not punkte.empty:
        base = alt.Chart(punkte).encode(x=alt.X("start:T", title=None), y=y)
        layers.append(base.mark_point(filled=True, size=120, color="#2E7D32").encode(
            tooltip=[alt.Tooltip("start:T", title="Datum", format="%d.%m.%Y"), alt.Tooltip("label:N", title="Niveau"),
                     alt.Tooltip("detail:N", title="Detail")]))
        layers.append(base.mark_text(dy=-12, color="#2E7D32", fontWeight="bold").encode(text="label:N"))
    if fa.marker:
        md = pd.DataFrame([{"name": n, "datum": d} for n, d in fa.marker.items()])
        layers.append(alt.Chart(md).mark_rule(strokeDash=[4, 4], color="#C62828").encode(
            x="datum:T", tooltip=[alt.Tooltip("name:N", title="Marke"), alt.Tooltip("datum:T", title="Datum", format="%d.%m.%Y")]))
        layers.append(alt.Chart(md).mark_text(align="left", dx=3, dy=-4, color="#C62828", fontSize=10, baseline="top").encode(
            x="datum:T", y=alt.value(6), text="name:N"))
    return alt.layer(*layers).properties(height=240)


with st.sidebar:
    st.header("Daten")
    source = st.radio("Quelle", ["Synthetische Demodaten", "Eigene Exporte hochladen"], label_visibility="collapsed")
    if source == "Eigene Exporte hochladen":
        uploads = st.file_uploader("Excel-Exporte (.xlsx), optional mit Situationsanalyse-Merkmalen", type=["xlsx"], accept_multiple_files=True)
        files = tuple((u.name, u.getvalue()) for u in uploads or [])
    else:
        available = [m for m, p in SA_MERKMALE.items() if p.exists()]
        sa_method = st.radio("Situationsanalyse-Merkmale", available, horizontal=True,
                             help="Wie die Merkmale aus den Freitext-Berichten gewonnen wurden") if available else "Regeln"
        if not SA_MERKMALE["LLM lokal"].exists():
            st.caption("LLM-Extraktion noch nicht vorhanden (läuft ggf. im Hintergrund).")
        files = synthetic_files(sa_method)
        st.caption(f"{len(files)} Dateien aus `data/synthetic` – keine echten Personen.")
    stichtag = st.date_input("Stichtag", value=date.today(), format="DD.MM.YYYY")

if not files:
    st.title("Integrations-Cockpit")
    st.info("Bitte die Excel-Exporte hochladen (mindestens Klient und Asylgeschäftsdaten; je Ziel die zugehörigen Tabellen).")
    st.stop()

rules_text = read_rules_text()
rules = rules_from_text(rules_text)
loaded = load(files)
results, errors, matrix = evaluate_all(files, stichtag, rules_text)
if not results:
    st.title("Integrations-Cockpit")
    st.error(" · ".join(errors.values()))
    st.dataframe(loaded.issues_frame(), hide_index=True, width="stretch")
    st.stop()

with st.sidebar:
    goal = st.radio("Ziel", list(results), format_func=lambda g: GOALS[g][0])
    for g, msg in errors.items():
        st.caption(f"⚠️ {msg}")
    st.header("Ansicht")
    view = st.radio("Rolle", ["Leitung", "Sozialarbeiter:in"], horizontal=True)
    worker = None
    if view == "Sozialarbeiter:in":
        worker = st.selectbox("Fallführung", sorted(results[1 if 1 in results else goal].persons["fallfuehrung"].dropna().unique()))
    st.divider()
    st.caption("🔒 Verarbeitung nur lokal und im Arbeitsspeicher. Keine Daten werden gespeichert "
               "oder verlassen das Netzwerk; Nutzungsstatistik ist deaktiviert.")

if worker:
    results = {g: restrict(r, r.persons["fallfuehrung"] == worker) for g, r in results.items()}
    matrix = matrix[matrix["fallfuehrung"] == worker] if matrix is not None else None

result = results[goal]
issues_all = [loaded.issues_frame()] + [pd.DataFrame([i.as_row() for i in r.issues]) for r in results.values()]
issues = pd.concat(issues_all, ignore_index=True).drop_duplicates()
units = result.persons
scope = units[units["im_scope"]]
plural = "Personen" if result.unit == "Person" else "Haushalte"
vc = scope["status"].value_counts()

st.title("Integrations-Cockpit")
st.caption(f"Asylsozialdienst Stadt Bern · {result.label}")

cols = st.columns(6)
cols[0].metric(f"{plural} im Scope", len(scope), help="Aktuelle Fälle mit VA/FL-Status, für die das Ziel gilt")
cols[1].metric("🟢 Erreicht", int(vc.get(STATUS_REACHED, 0) + vc.get(STATUS_REACHED_LATE, 0)),
               help=f"davon nach Frist: {int(vc.get(STATUS_REACHED_LATE, 0))}")
cols[2].metric("🟡 Auf Kurs", int(vc.get(STATUS_ON_TRACK, 0)))
cols[3].metric("🔴 Gefährdet", int(vc.get(STATUS_AT_RISK, 0)),
               help=f"≤ {rules[f'goal{goal}'].get('risk_months')} Monate bis Frist und nicht absehbar erreicht")
cols[4].metric("🔴 Frist verpasst", int(vc.get(STATUS_MISSED, 0)), help="Hätte das Ziel bis heute erreichen sollen")
if goal == 1:
    q = result.totals["Quote fristgerecht (fällige)"]
    cols[5].metric("Quote fristgerecht", f"{q:.0%}" if q is not None else "–", help="Unter allen, deren Frist abgelaufen ist oder die das Ziel erreicht haben")
else:
    q = result.totals["Quote fristgerecht (abgeschlossene Fälle)"]
    cols[5].metric("Quote abgeschlossene Fälle", f"{q:.0%}" if q is not None else "–",
                   help=f"Frist = Zuständigkeitsende. Anteil fristgerecht erreicht unter {result.totals['Abgeschlossene Fälle (Frist abgelaufen, inkl. frühere)']} "
                        f"{plural} mit abgelaufener Zuständigkeit (inkl. frühere Klient:innen).")

if view == "Leitung":
    tab_names = ["Cockpit", "Fallakte", "Übersicht", "Muster", "Situationsanalysen", "Liste", "Datenqualität", "Annahmen"]
else:
    tab_names = ["Wen rufe ich an?", "Cockpit", "Fallakte", "Übersicht", "Liste", "Datenqualität", "Annahmen"]
tabs = dict(zip(tab_names, st.tabs(tab_names)))

if "Wen rufe ich an?" in tabs:
    with tabs["Wen rufe ich an?"]:
        st.subheader(f"Prioritäten diese Woche – {worker}")
        st.caption("Alle drei Ziele: rot (gefährdet) vor gelb, dann nach der nächsten offenen Frist.")
        calls = call_list(matrix) if matrix is not None else []
        if not calls:
            st.success("Keine offenen Fälle.")
        for c in calls:
            with st.container(border=True):
                st.markdown(f"{AMPEL_ICON[c['prioritaet']]} **{c['klientennummer']}** · {c['verfahrensstand']} · Alter {c['alter']}")
                for ampel, text in c["gruende"]:
                    st.markdown(f"{AMPEL_ICON[ampel]} {text}")

with tabs["Cockpit"]:
    if matrix is None or matrix.empty:
        st.info("Cockpit benötigt mindestens Ziel 1.")
    else:
        st.caption("Eine Zeile pro Person, Ampel je Ziel. Ziel 3 gilt für den ganzen Haushalt.")
        summary_cols = st.columns(3)
        for i, g in enumerate(g for g in (1, 2, 3) if f"z{g}_status" in matrix.columns):
            open_counts = matrix[matrix[f"z{g}_scope"].fillna(False).astype(bool)][f"z{g}_ampel"].value_counts()
            summary_cols[i].markdown(f"**{GOALS[g][0]}**  \n🔴 {open_counts.get('rot', 0)} · 🟡 {open_counts.get('gelb', 0)} · 🟢 {open_counts.get('grün', 0)}")
        table = with_icons(matrix_table(matrix))
        st.dataframe(table, hide_index=True, width="stretch", height=520, column_config=date_config(table))

with tabs["Fallakte"]:
    opts = person_options(results)
    if not opts:
        st.info("Keine Personen im aktuellen Datensatz.")
    else:
        labels = {g: name for g, (name, _) in GOALS.items()}
        fmt = {o["klientennummer"]:
               f"{o['klientennummer']} · {o['verfahrensstand'] or '—'} · Alter {o['alter'] if o['alter'] is not None else '—'}"
               for o in opts}
        sel = st.selectbox("Klient:in", [o["klientennummer"] for o in opts], format_func=lambda k: fmt.get(k, k))
        fa = build_fallakte(loaded.tables, stichtag, sel, results, labels)

        ampel_cols = st.columns(len(fa.ziele) or 1)
        for col, z in zip(ampel_cols, fa.ziele):
            with col.container(border=True):
                st.markdown(f"**{z['label']}**")
                st.markdown(f"## {AMPEL_ICON.get(z['ampel'], '⚪')}")
                st.caption(z["status"] or "Nicht anwendbar")

        st.divider()
        st.markdown("**Zeitstrahl**")
        if fa.ereignisse.empty and not fa.marker:
            st.caption("Keine datierten Einträge für diese Person.")
        else:
            st.altair_chart(fallakte_chart(fa), width="stretch")
            st.caption(f"Punkte = Sprachnachweise (mit Niveau). Balken = Kurse/Ausbildung, Anstellungen "
                       f"(≥ {int(PENSUM_HERVORHEBUNG)} % dunkelblau hervorgehoben) und Sozialhilfe-Perioden des Haushalts. "
                       "Senkrechte Linien: Einreise, Frist A1, Zuständigkeitsende, Heute.")

with tabs["Übersicht"]:
    left, right = st.columns(2)
    by_year = pd.crosstab(scope["einreisejahr"], scope["status"]).reindex(columns=STATUS_ORDER, fill_value=0)
    with left:
        st.markdown("**Nach Einreisejahr**")
        st.bar_chart(by_year, color=["#2E7D32", "#81C784", "#F9A825", "#E57373", "#C62828"])
    with right:
        st.markdown("**Nach Fallführung**" if view == "Leitung" else "**Meine Fälle**")
        st.dataframe(result.by_worker, hide_index=True, width="stretch",
                     column_config={c: PCT for c in result.by_worker.columns if c.startswith("Quote")})
    st.markdown("**Nach Einreisejahr (Tabelle)**")
    st.dataframe(result.by_entry_year, hide_index=True, width="stretch",
                 column_config={c: PCT for c in result.by_entry_year.columns if c.startswith("Quote")})

level2 = None
if "Muster" in tabs:
    level2 = level2_for(files, stichtag, goal, rules_text)
    with tabs["Muster"]:
        st.subheader(f"Was haben {plural} gemeinsam, die {result.short} fristgerecht erreichen?")
        st.caption(f"Grundlage: Zielgruppe mit abgelaufener Frist, auch frühere Kohorten. Nur Gruppen ab {level2.min_group_size} {plural}, "
                   "nie ein Wert pro Person." + (" Merkmale der Dossierträger:in." if result.unit == "Haushalt" else ""))
        if level2.groups.empty:
            st.warning(level2.insights[0])
        else:
            for line in level2.insights:
                st.markdown(f"- {line}")
            st.info(CAVEAT, icon="ℹ️")

            left, right = st.columns([2, 3])
            with left:
                st.markdown("**Merkmale nach Stärke des Zusammenhangs**")
                st.dataframe(level2.strength, hide_index=True, width="stretch", height=430,
                             column_config={"Zusammenhang (Cramérs V)": st.column_config.ProgressColumn(min_value=0, max_value=0.5, format="%.2f")})
            with right:
                feature = st.selectbox("Merkmal im Detail", level2.strength["Merkmal"].tolist())
                g = level2.groups[level2.groups["Merkmal"] == feature]
                base = alt.Chart(g).encode(y=alt.Y("Gruppe:N", sort="-x", title=None))
                bars = base.mark_bar().encode(
                    x=alt.X("Quote:Q", axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0, 1]), title=f"{result.short} fristgerecht erreicht"),
                    color=alt.Color("Auffällig:N", scale=alt.Scale(domain=["ja", "nein"], range=["#1F4E78", "#9DB3C8"]), legend=None),
                    tooltip=["Gruppe", "Personen", alt.Tooltip("Quote:Q", format=".0%"), "Differenz zu gesamt (Prozentpunkte)"])
                ci = base.mark_rule(color="#333").encode(x="95%-Intervall von:Q", x2="95%-Intervall bis:Q")
                overall = alt.Chart(pd.DataFrame({"q": [level2.rate]})).mark_rule(color="#C62828", strokeDash=[5, 4]).encode(x="q:Q")
                st.altair_chart(bars + ci + overall, width="stretch")
                st.caption(f"Rote Linie = gesamt ({level2.rate:.0%}). Dunkelblau = Intervall schliesst den Gesamtwert aus.")

            st.markdown("**Kombinationen, die mehr zeigen als jedes Merkmal allein**")
            if level2.combinations.empty:
                st.caption("Keine auffälligen Kombinationen mit genügend grossen Gruppen.")
            else:
                st.dataframe(level2.combinations.drop(columns=["95%-Intervall von", "95%-Intervall bis", "Auffällig"]),
                             hide_index=True, width="stretch", column_config={"Quote": PCT})

if "Situationsanalysen" in tabs:
    with tabs["Situationsanalysen"]:
        st.subheader("Freitext-Berichte → prüfbare Merkmale")
        st.markdown(
            "Situationsanalysen (.docx, .pdf, .txt) hochladen. Namen, Telefon, Adresse und Nummern werden vor der Auswertung entfernt; "
            "die Zuordnung erfolgt über die Zemis-Nr. im Kopf. Das Ergebnis ist eine Excel-Datei, die Fachpersonen prüfen und korrigieren, "
            "bevor sie zusammen mit den Exporten hochgeladen wird.")
        docs = st.file_uploader("Situationsanalysen", type=["docx", "pdf", "txt"], accept_multiple_files=True)
        llm_ok = st.cache_data(ttl=60, show_spinner=False)(llm_available)(LLM_MODEL)
        method = st.radio("Methode", ["Regeln (Schlüsselwörter)", f"LLM lokal ({LLM_MODEL}, Ollama)"], horizontal=True, disabled=not docs)
        if not llm_ok:
            st.caption("Lokales LLM nicht erreichbar – nur Regeln verfügbar.")
        elif method.startswith("LLM"):
            st.caption("Läuft vollständig auf diesem Rechner. Auf CPU ca. 20 Sekunden pro Person.")
        if docs and st.button("Merkmale extrahieren", type="primary", disabled=method.startswith("LLM") and not llm_ok):
            bar = st.progress(0.0, text="Extraktion läuft …")
            st.session_state["sa_result"] = extract_documents(
                [(d.name, d.getvalue()) for d in docs], "llm" if method.startswith("LLM") else "regeln", LLM_MODEL,
                progress=lambda i, n: bar.progress(i / n, text=f"{i}/{n} Personen"))
        if "sa_result" in st.session_state:
            options = {spec["label"]: spec["values"] + ["unklar"] for spec in SA_FEATURES.values()}
            edited = st.data_editor(st.session_state["sa_result"], hide_index=True, width="stretch", disabled=["Zemis-Nr.", "Dossier-Nr.", "Datei", "Methode"],
                                    column_config={lbl: st.column_config.SelectboxColumn(options=opts) for lbl, opts in options.items()})
            buf = io.BytesIO()
            edited.to_excel(buf, index=False)
            st.download_button("⬇️ Geprüfte Merkmale als Excel", buf.getvalue(), "Situationsanalyse_Merkmale.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        if source == "Synthetische Demodaten" and GROUND_TRUTH.exists():
            st.markdown("**Qualität der Extraktion (nur Demodaten, Vergleich mit der bekannten Wahrheit)**")
            truth = pd.read_csv(GROUND_TRUTH, dtype={"Zemis-Nr.": str})
            evals = [evaluate_extraction(pd.read_excel(p, dtype={"Zemis-Nr.": str}), truth).assign(Methode=name)
                     for name, p in SA_MERKMALE.items() if p.exists()]
            if evals:
                ev = pd.concat(evals).pivot(index="Merkmal", columns="Methode", values="Trefferquote").reset_index()
                st.dataframe(ev, hide_index=True, width="stretch", column_config={c: PCT for c in ev.columns if c != "Merkmal"})
                st.caption("Die Regeln sind auf die Formulierungen der Demodaten abgestimmt – bei echten Berichten ist das LLM robuster; "
                           "die Trefferquote muss mit echten, anonymisierten Berichten geprüft werden.")

with tabs["Liste"]:
    only_scope = st.toggle(f"Nur {plural} im Scope", value=True)
    table = with_icons(unit_table(result, units[units["im_scope"]] if only_scope else units))
    st.dataframe(table, hide_index=True, width="stretch", height=520, column_config=date_config(table))

with tabs["Datenqualität"]:
    st.dataframe(issues, hide_index=True, width="stretch")
    st.caption("Erkannte Dateien: " + "; ".join(f"{t} ← {s}" for t, s in loaded.sources.items()))

with tabs["Annahmen"]:
    st.markdown("Regeln aus `rules.yaml` – offene Punkte bitte mit dem ASD klären und dort anpassen.")
    st.code(rules_text, language="yaml")

st.sidebar.download_button(
    "⬇️ Ergebnis als Excel (alle Ziele)",
    data=lambda: build_workbook(list(results.values()), rules, issues, loaded.sources, level2, matrix),
    file_name=f"Integrations-Cockpit_{stichtag:%Y-%m-%d}{'_' + worker.split()[0] if worker else ''}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    width="stretch",
)
