from datetime import date

import pandas as pd
import pytest

from cockpit.goal1 import evaluate_goal1
from cockpit.ingest import load_directory
from cockpit.level2 import SMALL, analyse, wilson
from cockpit.rules import load_rules
from synth.generate import generate, write


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory):
    out = tmp_path_factory.mktemp("synth")
    write(generate(households=200, seed=7, stichtag=date(2026, 11, 20)), out)
    loaded = load_directory(out)
    rules = load_rules()
    result = evaluate_goal1(loaded.tables, rules, pd.Timestamp("2026-11-20"))
    return loaded, rules, result


def test_wilson_interval():
    lo, hi = wilson(50, 100)
    assert lo == pytest.approx(0.404, abs=0.001) and hi == pytest.approx(0.596, abs=0.001)
    assert all(pd.isna(v) for v in wilson(0, 0))


def test_population_only_known_outcomes(synthetic):
    loaded, rules, result = synthetic
    l2 = analyse(result, loaded.tables, rules)
    p = result.persons
    expected = (p["zielgruppe"] & (p["frist"] <= result.stichtag)).sum()
    assert l2.population == expected
    assert 0 < l2.rate < 1


def test_small_groups_are_never_shown(synthetic):
    loaded, rules, result = synthetic
    l2 = analyse(result, loaded.tables, rules)
    k = rules["level2"]["min_group_size"]
    assert (l2.groups["Personen"] >= k).all()
    assert l2.combinations.empty or (l2.combinations["Personen"] >= k).all()


def test_no_person_level_output(synthetic):
    loaded, rules, result = synthetic
    l2 = analyse(result, loaded.tables, rules)
    for df in (l2.groups, l2.strength, l2.combinations):
        assert not {"Klientennummer", "klientennummer", "Zemis-Nr.", "zemis"} & set(df.columns)


def test_planted_pattern_is_found(synthetic):
    loaded, rules, result = synthetic
    g = analyse(result, loaded.tables, rules).groups
    latin = g[g["Merkmal"] == "Lateinisch alphabetisiert"].set_index("Gruppe")["Quote"]
    assert latin["ja"] > latin["nein"]


def test_too_small_population(synthetic):
    loaded, rules, result = synthetic
    rules = {**rules, "level2": {**rules["level2"], "min_group_size": 100_000}}
    l2 = analyse(result, loaded.tables, rules)
    assert l2.groups.empty and "Zu wenige" in l2.insights[0]


def test_small_groups_are_pooled(synthetic):
    loaded, rules, result = synthetic
    g = analyse(result, loaded.tables, rules).groups
    nat = g[g["Merkmal"] == "Nationalität"]
    assert SMALL not in nat["Gruppe"].values or nat.loc[nat["Gruppe"] == SMALL, "Personen"].iloc[0] >= rules["level2"]["min_group_size"]
