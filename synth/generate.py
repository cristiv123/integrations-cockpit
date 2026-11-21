"""Synthetische Testdaten im Format der 11 Exporte (keine echten Personen).

    python -m synth.generate --out data/synthetic --households 220 --seed 42
"""

from __future__ import annotations

import argparse
import math
import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from cockpit.schema import export_headers

STICHTAG = date(2026, 11, 20)

FILE_NAMES = {
    "klient": "Hackathon_Klient_Resultat.xlsx",
    "asylverfahrensstand": "Hackathon_Asylverfahrensstand_Resultat.xlsx",
    "asylgeschaeftsdaten": "Hackathon_Asylgesch_ftsdaten_Resultat.xlsx",
    "dossierperson": "Hackathon_Dossierperson_Resultat.xlsx",
    "finanzielle_unterstuetzung": "Hackathon_Finanzielle_Unterst_tzung_Resultat.xlsx",
    "unterbringung": "Hackathon_Unterbringung_Resultat.xlsx",
    "sprachstand": "Hackathon_Sprachstand_Resultat.xlsx",
    "integrationsfoerderung": "Hackathon_Integrationsförderung und Ausbildung_Resultat.xlsx",
    "erwerb": "Hackathon_Erwerb_Resultat.xlsx",
    "zemis_taetigkeit": "Hackathon_ZEMIS_T_tigkeit_Resultat.xlsx",
    "integrationszielerreichung": "Hackathon_Integrationszielerreichung_Resultat.xlsx",
}
# Manche Exporte liefern Datum als Text (dd.mm.yyyy), andere als Excel-Datum – beides muss funktionieren.
TEXT_DATE_TABLES = {"asylgeschaeftsdaten", "sprachstand", "erwerb"}

SOZIALARBEITENDE = ["Keller Anna", "Brunner Marc", "Meier Sandra", "Zbinden Luca", "Huber Nadia", "Schmid Reto", "Gerber Lea", "Roth Samuel"]

NATIONEN = {
    "Afghanistan": (["Dari", "Paschtu"], False, (0, 12)),
    "Eritrea": (["Tigrinya"], False, (2, 12)),
    "Syrien": (["Arabisch", "Kurdisch"], False, (4, 15)),
    "Türkei": (["Türkisch", "Kurdisch"], True, (5, 16)),
    "Sri Lanka": (["Tamil"], False, (6, 14)),
    "Irak": (["Arabisch", "Kurdisch"], False, (3, 14)),
    "Somalia": (["Somali"], True, (0, 10)),
    "Ukraine": (["Ukrainisch", "Russisch"], False, (10, 17)),
}
STATUS_WEIGHTS = {"VA": 30, "B-FL": 28, "F-FL": 10, "B-RSFL": 5, "B-SL": 3, "N": 9, "S": 15}
SUFFIX = {"VA": "+7", "F-FL": "+7", "B-FL": "+5", "B-RSFL": "+7", "B-SL": "+5"}
ERLEDIGUNG = {
    "B-FL": "Asylgewährung Art. 3, 7",
    "B-RSFL": "Asylgewährung Art. 51.1",
    "B-SL": "Anerkennung Staatenlosigkeit",
    "F-FL": "Ablehnung mit Fl.-Eigenschaft Art 3, 7",
    "VA": "Ablehnung",
}
VORNAMEN = {"weiblich": ["Amina", "Fatima", "Selam", "Mariam", "Leyla", "Hawa", "Nour", "Tsega", "Zainab", "Olena"],
            "männlich": ["Ahmad", "Yonas", "Mohammed", "Ali", "Dawit", "Hassan", "Omar", "Mehmet", "Abdi", "Taras"]}
NACHNAMEN = ["Haidari", "Tesfay", "Al-Hassan", "Yilmaz", "Kanagaratnam", "Rahimi", "Abdullahi", "Kebede", "Mustafa", "Shevchenko"]

