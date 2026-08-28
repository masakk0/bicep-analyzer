"""
src/graph/builder.py
─────────────────────
Builds a NetworkX graph from parser output.
Exposes query methods used by both the UI and the agent.
"""

from __future__ import annotations

from typing import Any, Optional
import networkx as nx

from src.parser.bicep_parser import ParseResult, BicepResource, BicepEdge


class InfraGraph:
    """
    Wrapper around a NetworkX DiGraph.
    Each node has BicepResource attributes.
    Each edge has a relationship type.
    """

    def __init__(self, parse_result: ParseResult):
        self.G: nx.DiGraph = nx.DiGraph()
        self._parse_result = parse_result
        self._build(parse_result)

    # ─────────────────────────────────────────────
    # Build
    # ─────────────────────────────────────────────
    def _build(self, result: ParseResult) -> None:
        for resource in result.resources:
            self.G.add_node(
                resource.symbol_name,
                **{
                    "symbol_name": resource.symbol_name,
                    "name": resource.name,
                    "resource_type": resource.resource_type,
                    "api_version": resource.api_version,
                    "category": resource.category,
                    "icon": resource.icon,
                    "label": resource.label,
                    "raw_properties": resource.raw_properties,
                    "kind": resource.kind,
                    "is_existing": resource.is_existing,
                },
            )

        for edge in result.edges:
            self.G.add_edge(
                edge.from_symbol,
                edge.to_symbol,
                relation=edge.relation,
            )

    # ─────────────────────────────────────────────
    # Query API (used by the agent through tools).
    # ─────────────────────────────────────────────
    def get_all_resources(self) -> list[dict]:
        """Return all nodes as a list of dictionaries."""
        return [self.G.nodes[n] for n in self.G.nodes]

    def get_resource(self, symbol_name: str) -> Optional[dict]:
        """Return a node by symbol_name."""
        if symbol_name in self.G.nodes:
            return dict(self.G.nodes[symbol_name])
        return None

    def get_resources_by_category(self, category: str) -> list[dict]:
        """Filter resources by category."""
        return [
            dict(self.G.nodes[n])
            for n in self.G.nodes
            if self.G.nodes[n].get("category") == category
        ]

    def get_resources_by_label(self, label: str) -> list[dict]:
        """Filter resources by label (for example, 'Function / App')."""
        return [
            dict(self.G.nodes[n])
            for n in self.G.nodes
            if self.G.nodes[n].get("label") == label
        ]

    def get_dependencies(self, symbol_name: str) -> list[dict]:
        """Resources that symbol_name depends on (outgoing edges)."""
        return [
            dict(self.G.nodes[succ])
            for succ in self.G.successors(symbol_name)
        ]

    def get_dependents(self, symbol_name: str) -> list[dict]:
        """Resources that depend on symbol_name (incoming edges)."""
        return [
            dict(self.G.nodes[pred])
            for pred in self.G.predecessors(symbol_name)
        ]

    def get_connected_resources(self, symbol_name: str) -> list[dict]:
        """All connected resources (both directions)."""
        neighbors = set(self.G.successors(symbol_name)) | set(self.G.predecessors(symbol_name))
        return [dict(self.G.nodes[n]) for n in neighbors]

    def get_resources_without_private_endpoint(self) -> list[dict]:
        """
        Sensitive resources (ai, storage, security) without
        a connected Private Endpoint.
        """
        pe_nodes = {
            n for n in self.G.nodes
            if self.G.nodes[n].get("label") == "Private Endpoint"
        }
        sensitive_categories = {"ai", "storage", "security", "database"}
        result = []
        for n in self.G.nodes:
            node = self.G.nodes[n]
            if node.get("category") not in sensitive_categories:
                continue
            # Check whether a PE depends on this resource.
            has_pe = any(
                self.G.nodes[pred].get("label") == "Private Endpoint"
                for pred in self.G.predecessors(n)
            )
            if not has_pe:
                result.append(dict(node))
        return result

    def simulate_failure(self, symbol_name: str) -> dict:
        """
        Simulate removing a resource and return impacted resources
        (those that depend on it directly or indirectly).
        """
        if symbol_name not in self.G.nodes:
            return {"error": f"Resource '{symbol_name}' not found"}

        # Direct dependents (predecessors of incoming edges to symbol_name,
        # meaning resources that use it).
        direct_dependents = list(self.G.predecessors(symbol_name))

        # Impatto a cascata: tutti gli antenati nel grafo inverso
        try:
            ancestors = nx.ancestors(self.G.reverse(), symbol_name)
        except Exception:
            ancestors = set()

        impacted = set(direct_dependents) | ancestors
        impacted.discard(symbol_name)

        return {
            "failed_resource": dict(self.G.nodes[symbol_name]),
            "direct_dependents": [
                dict(self.G.nodes[n]) for n in direct_dependents
            ],
            "all_impacted": [
                dict(self.G.nodes[n]) for n in impacted
            ],
            "impact_count": len(impacted),
        }

    def find_isolated_resources(self) -> list[dict]:
        """Resources without any connections."""
        return [
            dict(self.G.nodes[n])
            for n in self.G.nodes
            if self.G.degree(n) == 0
        ]

    def summary(self) -> dict:
        """Numeric graph summary."""
        categories: dict[str, int] = {}
        for n in self.G.nodes:
            cat = self.G.nodes[n].get("category", "unknown")
            categories[cat] = categories.get(cat, 0) + 1

        return {
            "total_resources": self.G.number_of_nodes(),
            "total_edges": self.G.number_of_edges(),
            "categories": categories,
            "has_vnet": any(
                self.G.nodes[n].get("category") == "network"
                and self.G.nodes[n].get("label") == "VNet"
                for n in self.G.nodes
            ),
            "params": [
                {"name": p.name, "type": p.param_type, "default": p.default_value}
                for p in self._parse_result.params
            ],
        }

    def to_dict(self) -> dict:
        """Complete serialization for the agent or export."""
        return {
            "nodes": [dict(self.G.nodes[n]) for n in self.G.nodes],
            "edges": [
                {
                    "from": u,
                    "to": v,
                    "relation": self.G.edges[u, v].get("relation", "depends_on"),
                }
                for u, v in self.G.edges
            ],
        }