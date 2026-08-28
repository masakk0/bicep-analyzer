"""
src/analyzer/risk_engine.py
────────────────────────────
Evaluates risk rules against the infrastructure graph.
Each rule produces zero or more RiskFinding objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.graph.builder import InfraGraph
from src.analyzer.rules_loader import RiskRule, load_rules


@dataclass
class RiskFinding:
    rule_id: str
    rule_name: str
    severity: str
    category: str
    message: str
    resource_symbol: Optional[str]
    resource_name: Optional[str]
    fix_template: Optional[str]

    @property
    def severity_order(self) -> int:
        return {"high": 0, "medium": 1, "low": 2, "info": 3}.get(self.severity, 99)


class RiskEngine:
    """
    Evaluates YAML rules against the graph and returns RiskFinding objects,
    ordered by severity.
    """

    def __init__(self, rules: Optional[list[RiskRule]] = None):
        self.rules = rules or load_rules()

    def evaluate(self, graph: InfraGraph) -> list[RiskFinding]:
        findings: list[RiskFinding] = []
        for rule in self.rules:
            findings.extend(self._apply_rule(rule, graph))
        return sorted(findings, key=lambda f: f.severity_order)

    # ─────────────────────────────────────────────
    # Dispatch by check type.
    # ─────────────────────────────────────────────
    def _apply_rule(self, rule: RiskRule, graph: InfraGraph) -> list[RiskFinding]:
        check_type = rule.check.get("type")
        dispatch = {
            "property_match":            self._check_property_match,
            "missing_dependency":        self._check_missing_dependency,
            "missing_property":          self._check_missing_property,
            "property_contains":         self._check_property_contains,
            "missing_resource_category": self._check_missing_resource_category,
        }
        handler = dispatch.get(check_type)
        if not handler:
            return []
        return handler(rule, graph)

    # ── property_match ─────────────────────────────
    def _check_property_match(self, rule: RiskRule, graph: InfraGraph) -> list[RiskFinding]:
        """Report resources where a property does not have the expected value."""
        prop = rule.check.get("property", "")
        not_eq = rule.check.get("not_equals", "")
        findings = []
        for node in graph.get_all_resources():
            raw = node.get("raw_properties", "")
            if prop in raw and not_eq not in raw:
                findings.append(self._make_finding(rule, node,
                    f"{node['name']}: '{prop}' is not set to '{not_eq}'"))
        return findings

    # ── missing_dependency ─────────────────────────
    def _check_missing_dependency(self, rule: RiskRule, graph: InfraGraph) -> list[RiskFinding]:
        """
        Report resources in a category without a linked requires_linked node.
        """
        categories = rule.check.get("resource_categories", [])
        required_raw = rule.check.get("requires_linked", "")
        # Format: "network:private_endpoint" -> label == "Private Endpoint".
        required_label = self._label_from_key(required_raw)

        findings = []
        for cat in categories:
            for node in graph.get_resources_by_category(cat):
                symbol = node["symbol_name"]
                # Check whether a connected node has the required label.
                connected = graph.get_connected_resources(symbol)
                has_required = any(
                    n.get("label", "").lower() == required_label.lower()
                    for n in connected
                )
                if not has_required:
                    findings.append(self._make_finding(rule, node,
                        f"{node['name']}: missing '{required_label}'"))
        return findings

    # ── missing_property ───────────────────────────
    def _check_missing_property(self, rule: RiskRule, graph: InfraGraph) -> list[RiskFinding]:
        """Report resources of a type that lack a property in the raw text."""
        resource_categories = rule.check.get("resource_types", [])
        resource_labels = rule.check.get("resource_labels", [])
        missing_prop = rule.check.get("missing_property", "")
        findings = []

        for node in graph.get_all_resources():
            cat_match = node.get("category") in resource_categories
            label_match = not resource_labels or node.get("label") in resource_labels
            if cat_match and label_match:
                if missing_prop not in node.get("raw_properties", ""):
                    findings.append(self._make_finding(rule, node,
                        f"{node['name']}: missing '{missing_prop}'"))
        return findings

    # ── property_contains ──────────────────────────
    def _check_property_contains(self, rule: RiskRule, graph: InfraGraph) -> list[RiskFinding]:
        """Report resources whose raw_properties contain specific patterns."""
        resource_categories = rule.check.get("resource_types", [])
        contains_any = rule.check.get("contains_any", [])
        findings = []

        for node in graph.get_all_resources():
            if node.get("category") not in resource_categories:
                continue
            raw = node.get("raw_properties", "").lower()
            if any(kw.lower() in raw for kw in contains_any):
                findings.append(self._make_finding(rule, node,
                    f"{node['name']}: {rule.description.strip()}"))
        return findings

    # ── missing_resource_category ──────────────────
    def _check_missing_resource_category(self, rule: RiskRule, graph: InfraGraph) -> list[RiskFinding]:
        """Report when a category is completely absent from the template."""
        category = rule.check.get("category", "")
        resources = graph.get_resources_by_category(category)
        if not resources:
            return [RiskFinding(
                rule_id=rule.id,
                rule_name=rule.name,
                severity=rule.severity,
                category=rule.category,
                message=rule.description.strip(),
                resource_symbol=None,
                resource_name=None,
                fix_template=rule.fix_template,
            )]
        return []

    # ── Helpers ────────────────────────────────────
    def _make_finding(self, rule: RiskRule, node: dict, message: str) -> RiskFinding:
        return RiskFinding(
            rule_id=rule.id,
            rule_name=rule.name,
            severity=rule.severity,
            category=rule.category,
            message=message,
            resource_symbol=node.get("symbol_name"),
            resource_name=node.get("name"),
            fix_template=rule.fix_template,
        )

    def _label_from_key(self, key: str) -> str:
        """Convert 'network:private_endpoint' to 'Private Endpoint'."""
        if ":" in key:
            _, label_key = key.split(":", 1)
        else:
            label_key = key
        return label_key.replace("_", " ").title()