PHRASES = {
    "psychische_belastung": {
        "ja": ["Berichtet von Schlafstörungen und belastenden Erinnerungen an die Flucht.",
               "Leidet unter depressiven Verstimmungen, ist in Behandlung im Ambulatorium für Folter- und Kriegsopfer SRK.",
               "Wirkt oft erschöpft und niedergeschlagen; Verdacht auf PTBS, Abklärung läuft.",
               "Starke Sorgen um Angehörige im Herkunftsland, kann sich deshalb kaum konzentrieren."],
        "nein": ["Psychisch stabil, keine Hinweise auf Belastungen.", "Wirkt ausgeglichen und belastbar.",
                 "Keine psychischen Beschwerden bekannt."],
    },
    "lernmotivation": {
        "hoch": ["Sehr motiviert, möchte rasch Deutsch lernen und arbeiten.",
                 "Zeigt grosse Eigeninitiative, besucht freiwillig zusätzlich ein Sprachcafé.",
                 "Hat klare Ziele und verfolgt diese engagiert."],
        "mittel": ["Grundsätzlich motiviert, braucht aber regelmässige Unterstützung und Erinnerungen.",
                   "Motivation schwankend, je nach familiärer Situation."],
        "tief": ["Wenig Interesse an Kursen, erscheint unregelmässig.",
                 "Sieht im Moment keinen Sinn im Deutschlernen, will zuerst den Familiennachzug regeln.",
                 "Motivation gering, Termine werden oft verpasst."],
    },
    "lerntempo": {
        "schnell": ["Lernt schnell und selbständig.", "Macht rasche Fortschritte im Deutschkurs."],
        "mittel": ["Lerntempo im üblichen Bereich.", "Kommt im Kurs normal mit."],
        "langsam": ["Lernt langsam, braucht viele Wiederholungen.",
                    "Tut sich schwer mit dem Lernen, kaum Lernerfahrung aus der Schulzeit."],
    },
    "betreuung_hindernis": {
        "ja": ["Betreut die kleinen Kinder zuhause, kein Kita-Platz gefunden – kann Kurse nur sehr eingeschränkt besuchen.",
               "Verfügbarkeit stark eingeschränkt wegen Kinderbetreuung.",
               "Kann wegen der Betreuung des Kleinkindes nur an zwei Vormittagen pro Woche."],
        "nein": ["Voll verfügbar für Kurse und Arbeit, keine Betreuungspflichten.",
                 "Kinderbetreuung ist über die Kita geregelt, voll verfügbar.",
                 "Zeitlich flexibel verfügbar."],
    },
    "soziales_netz": {
        "gut": ["Gut vernetzt in der Community, regelmässiger Kontakt zu einer Freiwilligen (Tandem).",
                "Hat Verwandte in Bern, die im Alltag unterstützen.", "Aktiv im Quartiertreff, viele Kontakte."],
        "schwach": ["Kaum soziale Kontakte ausserhalb der Familie.",
                    "Isoliert, kennt ausser der Sozialarbeiterin kaum jemanden in Bern."],
    },
}
FILLER = {
    "phys": ["Keine körperlichen Einschränkungen.", "Rückenschmerzen, in hausärztlicher Behandlung.", "Allgemein guter Gesundheitszustand."],
    "kommunikation": ["Verständigung mit Dolmetscher/in.", "Verständigung teilweise auf Englisch.", "Einfache Gespräche auf Deutsch möglich."],
    "perspektive": ["Möchte in der Pflege arbeiten.", "Interesse an einer Lehre im Detailhandel.", "Möchte als Koch arbeiten.",
                    "Hat im Herkunftsland als Schneider gearbeitet und möchte daran anknüpfen.", "Noch keine klaren Vorstellungen."],
    "wohnen": ["Lebt in der Kollektivunterkunft Zieglerspital.", "Wohnt in einer 3-Zimmer-Wohnung in Bümpliz.", "Wohnungssuche läuft."],
    "familie": ["Ehepaar mit Kindern, weitere Familienangehörige im Herkunftsland.", "Alleinstehend, Eltern im Herkunftsland.",
                "Familiennachzug ist ein grosses Thema."],
}

BETRIEBE = ["Alpha-Home GmbH", "Alters- und Pflegeheim Wattenwil", "Altersbetreuung Worb", "Adecco", "Coop Bern", "Migros Aare",
            "Hotel Bellevue Palace", "Inselspital Bern", "Reinigung Blitzblank AG", "Bäckerei Reinhard", "Post CH AG Logistik", "BERNMOBIL"]


def rdate(rng: random.Random, start: date, end: date) -> date:
    return start + timedelta(days=rng.randint(0, max(0, (end - start).days)))


def add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)


def add_months(d: date, months: float) -> date:
    return d + timedelta(days=int(months * 30.44))


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def education_label(years: int) -> str:
    if years == 0:
        return "keine"
    if years < 6:
        return "Primarschule nicht abgeschlossen"
    if years < 9:
        return "Primarschule"
    if years < 12:
        return "Sekundarstufe I"
    if years < 15:
        return "Sekundarstufe II"
    return "Tertiär"


