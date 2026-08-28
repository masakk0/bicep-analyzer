"""
src/agent/tools.py
───────────────────
Tool functions callable by the LLM agent.
Each tool has an OpenAI-compatible JSON schema and a Python function.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

from src.graph.builder import InfraGraph
from src.analyzer.risk_engine import RiskEngine, RiskFinding


# ─────────────────────────────────────────────────────────────
# Schema dei tool (OpenAI function calling format)
# ─────────────────────────────────────────────────────────────
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_infrastructure_summary",
            "description": (
                "Returns an infrastructure summary: resource count by category, "
                "dependency count, and defined parameters."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_all_resources",
            "description": "Returns all resources in the Bicep template.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_resource_detail",
            "description": "Returns details for a resource, including its connections.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol_name": {
                        "type": "string",
                        "description": "The resource's symbolic name in the template (for example, 'functionApp' or 'vnet').",
                    }
                },
                "required": ["symbol_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_resources_by_category",
            "description": "Returns resources filtered by category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["network", "compute", "storage", "ai", "security", "database", "messaging", "unknown"],
                        "description": "The category to filter by.",
                    }
                },
                "required": ["category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_risks",
            "description": (
                "Evaluates and returns all architectural risks detected in the template. "
                "Includes severity, message, and suggested fix."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "simulate_failure",
            "description": (
                "Simulates a resource removal/failure and returns directly and transitively "
                "impacted resources."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol_name": {
                        "type": "string",
                        "description": "The symbolic name of the resource to simulate failing.",
                    }
                },
                "required": ["symbol_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_resources_without_private_endpoint",
            "description": (
                "Returns sensitive resources (AI, Storage, Key Vault, Database) "
                "without a connected Private Endpoint."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_isolated_resources",
            "description": "Returns resources with no connections to other resources.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_bicep_document",
            "description": "Returns the path, revision, and full content of the active Bicep document.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "replace_bicep_text",
            "description": (
                "Edits the active Bicep document by replacing text that occurs exactly once. "
                "The graph and risks are updated immediately."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "old_text": {"type": "string", "description": "Exact text to replace."},
                    "new_text": {"type": "string", "description": "New Bicep text."},
                },
                "required": ["old_text", "new_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_bicep_file",
            "description": "Saves the active Bicep document to disk in the workspace root.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative .bicep path. Omit to use the active file.",
                    }
                },
                "required": [],
            },
        },
    },
]


# ─────────────────────────────────────────────────────────────
# Tool executor
# ─────────────────────────────────────────────────────────────
class ToolExecutor:
    """
    Executes agent tool calls and returns results as a JSON string.
    Maintains graph and risk-engine state injected from outside.
    """

    def __init__(
        self,
        graph: InfraGraph,
        risk_engine: RiskEngine,
        document_handler: Optional[Callable[[], dict]] = None,
        edit_handler: Optional[Callable[[str, str], dict]] = None,
        save_handler: Optional[Callable[[Optional[str]], dict]] = None,
    ):
        self.graph = graph
        self.risk_engine = risk_engine
        self.document_handler = document_handler
        self.edit_handler = edit_handler
        self.save_handler = save_handler
        self._dispatch = {
            "get_infrastructure_summary":           self._summary,
            "get_all_resources":                    self._all_resources,
            "get_resource_detail":                  self._resource_detail,
            "get_resources_by_category":            self._by_category,
            "get_risks":                            self._risks,
            "simulate_failure":                     self._simulate_failure,
            "get_resources_without_private_endpoint": self._without_pe,
            "find_isolated_resources":              self._isolated,
            "get_bicep_document":                   self._get_bicep_document,
            "replace_bicep_text":                   self._replace_bicep_text,
            "save_bicep_file":                      self._save_bicep_file,
        }

    def execute(self, tool_name: str, arguments: dict) -> str:
        handler = self._dispatch.get(tool_name)
        if not handler:
            return json.dumps({"error": f"Tool '{tool_name}' not found"})
        try:
            result = handler(**arguments)
            return json.dumps(result, ensure_ascii=False, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)})

    # ── Handlers ───────────────────────────────────────────────
    def _summary(self) -> dict:
        return self.graph.summary()

    def _all_resources(self) -> list:
        return [
            {k: v for k, v in r.items() if k != "raw_properties"}
            for r in self.graph.get_all_resources()
        ]

    def _resource_detail(self, symbol_name: str) -> dict:
        node = self.graph.get_resource(symbol_name)
        if not node:
            return {"error": f"Resource '{symbol_name}' not found"}
        return {
            **{k: v for k, v in node.items() if k != "raw_properties"},
            "dependencies": [
                {k: v for k, v in d.items() if k != "raw_properties"}
                for d in self.graph.get_dependencies(symbol_name)
            ],
            "dependents": [
                {k: v for k, v in d.items() if k != "raw_properties"}
                for d in self.graph.get_dependents(symbol_name)
            ],
        }

    def _by_category(self, category: str) -> list:
        return [
            {k: v for k, v in r.items() if k != "raw_properties"}
            for r in self.graph.get_resources_by_category(category)
        ]

    def _risks(self) -> list:
        findings = self.risk_engine.evaluate(self.graph)
        return [
            {
                "rule_id": f.rule_id,
                "rule_name": f.rule_name,
                "severity": f.severity,
                "category": f.category,
                "message": f.message,
                "resource": f.resource_name,
                "fix_available": f.fix_template is not None,
                "fix_template": f.fix_template,
            }
            for f in findings
        ]

    def _simulate_failure(self, symbol_name: str) -> dict:
        result = self.graph.simulate_failure(symbol_name)
        # Omit raw_properties to keep the LLM context compact.
        def clean(lst):
            return [{k: v for k, v in r.items() if k != "raw_properties"} for r in lst]

        if "error" in result:
            return result
        return {
            "failed_resource": {k: v for k, v in result["failed_resource"].items() if k != "raw_properties"},
            "direct_dependents": clean(result["direct_dependents"]),
            "all_impacted": clean(result["all_impacted"]),
            "impact_count": result["impact_count"],
        }

    def _without_pe(self) -> list:
        return [
            {k: v for k, v in r.items() if k != "raw_properties"}
            for r in self.graph.get_resources_without_private_endpoint()
        ]

    def _isolated(self) -> list:
        return [
            {k: v for k, v in r.items() if k != "raw_properties"}
            for r in self.graph.find_isolated_resources()
        ]

    def _replace_bicep_text(self, old_text: str, new_text: str) -> dict:
        if not self.edit_handler:
            return {"error": "Bicep editing is unavailable"}
        return self.edit_handler(old_text, new_text)

    def _get_bicep_document(self) -> dict:
        if not self.document_handler:
            return {"error": "Bicep document is unavailable"}
        return self.document_handler()

    def _save_bicep_file(self, path: Optional[str] = None) -> dict:
        if not self.save_handler:
            return {"error": "Bicep saving is unavailable"}
        return self.save_handler(path)
