# Integrations-Cockpit: installation and configuration

*Language versions: English (this file) · [Română](../ro/instalare.md)*

Related: [Technical documentation](technical-documentation.md) · [User manual](user-manual.md)

---

## Contents

1. [What you are installing](#1-what-you-are-installing)
2. [Requirements](#2-requirements)
3. [Installation](#3-installation)
4. [First start and check](#4-first-start-and-check)
5. [Optional: local LLM for the Situationsanalysen](#5-optional-local-llm-for-the-situationsanalysen)
6. [Configuration](#6-configuration)
7. [Working with real exports](#7-working-with-real-exports)
8. [Regenerating the demo data](#8-regenerating-the-demo-data)
9. [Running the tests](#9-running-the-tests)
10. [Updating and uninstalling](#10-updating-and-uninstalling)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. What you are installing

A Python web application. It runs on **one computer**, and the people using it open it in a
browser on that same computer. It stores nothing: the Excel exports are uploaded, processed in
memory and the result is downloaded again.

| Component | Required | Purpose |
|---|---|---|
| Python 3.12 + the packages in `requirements.txt` | yes | The application |
| A web browser (Chrome, Edge, Firefox) | yes | The user interface |
| [Ollama](https://ollama.com) with the `qwen3:4b` model | no | Reading the free-text Situationsanalysen with a local AI model. Without it, keyword rules are used. |
| Git | no | Getting the code and updates |

## 2. Requirements

| | Minimum | Recommended |
|---|---|---|
| Operating system | Windows 10/11, macOS or Linux | Windows 11 (the commands below use PowerShell) |
| Python | 3.11 | 3.12 (tested with 3.12.10) |
| Memory | 4 GB | 8 GB; 16 GB with the local LLM |
| Disk | 500 MB | 4 GB with the local LLM (the model takes 2.5 GB) |
| Network | none at run time | Internet only during installation, to download packages and the model |

Check Python:

```powershell
python --version
```

If it is missing, install it from [python.org](https://www.python.org/downloads/). On Windows,
tick **Add python.exe to PATH** during setup.

## 3. Installation

### 3.1 Get the code

With Git:

```powershell
git clone https://github.com/cristiv123/integrations-cockpit.git
cd integrations-cockpit
```

Without Git: on the GitHub page choose **Code → Download ZIP**, unpack it, and open PowerShell
in the unpacked folder.

### 3.2 Create a virtual environment and install the packages

The virtual environment keeps the application's packages separate from the rest of the system.

```powershell
python -m venv .venv
```

```powershell
.venv\Scripts\Activate.ps1
```

```powershell
pip install -r requirements.txt
```

On macOS and Linux the activation command is `source .venv/bin/activate`.

If PowerShell refuses to run the activation script ("running scripts is disabled"), allow it
for the current window only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

The installed packages are pinned to exact versions in `requirements.txt`: Streamlit 1.67.0,
pandas 3.1.1, openpyxl 3.1.5, PyYAML 6.0.3, Altair 6.3.0, python-docx 1.2.0, pypdf 7.1.1,
requests 2.34.2 and pytest 9.2.0.

## 4. First start and check

With the virtual environment active:

```powershell
streamlit run app.py
```

Open **http://localhost:8501** in the browser. The first load takes about 20 seconds.

Check that the installation works:

1. In the sidebar, **Synthetische Demodaten** (synthetic demo data) is selected, and the
   caption below it reports the number of files loaded from `data/synthetic`.
2. The header shows six numbers, and the **Cockpit** tab shows a table with coloured circles.
3. **Ergebnis als Excel** (result as Excel), at the bottom of the sidebar, downloads a
   workbook.

Stop the application with **Ctrl+C** in the PowerShell window.

To start it again later, without re-activating the environment:

```powershell
.venv\Scripts\streamlit.exe run app.py
```

## 5. Optional: local LLM for the Situationsanalysen

The *Situationsanalysen* are free-text Word reports. The application turns each one into five
features (psychological burden, motivation, learning speed, care duties, social network). It
can do this with keyword rules, which need nothing extra, or with a language model running
**on the same computer**.

1. Install Ollama from [ollama.com/download](https://ollama.com/download). It starts in the
   background and listens on `http://localhost:11434`.
2. Download the model, about 2.5 GB:

   ```powershell
   ollama pull qwen3:4b
   ```

3. Check that the model is there:

   ```powershell
   ollama list
   ```

4. Restart the application. In the **Situationsanalysen** tab the method
   **LLM lokal (qwen3:4b, Ollama)** is now available. If Ollama is not reachable, the tab says
   so and only the rules can be chosen.

### 5.1 LLM features for the demo data

The sidebar switch **Situationsanalyse-Merkmale: Regeln / LLM lokal** only offers *LLM lokal*
once the file `data/situationsanalyse_merkmale_llm.xlsx` exists. It is not in the repository.
Create it with:

```powershell
python -m cockpit.situationsanalyse data/situationsanalysen --methode llm --cache data/cache/situationsanalyse_llm.jsonl --truth data/situationsanalyse_ground_truth.csv --out data/situationsanalyse_merkmale_llm.xlsx
```

| Option | Meaning |
|---|---|
| `--methode llm` / `regeln` | Use the model or the keyword rules |
| `--model` | Ollama model name, default `qwen3:4b` |
| `--workers N` | Persons processed in parallel; keep at 1 to 2 on a laptop |
| `--cache file.jsonl` | Saves each result, so an interrupted run continues where it stopped. The repository already contains the results for 326 of the 417 demo persons. |
| `--truth file.csv` | After the run, prints the hit rate per feature (demo data only) |
| `--limit N` | Process only the first N files, for a quick test |

On a CPU it takes about 20 seconds per person.

## 6. Configuration

### 6.1 Business rules: `rules.yaml`

Everything the challenge description leaves open is a setting in `rules.yaml`: who counts as a
current client, deadlines, minimum age, accepted language certificates, the 60 % threshold, the
treatment of parallel jobs, which kinds of support count as social assistance, the minimum group
size for patterns, and more. Each setting has a comment explaining it.

- Edit the file with any text editor and save it **as UTF-8**.
- **Clear the cache afterwards.** The computed results are cached per set of files and
  Stichtag, and the cache does not notice a changed `rules.yaml`. Open the menu **⋮** at the
  top right of the page and choose **Clear cache**, or press `C`; restarting the application
  also works. Until then the *Annahmen* tab already shows the new rules while the numbers are
  still the old ones.
- The **Annahmen** (assumptions) tab shows the rules in force, and the Excel result contains
  them on the *Annahmen* sheet. A result therefore always documents the rules it was computed
  with.

Common changes:

| Need | Setting |
|---|---|
| A new certificate type counts for A1 | add it to `goal1.accepted_proofs`; an empty list `[]` accepts every proof type |
| Two 30 % jobs should *not* add up to 60 % | `goal2.sum_parallel_jobs: false` |
| Allow a short break between two jobs | `goal2.max_gap_days: 14` |
| Education counts only once completed | `goal2.education_counts_from: abschluss` |
| Warn earlier | raise `goalN.risk_months` |
| Pattern analysis by social worker | `level2.include_case_worker: true`, **only with the employees' consent** |

> Keep the minimum group size `level2.min_group_size` at 10 or higher. It is what prevents
> conclusions about individual people.

A YAML syntax error stops the application with an error message naming the line. Keep a copy
before editing.

### 6.2 Server: `.streamlit/config.toml`

```toml
[browser]
gatherUsageStats = false     # no usage statistics are sent to Streamlit

[server]
address = "localhost"        # reachable only from this computer
headless = true              # do not open a browser window automatically
maxUploadSize = 200          # MB per upload

[theme]
base = "light"
primaryColor = "#1F4E78"
```

| Need | Change |
|---|---|
| Another port | start with `streamlit run app.py --server.port 8600` |
| Larger exports | raise `maxUploadSize` |
| Open a browser tab on start | `headless = false` |

> **Do not set `address = "0.0.0.0"`** to reach the application from other computers. The
> application has no login: the role switch between management and social worker is a view, not
> a protection. If several people need it, run it behind a reverse proxy with authentication,
> inside the ASD network, and clear that with data protection first.

Keep `gatherUsageStats = false`.

## 7. Working with real exports

1. Export the tables from the case-management system as `.xlsx`. The file names do not matter;
   the application recognises each table by its columns.
2. Start the application, choose **Eigene Exporte hochladen** (upload own exports) in the
   sidebar and drag all files into the upload field at once.
3. Open the **Datenqualität** (data quality) tab. It lists which file was recognised as which
   table, files that were not recognised, unknown columns, invalid dates and rows without a
   matching client.

The minimum set:

| Goal | Exports needed |
|---|---|
| all | Klient |
| Goal 1 · language A1 | Asylgeschäftsdaten, Sprachstand |
| Goal 2 · work / training | Erwerb and/or Integrationsförderung und Ausbildung |
| Goal 3 · no social assistance | Finanzielle Unterstützung |
| Patterns, households | Dossierperson, Unterbringung, Integrationsförderung (more data, more features) |
| Cross-checks | Integrationszielerreichung, ZEMIS Tätigkeit, Asylverfahrensstand |

If a real export uses a column header the application does not know, it appears as "Unbekannte
Spalten ignoriert" (unknown columns ignored) in *Datenqualität*. Add the header to the alias
list of the matching field in `cockpit/schema.py`. Five of the eleven layouts were derived from
the data model rather than from real templates and are the most likely to need this: Klient,
Sprachstand, Integrationsförderung, Integrationszielerreichung, Unterbringung.

## 8. Regenerating the demo data

```powershell
python -m synth.generate --out data/synthetic --households 220 --seed 42
```

This overwrites `data/synthetic/`, `data/situationsanalysen/` and
`data/situationsanalyse_ground_truth.csv`. The same seed always produces the same data. A
different number of households or another seed gives another population, and the LLM cache
then no longer matches. Afterwards, recreate the rule-based feature file:

```powershell
python -m cockpit.situationsanalyse data/situationsanalysen --methode regeln --out data/synthetic/Situationsanalyse_Merkmale.xlsx
```

## 9. Running the tests

```powershell
python -m pytest -q
```

Run it from the project folder. The expected result is `54 passed`. Use `python -m pytest`
rather than plain `pytest`: the `-m` form is what puts the project folder on the import path.

## 10. Updating and uninstalling

Update:

```powershell
git pull
```

```powershell
pip install -r requirements.txt
```

Uninstall: stop the application and delete the project folder; the virtual environment is
inside it. If you installed Ollama only for this, remove the model with `ollama rm qwen3:4b`
and uninstall Ollama like any other program.

## 11. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `streamlit` is not recognised | The virtual environment is not active. Run `.venv\Scripts\Activate.ps1`, or call `.venv\Scripts\streamlit.exe` directly. |
| `ModuleNotFoundError` | Packages missing in this environment: `pip install -r requirements.txt` with the environment active. |
| Port 8501 already in use | Another instance is running. Stop it, or use `--server.port 8600`. |
| "Bitte die Excel-Exporte hochladen" (please upload the exports) | No file uploaded yet, or none was recognised. Check *Datenqualität*. |
| A goal is missing in the sidebar, with "Für Ziel N fehlen die Exporte" | The exports for that goal were not uploaded; see the table in [section 7](#7-working-with-real-exports). |
| "Export Klient fehlt oder ist unvollständig" | The Klient export is missing or lacks *Zuständigkeitsende* or *Geburtsdatum*, the two columns used to recognise it. |
| A file is reported as "keiner bekannten Tabelle zugeordnet" (not matched to a table) | Its headers differ from every known spelling. Compare them with `cockpit/schema.py`. |
| Many "Ungültiges Datum" (invalid date) warnings | Dates in a format other than `dd.mm.yyyy`, `yyyy-mm-dd`, `dd/mm/yyyy` or an Excel date. Correct them in the export. |
| "Lokales LLM nicht erreichbar" (local LLM not reachable) | Ollama is not running, or the model is missing. Start Ollama and check `ollama list`. |
| *LLM lokal* missing in the sidebar | `data/situationsanalyse_merkmale_llm.xlsx` does not exist; see [section 5.1](#51-llm-features-for-the-demo-data). |
| Tests fail with `ModuleNotFoundError: cockpit` | Run `python -m pytest` from the project folder. |
| A change in `rules.yaml` does not change the numbers | The results are cached. Menu **⋮ → Clear cache**, or press `C`, or restart. |
| The application is slow after changing the date | Every new Stichtag recomputes all goals once; later clicks use the cache. |
