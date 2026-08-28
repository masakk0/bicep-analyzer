"""
tests/test_risk_engine.py
──────────────────────────
Unit tests for RiskEngine.
"""

import pytest
from src.parser.bicep_parser import BicepParser
from src.graph.builder import InfraGraph
from src.analyzer.risk_engine import RiskEngine

# Template with intentional risks:
# - aiService without a Private Endpoint
# - keyVault without a Private Endpoint
# - functionAppNoVnet not integrated with a VNet
RISKY_BICEP = """
param location string = 'westeurope'

resource vnet 'Microsoft.Network/virtualNetworks@2023-04-01' = {
  name: 'test-vnet'
  location: location
  properties: { addressSpace: { addressPrefixes: ['10.0.0.0/16'] } }
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: 'teststorage'
  location: location
  properties: { publicNetworkAccess: 'Disabled' }
}

resource storagePrivateEndpoint 'Microsoft.Network/privateEndpoints@2023-04-01' = {
  name: 'test-storage-pe'
  location: location
  properties: {
    subnet: { id: '${vnet.id}/subnets/pe-subnet' }
    privateLinkServiceConnections: [{
      properties: { privateLinkServiceId: storageAccount.id }
    }]
  }
}

resource aiService 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: 'test-ai'
  location: location
  kind: 'OpenAI'
  properties: { publicNetworkAccess: 'Disabled' }
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'test-kv'
  location: location
  properties: { publicNetworkAccess: 'Enabled' }
}

resource functionAppNoVnet 'Microsoft.Web/sites@2022-09-01' = {
  name: 'test-func-no-vnet'
  location: location
  kind: 'functionapp'
  properties: {
    siteConfig: {
      appSettings: [
        { name: 'AI_ENDPOINT', value: 'https://test-ai.cognitiveservices.azure.com' }
      ]
    }
  }
}
"""

# Clean template (no risks expected)
CLEAN_BICEP = """
param location string = 'westeurope'

resource vnet 'Microsoft.Network/virtualNetworks@2023-04-01' = {
  name: 'clean-vnet'
  location: location
  properties: { addressSpace: { addressPrefixes: ['10.0.0.0/16'] } }
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: 'cleanstorage'
  location: location
  properties: { publicNetworkAccess: 'Disabled' }
}

resource storagePrivateEndpoint 'Microsoft.Network/privateEndpoints@2023-04-01' = {
  name: 'clean-storage-pe'
  location: location
  properties: {
    subnet: { id: '${vnet.id}/subnets/pe-subnet' }
    privateLinkServiceConnections: [{
      properties: { privateLinkServiceId: storageAccount.id }
    }]
  }
}
"""


def make_graph(bicep: str) -> InfraGraph:
    parser = BicepParser()
    result = parser.parse(bicep)
    return InfraGraph(result)


class TestRiskEngine:

    def setup_method(self):
        self.engine = RiskEngine()

    def test_detects_ai_without_pe(self):
        graph = make_graph(RISKY_BICEP)
        findings = self.engine.evaluate(graph)
        rule_ids = [f.rule_id for f in findings]
        assert "ai_no_private_endpoint" in rule_ids

    def test_detects_keyvault_public_access(self):
        graph = make_graph(RISKY_BICEP)
        findings = self.engine.evaluate(graph)
        # publicNetworkAccess: 'Enabled' → high risk
        high_findings = [f for f in findings if f.severity == "high"]
        assert len(high_findings) > 0

    def test_detects_function_no_vnet(self):
        graph = make_graph(RISKY_BICEP)
        findings = self.engine.evaluate(graph)
        rule_ids = [f.rule_id for f in findings]
        assert "function_no_vnet" in rule_ids

    def test_detects_function_calls_ai(self):
        graph = make_graph(RISKY_BICEP)
        findings = self.engine.evaluate(graph)
        rule_ids = [f.rule_id for f in findings]
        assert "function_calls_ai_no_retry" in rule_ids

    def test_storage_with_pe_not_flagged(self):
        graph = make_graph(RISKY_BICEP)
        findings = self.engine.evaluate(graph)
        # storageAccount has a PE and should not be reported for storage_no_private_endpoint
        storage_pe_findings = [
            f for f in findings
            if f.rule_id == "storage_no_private_endpoint"
            and f.resource_symbol == "storageAccount"
        ]
        assert len(storage_pe_findings) == 0

    def test_sorted_by_severity(self):
        graph = make_graph(RISKY_BICEP)
        findings = self.engine.evaluate(graph)
        order = {"high": 0, "medium": 1, "low": 2, "info": 3}
        severities = [order[f.severity] for f in findings]
        assert severities == sorted(severities)

    def test_findings_have_fix_template(self):
        graph = make_graph(RISKY_BICEP)
        findings = self.engine.evaluate(graph)
        high = [f for f in findings if f.severity == "high" and f.rule_id == "ai_no_private_endpoint"]
        assert len(high) > 0
        assert high[0].fix_template is not None

    def test_clean_template_fewer_risks(self):
        graph = make_graph(CLEAN_BICEP)
        findings = self.engine.evaluate(graph)
        high_findings = [f for f in findings if f.severity == "high"]
        # Template pulito non deve avere high risks
        assert len(high_findings) == 0
