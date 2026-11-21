# Integrations-Cockpit: instalare și configurare

*Versiuni: [English](../en/installation.md) · Română (acest fișier)*

Vezi și: [Documentație tehnică](documentatie-tehnica.md) · [Manual de utilizare](manual-utilizare.md)

---

## Cuprins

1. [Ce instalezi](#1-ce-instalezi)
2. [Cerințe](#2-cerințe)
3. [Instalare](#3-instalare)
4. [Prima pornire și verificare](#4-prima-pornire-și-verificare)
5. [Opțional: LLM local pentru Situationsanalysen](#5-opțional-llm-local-pentru-situationsanalysen)
6. [Configurare](#6-configurare)
7. [Lucrul cu exporturi reale](#7-lucrul-cu-exporturi-reale)
8. [Regenerarea datelor demo](#8-regenerarea-datelor-demo)
9. [Rularea testelor](#9-rularea-testelor)
10. [Actualizare și dezinstalare](#10-actualizare-și-dezinstalare)
11. [Rezolvarea problemelor](#11-rezolvarea-problemelor)

---

## 1. Ce instalezi

O aplicație web scrisă în Python. Rulează pe **un singur calculator**, iar utilizatorii o deschid
într-un browser pe același calculator. Nu stochează nimic: exporturile Excel sunt încărcate,
prelucrate în memorie, iar rezultatul este descărcat.

| Componentă | Obligatorie | Rol |
|---|---|---|
| Python 3.12 + pachetele din `requirements.txt` | da | Aplicația |
| Un browser (Chrome, Edge, Firefox) | da | Interfața |
| [Ollama](https://ollama.com) cu modelul `qwen3:4b` | nu | Citirea rapoartelor în text liber Situationsanalysen cu un model AI local. Fără el se folosesc reguli pe cuvinte cheie. |
| Git | nu | Descărcarea codului și a actualizărilor |

## 2. Cerințe

| | Minim | Recomandat |
|---|---|---|
| Sistem de operare | Windows 10/11, macOS sau Linux | Windows 11 (comenzile de mai jos sunt pentru PowerShell) |
| Python | 3.11 | 3.12 (testat cu 3.12.10) |
| Memorie | 4 GB | 8 GB; 16 GB cu LLM-ul local |
| Disc | 500 MB | 4 GB cu LLM-ul local (modelul ocupă 2,5 GB) |
| Rețea | deloc în timpul rulării | Internet doar la instalare, pentru pachete și model |

Verifică Python:

```powershell
python --version
```

Dacă lipsește, instalează-l de pe [python.org](https://www.python.org/downloads/). Pe Windows,
bifează **Add python.exe to PATH** în timpul instalării.

## 3. Instalare

### 3.1 Descarcă codul

Cu Git:

```powershell
git clone https://github.com/cristiv123/integrations-cockpit.git
cd integrations-cockpit
```

Fără Git: pe pagina GitHub alege **Code → Download ZIP**, dezarhivează și deschide PowerShell în
folderul dezarhivat.

### 3.2 Creează un mediu virtual și instalează pachetele

Mediul virtual ține pachetele aplicației separat de restul sistemului.

```powershell
python -m venv .venv
```

```powershell
.venv\Scripts\Activate.ps1
```

```powershell
pip install -r requirements.txt
```

Pe macOS și Linux comanda de activare este `source .venv/bin/activate`.

Dacă PowerShell refuză să ruleze scriptul de activare („running scripts is disabled”), permite-l
doar pentru fereastra curentă:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Pachetele au versiuni fixe în `requirements.txt`: Streamlit 1.67.0, pandas 3.1.1, openpyxl 3.1.5,
PyYAML 6.0.3, Altair 6.3.0, python-docx 1.2.0, pypdf 7.1.1, requests 2.34.2 și pytest 9.2.0.

## 4. Prima pornire și verificare

Cu mediul virtual activ:

```powershell
streamlit run app.py
```

Deschide **http://localhost:8501** în browser. Prima încărcare durează aproximativ 20 de secunde.

Verifică dacă instalarea funcționează:

1. În bara laterală e selectat **Synthetische Demodaten** (date demo sintetice), iar textul de
   sub el arată numărul de fișiere încărcate din `data/synthetic`.
2. Antetul arată șase cifre, iar fila **Cockpit** arată un tabel cu cercuri colorate.
3. **Ergebnis als Excel** (rezultatul ca Excel), jos în bara laterală, descarcă un registru.

Oprește aplicația cu **Ctrl+C** în fereastra PowerShell.

Pentru o pornire ulterioară, fără reactivarea mediului:

```powershell
.venv\Scripts\streamlit.exe run app.py
```

## 5. Opțional: LLM local pentru Situationsanalysen

*Situationsanalysen* sunt rapoarte Word în text liber. Aplicația le transformă în cinci
caracteristici per persoană (povară psihică, motivație, ritm de învățare, obligații de îngrijire,
rețea socială). Poate face asta cu reguli pe cuvinte cheie, care nu cer nimic în plus, sau cu un
model de limbaj care rulează **pe același calculator**.

1. Instalează Ollama de pe [ollama.com/download](https://ollama.com/download). Pornește în fundal
   și ascultă pe `http://localhost:11434`.
2. Descarcă modelul, aproximativ 2,5 GB:

   ```powershell
   ollama pull qwen3:4b
   ```

3. Verifică dacă modelul e prezent:

   ```powershell
   ollama list
   ```

4. Repornește aplicația. În fila **Situationsanalysen** apare acum metoda
   **LLM lokal (qwen3:4b, Ollama)**. Dacă Ollama nu răspunde, fila spune asta și rămân disponibile
   doar regulile.

### 5.1 Caracteristici LLM pentru datele demo

Comutatorul din bara laterală **Situationsanalyse-Merkmale: Regeln / LLM lokal** oferă *LLM lokal*
doar după ce există fișierul `data/situationsanalyse_merkmale_llm.xlsx`. Fișierul nu e în
repository. Îl creezi cu:

```powershell
python -m cockpit.situationsanalyse data/situationsanalysen --methode llm --cache data/cache/situationsanalyse_llm.jsonl --truth data/situationsanalyse_ground_truth.csv --out data/situationsanalyse_merkmale_llm.xlsx
```

| Opțiune | Semnificație |
|---|---|
| `--methode llm` / `regeln` | Folosește modelul sau regulile pe cuvinte cheie |
| `--model` | Numele modelului Ollama, implicit `qwen3:4b` |
| `--workers N` | Persoane prelucrate în paralel; pe un laptop rămâi la 1–2 |
| `--cache fisier.jsonl` | Salvează fiecare rezultat, ca o rulare întreruptă să continue de unde a rămas. Repository-ul conține deja rezultatele pentru 326 din cele 417 persoane demo. |
| `--truth fisier.csv` | După rulare, afișează rata de potrivire per caracteristică (doar pentru datele demo) |
| `--limit N` | Prelucrează doar primele N fișiere, pentru un test rapid |

Pe un procesor obișnuit (CPU) durează aproximativ 20 de secunde per persoană.

## 6. Configurare

### 6.1 Regulile de business: `rules.yaml`

Tot ce lasă neclar descrierea challenge-ului este o setare în `rules.yaml`: cine contează drept
client actual, termenele, vârsta minimă, certificatele de limbă acceptate, pragul de 60 %, modul
în care se tratează joburile paralele, ce tipuri de sprijin înseamnă ajutor social, mărimea
minimă a grupului pentru tipare și altele. Fiecare setare are un comentariu explicativ.

- Editează fișierul cu orice editor de text și salvează-l **în UTF-8**.
- Modificarea are efect la următorul clic în aplicație sau la reîncărcarea paginii; nu e nevoie
  de repornire.
- Fila **Annahmen** (ipoteze) arată regulile în vigoare, iar rezultatul Excel le conține pe foaia
  *Annahmen*. Astfel un rezultat documentează mereu regulile cu care a fost calculat.

Modificări frecvente:

| Nevoie | Setare |
|---|---|
| Un tip nou de certificat contează pentru A1 | adaugă-l în `goal1.accepted_proofs`; o listă goală `[]` acceptă orice tip de dovadă |
| Două joburi de 30 % să *nu* se adune la 60 % | `goal2.sum_parallel_jobs: false` |
| Se acceptă o pauză scurtă între două joburi | `goal2.max_gap_days: 14` |
| Formarea contează doar după absolvire | `goal2.education_counts_from: abschluss` |
| Avertizare mai devreme | mărește `goalN.risk_months` |
| Analiza tiparelor pe asistenți sociali | `level2.include_case_worker: true`, **doar cu acordul angajaților** |

> Păstrează mărimea minimă a grupului, `level2.min_group_size`, la 10 sau mai mult. Ea împiedică
> concluziile despre persoane individuale.

O greșeală de sintaxă YAML oprește aplicația cu un mesaj de eroare care indică linia. Păstrează o
copie înainte de editare.

### 6.2 Serverul: `.streamlit/config.toml`

```toml
[browser]
gatherUsageStats = false     # nu se trimit statistici de utilizare către Streamlit

[server]
address = "localhost"        # accesibil doar de pe acest calculator
headless = true              # nu deschide automat o fereastră de browser
maxUploadSize = 200          # MB per upload

[theme]
base = "light"
primaryColor = "#1F4E78"
```

| Nevoie | Modificare |
|---|---|
| Alt port | pornește cu `streamlit run app.py --server.port 8600` |
| Exporturi mai mari | mărește `maxUploadSize` |
| Deschide un tab de browser la pornire | `headless = false` |

> **Nu seta `address = "0.0.0.0"`** ca să accesezi aplicația de pe alte calculatoare. Aplicația
> nu are autentificare: comutarea rolului între conducere și asistent social e un mod de
> afișare, nu o protecție. Dacă mai multe persoane au nevoie de ea, rulează-o în spatele unui
> reverse proxy cu autentificare, în rețeaua ASD, și lămurește întâi aspectele de protecție a
> datelor.

Păstrează `gatherUsageStats = false`.

## 7. Lucrul cu exporturi reale

1. Exportă tabelele din sistemul de gestiune a cazurilor ca `.xlsx`. Numele fișierelor nu
   contează; aplicația recunoaște fiecare tabel după coloane.
2. Pornește aplicația, alege **Eigene Exporte hochladen** (încarcă exporturi proprii) în bara
   laterală și trage toate fișierele deodată în câmpul de upload.
3. Deschide fila **Datenqualität** (calitatea datelor). Ea arată ce fișier a fost recunoscut ca
   ce tabel, fișierele nerecunoscute, coloanele necunoscute, datele invalide și rândurile fără
   client corespunzător.

Setul minim:

| Obiectiv | Exporturi necesare |
|---|---|
| toate | Klient |
| Obiectivul 1 · limba A1 | Asylgeschäftsdaten, Sprachstand |
| Obiectivul 2 · muncă / formare | Erwerb și/sau Integrationsförderung und Ausbildung |
| Obiectivul 3 · fără ajutor social | Finanzielle Unterstützung |
| Tipare, gospodării | Dossierperson, Unterbringung, Integrationsförderung (mai multe date, mai multe caracteristici) |
| Verificări încrucișate | Integrationszielerreichung, ZEMIS Tätigkeit, Asylverfahrensstand |

Dacă un export real folosește un antet de coloană pe care aplicația nu îl cunoaște, el apare ca
„Unbekannte Spalten ignoriert” (coloane necunoscute ignorate) în *Datenqualität*. Adaugă antetul
în lista de aliasuri a câmpului potrivit din `cockpit/schema.py`. Cinci din cele unsprezece
structuri au fost deduse din modelul de date, nu din șabloane reale, și sunt cele mai probabile
să aibă nevoie de asta: Klient, Sprachstand, Integrationsförderung, Integrationszielerreichung,
Unterbringung.

## 8. Regenerarea datelor demo

```powershell
python -m synth.generate --out data/synthetic --households 220 --seed 42
```

Comanda suprascrie `data/synthetic/`, `data/situationsanalysen/` și
`data/situationsanalyse_ground_truth.csv`. Aceeași sămânță (seed) produce mereu aceleași date. Alt
număr de gospodării sau altă sămânță dă altă populație, iar cache-ul LLM nu se mai potrivește.
După aceea, recreează fișierul de caracteristici pe bază de reguli:

```powershell
python -m cockpit.situationsanalyse data/situationsanalysen --methode regeln --out data/synthetic/Situationsanalyse_Merkmale.xlsx
```

## 9. Rularea testelor

```powershell
python -m pytest -q
```

Rulează comanda din folderul proiectului. Rezultatul așteptat este `54 passed`. Folosește
`python -m pytest`, nu doar `pytest`: forma cu `-m` pune folderul proiectului pe calea de import.

## 10. Actualizare și dezinstalare

Actualizare:

```powershell
git pull
```

```powershell
pip install -r requirements.txt
```

Dezinstalare: oprește aplicația și șterge folderul proiectului; mediul virtual e în interiorul
lui. Dacă ai instalat Ollama doar pentru aplicație, șterge modelul cu `ollama rm qwen3:4b` și
dezinstalează Ollama ca pe orice alt program.

## 11. Rezolvarea problemelor

| Simptom | Cauză și soluție |
|---|---|
| `streamlit` nu e recunoscut | Mediul virtual nu e activ. Rulează `.venv\Scripts\Activate.ps1` sau apelează direct `.venv\Scripts\streamlit.exe`. |
| `ModuleNotFoundError` | Lipsesc pachete în acest mediu: `pip install -r requirements.txt`, cu mediul activ. |
| Portul 8501 e ocupat | Rulează deja o instanță. Oprește-o sau folosește `--server.port 8600`. |
| „Bitte die Excel-Exporte hochladen” (încarcă exporturile) | Niciun fișier încărcat încă, sau niciunul recunoscut. Verifică *Datenqualität*. |
| Un obiectiv lipsește din bara laterală, cu „Für Ziel N fehlen die Exporte” | Exporturile pentru acel obiectiv nu au fost încărcate; vezi tabelul din [secțiunea 7](#7-lucrul-cu-exporturi-reale). |
| „Export Klient fehlt oder ist unvollständig” | Exportul Klient lipsește sau nu are coloanele *Zuständigkeitsende* sau *Geburtsdatum*, cele două după care e recunoscut. |
| Un fișier e raportat ca „keiner bekannten Tabelle zugeordnet” (nepotrivit cu niciun tabel) | Antetele lui diferă de toate variantele cunoscute. Compară-le cu `cockpit/schema.py`. |
| Multe avertismente „Ungültiges Datum” (dată invalidă) | Date în alt format decât `dd.mm.yyyy`, `yyyy-mm-dd`, `dd/mm/yyyy` sau dată Excel. Corectează-le în export. |
| „Lokales LLM nicht erreichbar” (LLM-ul local nu răspunde) | Ollama nu rulează sau lipsește modelul. Pornește Ollama și verifică `ollama list`. |
| *LLM lokal* lipsește din bara laterală | Nu există `data/situationsanalyse_merkmale_llm.xlsx`; vezi [secțiunea 5.1](#51-caracteristici-llm-pentru-datele-demo). |
| Testele eșuează cu `ModuleNotFoundError: cockpit` | Rulează `python -m pytest` din folderul proiectului. |
| O modificare în `rules.yaml` nu apare încă | Apasă oriunde în aplicație sau reîncarcă pagina. Verifică dacă fișierul a fost salvat în UTF-8 și dacă fila *Annahmen* arată valoarea nouă. |
| Aplicația e lentă după schimbarea datei | Fiecare Stichtag nou recalculează o dată toate obiectivele; clicurile următoare folosesc cache-ul. |
