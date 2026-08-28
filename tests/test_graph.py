"""
tests/test_graph.py
────────────────────
Unit tests for InfraGraph.
"""

import pytest
from src.parser.bicep_parser import BicepParser
from src.graph.builder import InfraGraph

SAMPLE_BICEP = """
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

resource appServicePlan 'Microsoft.Web/serverfarms@2022-09-01' = {
  name: 'test-plan'
  location: location
  sku: { name: 'P1v3' }
}

resource functionApp 'Microsoft.Web/sites@2022-09-01' = {
  name: 'test-func'
  location: location
  properties: {
    serverFarmId: appServicePlan.id
    virtualNetworkSubnetId: '${vnet.id}/subnets/app-subnet'
  }
}

resource aiService 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: 'test-ai'
  location: location
  kind: 'OpenAI'
  properties: { publicNetworkAccess: 'Disabled' }
}
"""


@pytest.fixture
def graph():
    parser = BicepParser()
    result = parser.parse(SAMPLE_BICEP)
    return InfraGraph(result)


class TestInfraGraph:

    def test_node_count(self, graph):
        assert graph.G.number_of_nodes() == 6

    def test_edge_count(self, graph):
        # storagePrivateEndpoint → vnet, storageAccount
        # functionApp → appServicePlan, vnet
        assert graph.G.number_of_edges() >= 4

    def test_get_all_resources(self, graph):
        resources = graph.get_all_resources()
        assert len(resources) == 6

    def test_get_resource_by_symbol(self, graph):
        node = graph.get_resource("vnet")
        assert node is not None
        assert node["category"] == "network"
        assert node["label"] == "VNet"

    def test_get_resource_nonexistent(self, graph):
        assert graph.get_resource("doesNotExist") is None

    def test_get_resources_by_category(self, graph):
        ai_resources = graph.get_resources_by_category("ai")
        assert len(ai_resources) == 1
        assert ai_resources[0]["symbol_name"] == "aiService"

    def test_get_dependencies(self, graph):
        # functionApp depends on appServicePlan and vnet
        deps = graph.get_dependencies("functionApp")
        dep_symbols = {d["symbol_name"] for d in deps}
        assert "appServicePlan" in dep_symbols
        assert "vnet" in dep_symbols

    def test_get_dependents(self, graph):
        # storagePrivateEndpoint depends on vnet; vnet has storagePrivateEndpoint as a dependent
        dependents = graph.get_dependents("vnet")
        dep_symbols = {d["symbol_name"] for d in dependents}
        assert "storagePrivateEndpoint" in dep_symbols

    def test_simulate_failure_vnet(self, graph):
        result = graph.simulate_failure("vnet")
        assert "failed_resource" in result
        assert result["impact_count"] > 0
        impacted_symbols = {r["symbol_name"] for r in result["all_impacted"]}
        # functionApp uses vnet and should be impacted
        assert "functionApp" in impacted_symbols

    def test_simulate_failure_nonexistent(self, graph):
        result = graph.simulate_failure("doesNotExist")
        assert "error" in result

    def test_resources_without_private_endpoint(self, graph):
        # aiService has no PE and should appear
        exposed = graph.get_resources_without_private_endpoint()
        exposed_symbols = {r["symbol_name"] for r in exposed}
        assert "aiService" in exposed_symbols
        # storageAccount has a PE and should not appear
        assert "storageAccount" not in exposed_symbols

    def test_summary(self, graph):
        s = graph.summary()
        assert s["total_resources"] == 6
        assert s["has_vnet"] is True
        assert "network" in s["categories"]
        assert "compute" in s["categories"]

    def test_isolated_resources(self, graph):
        isolated = graph.find_isolated_resources()
        # Every resource in this template has at least one connection
        isolated_symbols = {r["symbol_name"] for r in isolated}
        assert "vnet" not in isolated_symbols

    def test_to_dict(self, graph):
        d = graph.to_dict()
        assert "nodes" in d
        assert "edges" in d
        assert len(d["nodes"]) == 6
