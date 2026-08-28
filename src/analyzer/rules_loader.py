"""
src/analyzer/rules_loader.py
─────────────────────────────
Loads risk rules from config/risk_rules.yaml.
"""

from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Any
import yaml


@dataclass
class RiskRule:
    id: str
    enabled: bool
    severity: str          # high | medium | low | info
    category: str
    name: str
    description: str
    check: dict
    fix_template: Optional[str] = None


def load_rules(config_path: Optional[str] = None) -> list[RiskRule]:
    """
    Loads rules from risk_rules.yaml.
    If config_path is None, uses the default path.
    """
    if config_path is None:
        config_path = Path(__file__).parent.parent.parent / "config" / "risk_rules.yaml"

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    rules = []
    for raw in data.get("rules", []):
        if not raw.get("enabled", True):
            continue
        rules.append(RiskRule(
            id=raw["id"],
            enabled=raw.get("enabled", True),
            severity=raw["severity"],
            category=raw["category"],
            name=raw["name"],
            description=raw["description"],
            check=raw["check"],
            fix_template=raw.get("fix_template"),
        ))
    return rules