def generate(households: int = 220, seed: int = 42, stichtag: date = STICHTAG) -> dict[str, list[dict]]:
    rng = random.Random(seed)
    extra = random.Random(seed + 7)  # eigene Zufallsfolge, damit Ergänzungen die übrigen Daten nicht verändern
    rows: dict[str, list[dict]] = {t: [] for t in FILE_NAMES}
    rows["_situationsanalyse"] = []
    next_client = 20001
    used_zemis: set[int] = set()
    sw_skill = {sw: rng.uniform(-0.4, 0.4) for sw in SOZIALARBEITENDE}

    def new_zemis() -> int:
        while True:
            z = rng.randint(10_000_000, 99_999_999)
            if z not in used_zemis:
                used_zemis.add(z)
                return z

    for h in range(households):
        status = rng.choices(list(STATUS_WEIGHTS), weights=list(STATUS_WEIGHTS.values()))[0]
        if status == "S":
            nation = "Ukraine"
            entry = rdate(rng, date(2022, 3, 1), date(2026, 8, 31))
        else:
            nation = rng.choice([n for n in NATIONEN if n != "Ukraine"])
            entry = rdate(rng, date(2018, 6, 1), date(2026, 8, 31) if status != "N" else date(2026, 9, 30))
            if status == "N":
                entry = rdate(rng, date(2025, 9, 1), date(2026, 9, 30))
        languages, latin_script, school_range = NATIONEN[nation]
        dossier = f"D12.{10000 + h}"
        sw = rng.choice(SOZIALARBEITENDE)
        application = entry + timedelta(days=rng.randint(1, 14))
        decision = application + timedelta(days=rng.randint(60, 540))
        zust_beginn = entry + timedelta(days=rng.randint(30, 150))
        if status in ("B-FL", "B-RSFL", "B-SL"):
            zust_ende = add_years(application, 5)
        elif status in ("VA", "F-FL"):
            zust_ende = add_years(entry, 7)
        else:
            zust_ende = None
        if status not in ("N", "S") and decision > stichtag:
            decision = stichtag - timedelta(days=rng.randint(5, 60))
        ended = zust_ende is not None and zust_ende < stichtag
        current_status = status + SUFFIX[status] if ended and status in SUFFIX else status
        uebergang = zust_ende + timedelta(days=1) if ended else None
        in_sozialhilfe = rng.random() < 0.8

        members = [("Dossierträger/-in", rng.randint(19, 52))]
        if rng.random() < 0.55:
            members.append(("Ehefrau / -mann", max(18, members[0][1] + rng.randint(-8, 6))))
        for _ in range(rng.choices([0, 1, 2, 3, 4], weights=[30, 20, 25, 15, 10])[0]):
            members.append(("Tochter / Sohn", rng.randint(0, 17)))
        young_kids = sum(1 for r, a in members if r == "Tochter / Sohn" and a < 4)
        netz = rng.choice(["gut", "schwach"])
        doc = {"dossier": dossier, "entry": entry, "sw": sw, "soziales_netz": netz, "persons": [],
               "omit_netz": rng.random() < 0.1}

        household_job_start: date | None = None
        for idx, (relation, age_at_entry) in enumerate(members):
            k = next_client
            next_client += 1
            z = new_zemis()
            born_in_ch = relation == "Tochter / Sohn" and rng.random() < 0.08 and entry < stichtag - timedelta(days=400)
            birth = rdate(rng, entry + timedelta(days=30), min(stichtag, entry + timedelta(days=900))) if born_in_ch else entry - timedelta(days=int(age_at_entry * 365.25) + rng.randint(0, 364))
            age_at_entry = 0 if born_in_ch else age_at_entry
            gender = "weiblich" if (relation == "Ehefrau / -mann") or rng.random() < 0.45 else "männlich"
            if relation == "Dossierträger/-in" and len(members) > 1 and members[1][0] == "Ehefrau / -mann":
                gender = "männlich"
            adult = age_at_entry >= 18
            school_years = rng.randint(*school_range) if adult else min(age_at_entry - 6, rng.randint(0, 9)) if age_at_entry > 6 else 0
            school_years = max(0, school_years)
            latin = "ja" if (latin_script and school_years >= 4) or (adult and rng.random() < 0.12) else "nein"
            art_anal = None if latin == "ja" else ("primär" if school_years < 2 else "sekundär")
            work_years = max(0, min(age_at_entry - 16, rng.randint(0, 15))) if adult else 0

            latent = None
            if relation != "Tochter / Sohn":
                tempo_score = school_years / 4 + (latin == "ja") * 1.5 + rng.uniform(-1.5, 1.5)
                latent = {
                    "psychische_belastung": "ja" if rng.random() < 0.3 else "nein",
                    "lernmotivation": rng.choices(["hoch", "mittel", "tief"], weights=[40, 40, 20])[0],
                    "lerntempo": "schnell" if tempo_score > 3.5 else "langsam" if tempo_score < 1.8 else "mittel",
                    "betreuung_hindernis": "ja" if young_kids and rng.random() < (0.7 if gender == "weiblich" else 0.15) else "nein",
                }
                doc["persons"].append({
                    "zemis": z, "vorname": rng.choice(VORNAMEN[gender]), "nachname": rng.choice(NACHNAMEN), "geburtsdatum": birth,
                    "relation": relation, "latent": latent, "omit": {f for f in latent if rng.random() < 0.1},
                })

            rows["klient"].append({
                "klientennummer": k, "zemis": z, "dossier": dossier, "zust_beginn": zust_beginn, "zust_ende": zust_ende,
                "uebergang_gemeinde": uebergang, "status_aktuell": current_status,
                "unterstuetzung_aktuell": "Sozialhilfe" if in_sozialhilfe else "Keine Unterstützung",
                "fallfuehrung": sw, "geburtsdatum": birth, "geschlecht": gender, "nationalitaet": nation,
                "zivilstand": "verheiratet" if relation != "Tochter / Sohn" and len(members) > 1 and members[1][0] == "Ehefrau / -mann" else "ledig",
                "muttersprache": rng.choice(languages), "ausbildung": education_label(school_years) if adult else "obligatorische Schule",
                "schuljahre": school_years, "lateinisch_alphabetisiert": latin, "art_analphabetismus": art_anal,
                "arbeitserfahrung": work_years,
            })
            rows["dossierperson"].append({
                "dossier": dossier, "klientennummer": k, "zemis": z, "von": zust_beginn if not born_in_ch else birth, "bis": None,
                "rolle": "Dossiermitglied", "beziehung": relation,
            })

            if born_in_ch:
                rows["asylgeschaeftsdaten"].append({"zemis": z, "klientennummer": k, "geschaeftsart": "Aufenthalt (Geburt)", "ereignisdatum": birth})
            elif not (h % 97 == 5 and idx == 0):  # wenige Personen ohne Einreise-Ereignis (Datenqualität)
                rows["asylgeschaeftsdaten"].append({"zemis": z, "klientennummer": k, "geschaeftsart": "Aufenthalt (Einreise)", "ereignisdatum": entry})
            if status == "S":
                rows["asylgeschaeftsdaten"].append({"zemis": z, "klientennummer": k, "geschaeftsart": "Gesuch vorübergehender Schutz",
                                                   "ereignisdatum": application, "erledigung": "Gewährung vorübergehender Schutz",
                                                   "erledigungscode": rng.randint(1000, 9999), "erledigungsdatum": application + timedelta(days=rng.randint(3, 30))})
            else:
                decided = status != "N"
                rows["asylgeschaeftsdaten"].append({"zemis": z, "klientennummer": k, "geschaeftsart": "Asylgesuch in CH (Kt normal, Kat. III)",
                                                   "ereignisdatum": application, "erledigung": ERLEDIGUNG.get(status) if decided else None,
                                                   "erledigungscode": rng.randint(1000, 9999) if decided else None,
                                                   "erledigungsdatum": decision if decided else None})

            hist_start = application if not born_in_ch else birth
            if status in ("N", "S"):
                rows["asylverfahrensstand"].append({"zemis": z, "klientennummer": k, "dossier": dossier, "gueltig_ab": hist_start, "gueltig_bis": None,
                                                   "status": "N (Asylsuchende)" if status == "N" else "S"})
            else:
                if not born_in_ch and decision > hist_start:
                    rows["asylverfahrensstand"].append({"zemis": z, "klientennummer": k, "dossier": dossier, "gueltig_ab": hist_start,
                                                       "gueltig_bis": decision - timedelta(days=1), "status": "N (Asylsuchende)"})
                start_final = max(decision, hist_start)
                if ended:
                    rows["asylverfahrensstand"].append({"zemis": z, "klientennummer": k, "dossier": dossier, "gueltig_ab": start_final, "gueltig_bis": zust_ende, "status": status})
                    rows["asylverfahrensstand"].append({"zemis": z, "klientennummer": k, "dossier": dossier, "gueltig_ab": zust_ende + timedelta(days=1), "gueltig_bis": None, "status": current_status})
                else:
                    rows["asylverfahrensstand"].append({"zemis": z, "klientennummer": k, "dossier": dossier, "gueltig_ab": start_final, "gueltig_bis": None, "status": status})

            move_out = zust_beginn + timedelta(days=rng.randint(180, 540))
            rows["unterbringung"].append({"klientennummer": k, "von": zust_beginn, "bis": min(move_out, stichtag) if move_out < stichtag else None,
                                          "art": "Kollektivunterkunft", "plz": 3027, "ort": "Bern"})
            if move_out < stichtag:
                rows["unterbringung"].append({"klientennummer": k, "von": move_out + timedelta(days=1), "bis": None,
                                              "art": rng.choice(["Wohnung", "Wohnung", "WG", "Gastfamilie"]), "plz": rng.choice([3004, 3006, 3007, 3008, 3011, 3012, 3013, 3014, 3018, 3027]), "ort": "Bern"})

            # Sprache – Erfolgswahrscheinlichkeit hängt bewusst von Schulbildung, Alphabetisierung, Alter und Fallführung ab,
            # damit die Mustersuche (Level 2) etwas findet.
            if age_at_entry >= 4 or born_in_ch:
                child = age_at_entry < 16
                rows["sprachstand"].append({"zemis": z, "klientennummer": k, "sprache": "Deutsch", "niveau": "A0",
                                            "nachweis": "Einschätzung Sozialarbeit", "datum": zust_beginn + timedelta(days=rng.randint(5, 40))})
                soft = 0.0
                if latent:
                    soft = (-0.9 * (latent["psychische_belastung"] == "ja")
                            + {"hoch": 0.7, "mittel": 0.0, "tief": -0.9}[latent["lernmotivation"]]
                            - 0.8 * (latent["betreuung_hindernis"] == "ja") + 0.35 * (netz == "gut"))
                logit = (-0.6 + 0.17 * school_years + 1.1 * (latin == "ja") - 0.045 * max(0, age_at_entry - 25)
                         + soft + sw_skill[sw] + (2.5 if child else 0))
                reaches = rng.random() < sigmoid(logit)
                speed = 10 if latin == "ja" else 22
                months = rng.triangular(5, 54, speed + max(0, 12 - school_years))
                reach_date = add_months(entry, months)
                if reaches and reach_date <= stichtag:
                    if child or born_in_ch:
                        proof = "Schulbesuch Schweiz"
                    else:
                        proof = rng.choices(["Zertifikat telc", "Zertifikat fide", "Abgeschlossene Ausbildung"], weights=[45, 45, 10])[0]
                    level = "A1" if not child else rng.choice(["A2", "B1"])
                    rows["sprachstand"].append({"zemis": z, "klientennummer": k, "sprache": "Deutsch", "niveau": level, "nachweis": proof,
                                                "datum": reach_date, "bemerkungen": proof.replace("Zertifikat ", "") if "Zertifikat" in proof else None})
                    if not child and rng.random() < 0.35 and add_months(reach_date, 10) < stichtag:
                        rows["sprachstand"].append({"zemis": z, "klientennummer": k, "sprache": "Deutsch", "niveau": "A2", "nachweis": proof,
                                                    "datum": add_months(reach_date, rng.randint(9, 20)), "bemerkungen": None})
                    if (not child and reach_date <= add_years(entry, 3) and rng.random() < 0.85
                            and reach_date + timedelta(days=45) < stichtag and status not in ("N", "S")):
                        rows["integrationszielerreichung"].append({"zemis": z, "ziel": "Ziel 1: Sprache A1", "erreicht_am": reach_date + timedelta(days=rng.randint(10, 45)),
                                                                   "partner_region": "Stadt Bern", "kohorte": entry.year, "mit_status_s": "nein"})
                elif not child and rng.random() < 0.25 and add_months(entry, 9) < stichtag:
                    rows["sprachstand"].append({"zemis": z, "klientennummer": k, "sprache": "Deutsch", "niveau": "A1", "nachweis": "Kursbestätigung",
                                                "datum": add_months(entry, rng.randint(9, 30)), "bemerkungen": "kein Zertifikat"})

            if adult or age_at_entry >= 16:
                course_start = zust_beginn + timedelta(days=rng.randint(20, 200))
                if course_start < stichtag:
                    if latin == "nein" and school_years < 6:
                        rows["integrationsfoerderung"].append({"zemis": z, "klientennummer": k, "start": course_start, "abschluss": course_start + timedelta(days=rng.randint(120, 300)),
                                                               "art": "Alphabetisierung", "bezeichnung": "Alphabetisierungskurs", "stunden": rng.choice([4, 6, 8]), "institution": "Volkshochschule Bern"})
                        course_start = course_start + timedelta(days=200)
                    rows["integrationsfoerderung"].append({"zemis": z, "klientennummer": k, "start": course_start, "abschluss": course_start + timedelta(days=rng.randint(150, 360)),
                                                           "art": "Deutschkurs", "bezeichnung": rng.choice(["Deutsch A1 Intensiv", "Deutsch A1/A2", "fide-Vorbereitung"]),
                                                           "stunden": rng.choice([4, 6, 8, 12, 16]), "institution": rng.choice(["ECAP Bern", "Volkshochschule Bern", "Isa Bern", "Klubschule Migros"])})
                if 16 <= age_at_entry <= 25 and rng.random() < 0.5:
                    s = zust_beginn + timedelta(days=rng.randint(200, 500))
                    if s < stichtag:
                        rows["integrationsfoerderung"].append({"zemis": z, "klientennummer": k, "start": s, "abschluss": s + timedelta(days=330), "art": "Brückenangebot",
                                                               "bezeichnung": "Berufsvorbereitendes Schuljahr Integration", "stunden": 28, "institution": "BFF Bern"})
                        if rng.random() < 0.45 and s + timedelta(days=360) < stichtag:
                            rows["integrationsfoerderung"].append({"zemis": z, "klientennummer": k, "start": s + timedelta(days=360), "abschluss": None, "art": "Sek II",
                                                                   "bezeichnung": rng.choice(["Lehre EBA Logistik", "Lehre EFZ Fachfrau/-mann Gesundheit", "Lehre EBA Küchenangestellte/r"]),
                                                                   "stunden": 40, "institution": rng.choice(["Inselspital Bern", "Coop Bern", "Hotel Bellevue Palace"])})
                if school_years >= 15 and rng.random() < 0.15:
                    s = zust_beginn + timedelta(days=rng.randint(400, 900))
                    if s < stichtag:
                        rows["integrationsfoerderung"].append({"zemis": z, "klientennummer": k, "start": s, "abschluss": None, "art": "Tertiär",
                                                               "bezeichnung": "Bachelor Pflege", "stunden": 40, "institution": "Berner Fachhochschule"})

                p_job = sigmoid(-1.2 + 0.12 * school_years + 0.08 * work_years + 0.6 * (latin == "ja") - 0.5 * (gender == "weiblich"))
                if adult and rng.random() < p_job:
                    start = zust_beginn + timedelta(days=rng.randint(150, 1400))
                    goal2_recorded = False
                    while start < stichtag:
                        months = rng.randint(2, 24)
                        end = add_months(start, months)
                        pensum = rng.choice([20, 40, 50, 60, 80, 100, 100])
                        employer = rng.choice(BETRIEBE)
                        program = extra.random() < 0.08
                        if program:
                            employer = "Beschäftigungsprogramm Stadt Bern"
                        done = add_months(start, 6)
                        if (not program and pensum >= 60 and months >= 6 and not goal2_recorded and done + timedelta(days=30) < stichtag
                                and status not in ("N", "S") and extra.random() < 0.8):
                            rows["integrationszielerreichung"].append({"zemis": z, "ziel": "Ziel 2: Erwerb / Ausbildung", "erreicht_am": done + timedelta(days=extra.randint(5, 30)),
                                                                       "partner_region": "Stadt Bern", "kohorte": entry.year, "mit_status_s": "nein"})
                            goal2_recorded = True
                        rows["erwerb"].append({"zemis": z, "klientennummer": k, "von": start, "bis": end if end < stichtag else None, "arbeitgeber": employer,
                                               "arbeitgeber_ort": "Bern", "pensum": pensum, "erwerbsstatus": "unselbstständig",
                                               "einkommen": round(pensum * rng.uniform(38, 55), 2), "stundenlohn": round(rng.uniform(21, 32), 2),
                                               "unregelmaessig": rng.random() < 0.15, "abtretung": rng.random() < 0.3})
                        if rng.random() < 0.9:
                            rows["zemis_taetigkeit"].append({"zemis": z, "klientennummer": k, "arbeitsbeginn": start, "verpflichtet_bis": end, "betrieb": employer})
                        if pensum >= 60 and household_job_start is None:
                            household_job_start = start
                        start = end + timedelta(days=rng.randint(1, 120))
                elif adult and rng.random() < 0.05:
                    s = zust_beginn + timedelta(days=rng.randint(100, 900))
                    if s < stichtag:
                        rows["zemis_taetigkeit"].append({"zemis": z, "klientennummer": k, "arbeitsbeginn": s, "verpflichtet_bis": s + timedelta(days=180),
                                                         "betrieb": "4 You Personal AG / Einsatzort Kanton Basel-Stadt"})

        if doc["persons"] and status != "N":
            rows["_situationsanalyse"].append(doc)

        if status != "N":
            stop = household_job_start + timedelta(days=rng.randint(30, 200)) if household_job_start and rng.random() < 0.6 else None
            if stop and stop < stichtag:
                rows["finanzielle_unterstuetzung"].append({"dossier": dossier, "unterstuetzung": "Sozialhilfe", "gueltig_von": zust_beginn, "gueltig_bis": stop,
                                                           "hauptgrund_beendigung": rng.choice(["Aufnahme einer Erwerbstätigkeit", "Erhöhtes Erwerbseinkommen"])})
                rows["finanzielle_unterstuetzung"].append({"dossier": dossier, "unterstuetzung": "Keine Unterstützung", "gueltig_von": stop + timedelta(days=1), "gueltig_bis": None})
                done = add_months(stop, 12)
                if done + timedelta(days=30) < stichtag and status != "S" and extra.random() < 0.8:
                    head = next(r for r in rows["klient"] if r["dossier"] == dossier)
                    rows["integrationszielerreichung"].append({"zemis": head["zemis"], "ziel": "Ziel 3: Wirtschaftliche Selbständigkeit",
                                                               "erreicht_am": done + timedelta(days=extra.randint(5, 30)), "partner_region": "Stadt Bern",
                                                               "kohorte": entry.year, "mit_status_s": "nein"})
            else:
                rows["finanzielle_unterstuetzung"].append({"dossier": dossier, "unterstuetzung": "Sozialhilfe", "gueltig_von": zust_beginn, "gueltig_bis": None})

    # Datenqualität: kaputtes Datum, fehlendes Datum, verwaiste Zeile
    sprach = rows["sprachstand"]
    certs = [r for r in sprach if r["nachweis"].startswith("Zertifikat")]
    if len(certs) > 3:
        certs[0]["datum"] = "31.02.2023"
        certs[1]["datum"] = None
        certs[2]["datum"] = None
    sprach.append({"zemis": 11111111, "klientennummer": 99999, "sprache": "Deutsch", "niveau": "A1", "nachweis": "Zertifikat fide", "datum": date(2025, 5, 3)})
    return rows


