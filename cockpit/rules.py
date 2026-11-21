from pathlib import Path

import yaml

DEFAULT_RULES_PATH = Path(__file__).resolve().parent.parent / "rules.yaml"


def read_rules_text(path: str | Path = DEFAULT_RULES_PATH) -> str:
    return Path(path).read_text(encoding="utf-8")


def rules_from_text(text: str) -> dict:
    return yaml.safe_load(text)


def load_rules(path: str | Path = DEFAULT_RULES_PATH) -> dict:
    return rules_from_text(read_rules_text(path))
