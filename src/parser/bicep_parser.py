"""
src/parser/bicep_parser.py
──────────────────────────
Lightweight parser for Bicep templates.
Extracts resources, modules, parameters, and dependencies without external dependencies.
v2: gestisce sia `resource` che `module` (incluso Azure Verified Modules,
for example, `br/public:avm/res/...`), and distinguishes `existing` resources
deployed elsewhere (out of scope) from those actually created by this template.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ─────────────────────────────────────────────────────────────
# Tipo → metadati interni
# ─────────────────────────────────────────────────────────────
RESOURCE_TYPE_MAP: dict[str, dict] = {
    "microsoft.network/virtualnetworks": {
        "category": "network", "icon": "🌐", "label": "VNet"
    },
    "microsoft.network/virtualnetworks/subnets": {
        "category": "network", "icon": "🧩", "label": "Subnet"
    },
    "microsoft.network/privateendpoints": {
        "category": "network", "icon": "🔒", "label": "Private Endpoint"
    },
    "microsoft.network/privatednszones": {
        "category": "network", "icon": "🔗", "label": "Private DNS Zone"
    },
    "microsoft.network/networksecuritygroups": {
        "category": "network", "icon": "🛡️", "label": "NSG"
    },
    "microsoft.network/applicationgateways": {
        "category": "network", "icon": "🔀", "label": "App Gateway"
    },
    "microsoft.web/sites": {
        "category": "compute", "icon": "⚡", "label": "Function / App"
    },
    "microsoft.web/serverfarms": {
        "category": "compute", "icon": "🖥️", "label": "App Service Plan"
    },
    "microsoft.storage/storageaccounts": {
        "category": "storage", "icon": "💾", "label": "Storage Account"
    },
    "microsoft.cognitiveservices/accounts": {
        "category": "ai", "icon": "🤖", "label": "AI Service"
    },
    "microsoft.machinelearningservices/workspaces": {
        "category": "ai", "icon": "🧠", "label": "ML Workspace"
    },
    "microsoft.keyvault/vaults": {
        "category": "security", "icon": "🔑", "label": "Key Vault"
    },
    "microsoft.sql/servers": {
        "category": "database", "icon": "🗄️", "label": "SQL Server"
    },
    "microsoft.documentdb/databaseaccounts": {
        "category": "database", "icon": "🗄️", "label": "CosmosDB"
    },
    "microsoft.containerservice/managedclusters": {
        "category": "compute", "icon": "☸️", "label": "AKS"
    },
    "microsoft.servicebus/namespaces": {
        "category": "messaging", "icon": "📨", "label": "Service Bus"
    },
    "microsoft.eventhub/namespaces": {
        "category": "messaging", "icon": "📡", "label": "Event Hub"
    },
    "microsoft.operationalinsights/workspaces": {
        "category": "monitoring", "icon": "📊", "label": "Log Analytics"
    },
    "microsoft.insights/components": {
        "category": "monitoring", "icon": "📈", "label": "App Insights"
    },
    "microsoft.resources/resourcegroups": {
        "category": "unknown", "icon": "🗂️", "label": "Resource Group"
    },
}

# Infer category/icon from the AVM module path when the Azure type is
# not directly available (for example, br/public:avm/res/web/site).
AVM_PATH_MAP: dict[str, dict] = {
    "web/site":              {"category": "compute", "icon": "⚡", "label": "App Service"},
    "web/serverfarm":        {"category": "compute", "icon": "🖥️", "label": "App Service Plan"},
    "storage/storage-account": {"category": "storage", "icon": "💾", "label": "Storage Account"},
    "insights/component":    {"category": "monitoring", "icon": "📈", "label": "App Insights"},
    "network/virtual-network": {"category": "network", "icon": "🌐", "label": "VNet"},
    "network/private-endpoint": {"category": "network", "icon": "🔒", "label": "Private Endpoint"},
    "keyvault/vault":         {"category": "security", "icon": "🔑", "label": "Key Vault"},
    "cognitiveservices/account": {"category": "ai", "icon": "🤖", "label": "AI Service"},
    "sql/server":             {"category": "database", "icon": "🗄️", "label": "SQL Server"},
    "documentdb/database-account": {"category": "database", "icon": "🗄️", "label": "CosmosDB"},
    "operationalinsights/workspace": {"category": "monitoring", "icon": "📊", "label": "Log Analytics"},
}


# ─────────────────────────────────────────────────────────────
# Data models
# ─────────────────────────────────────────────────────────────
@dataclass
class BicepResource:
    symbol_name: str                   # Symbolic name in the template
    name: str                          # Value of the 'name' property
    resource_type: str                 # For example, Microsoft.Network/virtualNetworks
    api_version: str                   # For example, 2023-04-01
    category: str                      # network | compute | storage | ai | ...
    icon: str
    label: str
    raw_properties: str                # Raw block for LLM analysis
    kind: str = "resource"             # resource | module
    is_existing: bool = False          # True for `existing` resources (out of scope)
    properties: dict = field(default_factory=dict)


@dataclass
class BicepEdge:
    from_symbol: str
    to_symbol: str
    relation: str = "depends_on"       # depends_on | uses | contains


@dataclass
class BicepParam:
    name: str
    param_type: str
    default_value: Optional[str] = None


@dataclass
class ParseResult:
    resources: list[BicepResource]
    edges: list[BicepEdge]
    params: list[BicepParam]
    raw_content: str


# ─────────────────────────────────────────────────────────────
# Parser
# ─────────────────────────────────────────────────────────────
class BicepParser:
    """
    Regex-based parser for Bicep templates.
    This is not a complete AST; it covers 95% of real-world v2 cases.

    Handles two top-level constructs:
      resource <symbolName> '<type>@<apiVersion>' [existing] = { ... }
      module   <symbolName> '<path>' = { name: ..., params: { ... } }
    """

    # resource <symbolName> '<type>@<apiVersion>' [existing] = {
    _RESOURCE_RE = re.compile(
        r"resource\s+(\w+)\s+'([^']+)'\s*(existing\s+)?=\s*\{",
        re.MULTILINE,
    )
    # module <symbolName> '<path>' = {
    _MODULE_RE = re.compile(
        r"module\s+(\w+)\s+'([^']+)'\s*=\s*\{",
        re.MULTILINE,
    )
    # param <name> <type> = <default>
    _PARAM_RE = re.compile(
        r"^param\s+(\w+)\s+(\w+)(?:\s*=\s*(.+))?",
        re.MULTILINE,
    )

    def parse(self, content: str) -> ParseResult:
        resources = self._extract_resources(content)
        modules = self._extract_modules(content)
        all_resources = resources + modules
        var_map = self._extract_var_bodies(content)
        edges = self._extract_edges(all_resources, var_map)
        params = self._extract_params(content)
        return ParseResult(
            resources=all_resources,
            edges=edges,
            params=params,
            raw_content=content,
        )

    # ── Variables (for resolving indirect references) ──────────
    _VAR_RE = re.compile(r"^var\s+(\w+)\s*=\s*", re.MULTILINE)

    def _extract_var_bodies(self, content: str) -> dict[str, str]:
        """
        Extract the text body of each `var name = ...` statement, handling
        balanced { } and [ ]. Used to follow indirect references: a resource
        can use `var X`, and X can contain `anotherResource.outputs.foo`.
        """
        var_bodies: dict[str, str] = {}
        for m in self._VAR_RE.finditer(content):
            name = m.group(1)
            start = m.end()
            var_bodies[name] = self._extract_statement(content, start)
        return var_bodies

    def _extract_statement(self, content: str, start: int) -> str:
        """
        Extract the value of an assignment from `start`, balancing { }, [ ],
        and ( ) until depth returns to 0 and a newline or end of file is reached.
        Handles simple vars, objects, arrays, and array comprehensions.
        """
        depth = 0
        out = []
        i = start
        n = len(content)
        started_bracket = False
        while i < n:
            ch = content[i]
            if ch in "{[(":
                depth += 1
                started_bracket = True
            elif ch in "}])":
                depth -= 1
            out.append(ch)
            i += 1
            if depth <= 0:
                if started_bracket:
                    break
                if ch == "\n":
                    break
        return "".join(out)

    # ── Resources (`resource` keyword) ──────────────────────────
    def _extract_resources(self, content: str) -> list[BicepResource]:
        resources = []
        for match in self._RESOURCE_RE.finditer(content):
            symbol_name = match.group(1)
            full_type = match.group(2)
            is_existing = bool(match.group(3))
            resource_type, _, api_version = full_type.partition("@")

            block_start = content.index("{", match.start())
            raw_props = self._extract_block(content, block_start)

            meta = RESOURCE_TYPE_MAP.get(resource_type.lower(), {
                "category": "unknown",
                "icon": "📦",
                "label": resource_type.split("/")[-1],
            })

            name = self._extract_name(raw_props) or symbol_name

            resources.append(BicepResource(
                symbol_name=symbol_name,
                name=name,
                resource_type=resource_type,
                api_version=api_version,
                category=meta["category"],
                icon=meta["icon"],
                label=meta["label"],
                raw_properties=raw_props,
                kind="resource",
                is_existing=is_existing,
            ))
        return resources

    # ── Modules (`module` keyword, incl. Azure Verified Modules) ──
    def _extract_modules(self, content: str) -> list[BicepResource]:
        modules = []
        for match in self._MODULE_RE.finditer(content):
            symbol_name = match.group(1)
            module_path = match.group(2)

            block_start = content.index("{", match.start())
            raw_props = self._extract_block(content, block_start)

            meta = self._infer_module_meta(module_path, raw_props)
            name = self._extract_name(raw_props) or symbol_name

            modules.append(BicepResource(
                symbol_name=symbol_name,
                name=name,
                resource_type=module_path,
                api_version="",
                category=meta["category"],
                icon=meta["icon"],
                label=meta["label"],
                raw_properties=raw_props,
                kind="module",
                is_existing=False,
            ))
        return modules

    def _infer_module_meta(self, module_path: str, raw_props: str) -> dict:
        """
        Infer category/icon/label for a Bicep module.
        Works for local modules (./foo.bicep) and Azure Verified Modules
        (br/public:avm/res/<service>/<resource>:version).
        """
        path_lower = module_path.lower()

        # Azure Verified Modules: br/public:avm/res/<service>/<resource>:<ver>
        avm_match = re.search(r"avm/res/([\w-]+)/([\w-]+)", path_lower)
        if avm_match:
            key = f"{avm_match.group(1)}/{avm_match.group(2)}"
            if key in AVM_PATH_MAP:
                return AVM_PATH_MAP[key]
            # Fallback: use the AVM resource name as a readable label.
            return {
                "category": "unknown",
                "icon": "📦",
                "label": avm_match.group(2).replace("-", " ").title(),
            }

        # Local module: infer from the file name.
        base = path_lower.split("/")[-1].replace(".bicep", "")
        for key, meta in AVM_PATH_MAP.items():
            if key.split("/")[-1] in base:
                return meta

        return {
            "category": "unknown",
            "icon": "🧱",
            "label": "Module",
        }

    def _extract_block(self, content: str, start: int) -> str:
        """Extract a balanced { ... } block."""
        depth = 0
        out = []
        for ch in content[start:]:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            out.append(ch)
            if depth == 0:
                break
        return "".join(out)

    def _extract_name(self, block: str) -> Optional[str]:
        """Try to extract the value of the 'name' property."""
        patterns = [
            r"name:\s*'([^']+)'",
            r'name:\s*"([^"]+)"',
            r"name:\s*`([^`]+)`",
        ]
        for pat in patterns:
            m = re.search(pat, block)
            if m:
                return m.group(1)
        return None

    # ── Edges ──────────────────────────────────────────────────
    def _extract_edges(
        self, resources: list[BicepResource], var_map: Optional[dict[str, str]] = None
    ) -> list[BicepEdge]:
        """
        Find references between resources/modules by searching each raw
        resource block for symbols used as:
        - ${symbolName.id} / ${symbolName.name} / ${symbolName.properties.x}
        - symbolName.id / symbolName.name
        - symbolName.outputs.xxx          (module output)

        Also follows one level of indirection through variables: if a block
        uses `var X` and X references another resource, the edge is detected
        (for example, an `appSettings` var used in a module containing
        `anotherModule.outputs.foo`).
        """
        var_map = var_map or {}
        edges = []
        seen = set()
        for resource in resources:
            # Expand the block with the bodies of named variables to capture
            # indirect references.
            expanded = resource.raw_properties
            referenced_vars = set(re.findall(r"\b(\w+)\b", resource.raw_properties))
            for vname in referenced_vars:
                if vname in var_map:
                    expanded += "\n" + var_map[vname]

            for other in resources:
                if resource.symbol_name == other.symbol_name:
                    continue
                patterns = [
                    rf"\$\{{{other.symbol_name}\.(id|name|properties\.\w+|outputs\.\w+)\}}",
                    rf"\b{other.symbol_name}\.(id|name|outputs\.\w+)\b",
                ]
                if any(re.search(p, expanded) for p in patterns):
                    key = (resource.symbol_name, other.symbol_name)
                    if key not in seen:
                        seen.add(key)
                        edges.append(BicepEdge(
                            from_symbol=resource.symbol_name,
                            to_symbol=other.symbol_name,
                        ))
        return edges

    # ── Params ─────────────────────────────────────────────────
    def _extract_params(self, content: str) -> list[BicepParam]:
        params = []
        for m in self._PARAM_RE.finditer(content):
            params.append(BicepParam(
                name=m.group(1),
                param_type=m.group(2),
                default_value=m.group(3).strip() if m.group(3) else None,
            ))
        return params