def _fmt(v: object, as_text: bool) -> object:
    if isinstance(v, date):
        return v.strftime("%d.%m.%Y") if as_text else pd.Timestamp(v)
    return v


def write_situationsanalysen(docs: list[dict], out: Path, seed: int) -> Path:
    """Ausgefüllte Situationsanalysen als .docx (Struktur wie die Vorlage) + Ground Truth für die Auswertung der Extraktion."""
    from docx import Document

    rng = random.Random(seed + 1)
    out.mkdir(parents=True, exist_ok=True)
    truth = []

    def say(field: str, value: str, omitted: bool) -> str:
        return "" if omitted else rng.choice(PHRASES[field][value])

    for d in docs:
        doc = Document()
        doc.add_paragraph("Stadt Bern · Direktion für Bildung, Soziales und Sport · Asylsozialdienst")
        doc.add_heading("Situationsanalyse und Potenzialerhebung", level=1)
        doc.add_heading("1. Personalien aller Personen in der Unterstützungseinheit", level=2)
        for i, p in enumerate(d["persons"], start=1):
            doc.add_heading(f"1.{i} {p['relation']}", level=3)
            for line in (f"Name: {p['nachname']}", f"Vorname: {p['vorname']}", f"Geburtsdatum: {p['geburtsdatum']:%d.%m.%Y}",
                         f"Einreisedatum: {d['entry']:%d.%m.%Y}", f"Telefon: 079 {rng.randint(100, 999)} {rng.randint(10, 99)} {rng.randint(10, 99)}",
                         f"Zemis-Nr.: {p['zemis']}", f"Zust. SAR: {d['sw']}"):
                doc.add_paragraph(line)

        doc.add_heading("2. Situationsanalyse", level=2)
        doc.add_heading("2.1 Familiäre Situation, soziales Umfeld", level=3)
        for label, text in (("Familiensystem in der Schweiz und im Herkunftsland:", rng.choice(FILLER["familie"])),
                            ("Soziales Umfeld und Vernetzung Freiwillige:", say("soziales_netz", d["soziales_netz"], d["omit_netz"]))):
            doc.add_paragraph(label)
            doc.add_paragraph(text)
        doc.add_heading("2.2 Wohnen", level=3)
        doc.add_paragraph("Aktuelle Wohnsituation:")
        doc.add_paragraph(rng.choice(FILLER["wohnen"]))

        for i, p in enumerate(d["persons"], start=3):
            lat, om = p["latent"], p["omit"]
            doc.add_heading(f"{i}. Individuelle Potenzialerhebung von {p['nachname']} {p['vorname']}, {p['geburtsdatum']:%d.%m.%Y}", level=2)
            sections = [
                (f"{i}.1 Gesundheit", [("Physischer Gesundheitszustand:", rng.choice(FILLER["phys"])),
                                       ("Psychischer Gesundheitszustand:", say("psychische_belastung", lat["psychische_belastung"], "psychische_belastung" in om))]),
                (f"{i}.2 Sprachliche Integration", [("Lerntempo:", say("lerntempo", lat["lerntempo"], "lerntempo" in om)),
                                                    ("Kommunikation mit Sozialarbeiter/in:", rng.choice(FILLER["kommunikation"]))]),
                (f"{i}.3 Berufliche Integration", [("Verfügbarkeit für Arbeit oder Bildung:", say("betreuung_hindernis", lat["betreuung_hindernis"], "betreuung_hindernis" in om))]),
                (f"{i}.4 Potenzialeinschätzung", [("Berufliche Perspektiven und Vorstellungen aus Sicht Klient/in:", rng.choice(FILLER["perspektive"])),
                                                  ("Einschätzung Potenzial und Motivation aus Sicht Sozialarbeiter/in / externe Abklärung:",
                                                   say("lernmotivation", lat["lernmotivation"], "lernmotivation" in om))]),
            ]
            for heading, fields in sections:
                doc.add_heading(heading, level=3)
                for label, text in fields:
                    doc.add_paragraph(label)
                    doc.add_paragraph(text)
            truth.append({"Zemis-Nr.": p["zemis"], "Dossier-Nr.": d["dossier"],
                          **{f: ("unklar" if f in om else v) for f, v in lat.items()},
                          "soziales_netz": "unklar" if d["omit_netz"] else d["soziales_netz"]})
        doc.save(out / f"Situationsanalyse_{d['dossier']}.docx")

    truth_path = out.parent / "situationsanalyse_ground_truth.csv"
    pd.DataFrame(truth).to_csv(truth_path, index=False, encoding="utf-8-sig")
    return truth_path


def write(rows: dict[str, list[dict]], out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for table, records in rows.items():
        if table.startswith("_"):
            continue
        headers = export_headers(table)
        as_text = table in TEXT_DATE_TABLES
        df = pd.DataFrame([{headers[k]: _fmt(r.get(k), as_text) for k in headers} for r in records], columns=list(headers.values()))
        path = out / FILE_NAMES[table]
        with pd.ExcelWriter(path, engine="openpyxl", datetime_format="DD.MM.YYYY", date_format="DD.MM.YYYY") as xw:
            df.to_excel(xw, sheet_name="Tabelle1", index=False)
        written.append(path)
    return written


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="data/synthetic")
    ap.add_argument("--households", type=int, default=300)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    rows = generate(args.households, args.seed)
    for p in write(rows, Path(args.out)):
        print(p)
    truth = write_situationsanalysen(rows["_situationsanalyse"], Path(args.out).parent / "situationsanalysen", args.seed)
    print(f"{len(rows['klient'])} Personen, {args.households} Haushalte, {len(rows['_situationsanalyse'])} Situationsanalysen (Ground Truth: {truth})")


if __name__ == "__main__":
    main()
