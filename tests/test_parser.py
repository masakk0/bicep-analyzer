"""
tests/test_parser.py
─────────────────────
Unit tests for BicepParser.
"""

import pytest
from src.parser.bicep_parser import BicepParser, BicepResource, BicepEdge

SAMPLE_BICEP = """
param location string = 'westeurope'
param appName string = 'myapp'

resource vnet 'Microsoft.Network/virtualNetworks@2023-04-01' = {
  name: '${appName}-vnet'
  location: location
  properties: {
    addressSpace: { addressPrefixes: ['10.0.0.0/16'] }
  }
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: '${appName}storage'
  location: location
  sku: { name: 'Standard_LRS' }
  properties: { publicNetworkAccess: 'Disabled' }
}

resource storagePrivateEndpoint 'Microsoft.Network/privateEndpoints@2023-04-01' = {
  name: '${appName}-storage-pe'
  location: location
  properties: {
    subnet: { id: '${vnet.id}/subnets/pe-subnet' }
    privateLinkServiceConnections: [{
      name: 'storage-connection'
      properties: {
        privateLinkServiceId: storageAccount.id
        groupIds: ['blob']
      }
    }]
  }
}

resource functionApp 'Microsoft.Web/sites@2022-09-01' = {
  name: '${appName}-func'
  location: location
  kind: 'functionapp'
  properties: {
    virtualNetworkSubnetId: '${vnet.id}/subnets/app-subnet'
    siteConfig: {
      appSettings: [
        { name: 'AI_ENDPOINT', value: 'https://myapp-ai.cognitiveservices.azure.com' }
      ]
    }
  }
}
"""


class TestBicepParser:

    def setup_method(self):
        self.parser = BicepParser()

    def test_extracts_correct_resource_count(self):
        result = self.parser.parse(SAMPLE_BICEP)
        assert len(result.resources) == 4

    def test_extracts_params(self):
        result = self.parser.parse(SAMPLE_BICEP)
        param_names = [p.name for p in result.params]
        assert "location" in param_names
        assert "appName" in param_names

    def test_param_default_value(self):
        result = self.parser.parse(SAMPLE_BICEP)
        location_param = next(p for p in result.params if p.name == "location")
        assert location_param.default_value == "'westeurope'"

    def test_resource_categories(self):
        result = self.parser.parse(SAMPLE_BICEP)
        cats = {r.symbol_name: r.category for r in result.resources}
        assert cats["vnet"] == "network"
        assert cats["storageAccount"] == "storage"
        assert cats["storagePrivateEndpoint"] == "network"
        assert cats["functionApp"] == "compute"

    def test_resource_labels(self):
        result = self.parser.parse(SAMPLE_BICEP)
        labels = {r.symbol_name: r.label for r in result.resources}
        assert labels["vnet"] == "VNet"
        assert labels["storagePrivateEndpoint"] == "Private Endpoint"
        assert labels["functionApp"] == "Function / App"

    def test_resource_api_version(self):
        result = self.parser.parse(SAMPLE_BICEP)
        vnet = next(r for r in result.resources if r.symbol_name == "vnet")
        assert vnet.api_version == "2023-04-01"

    def test_edges_detected(self):
        result = self.parser.parse(SAMPLE_BICEP)
        edge_pairs = {(e.from_symbol, e.to_symbol) for e in result.edges}
        # storagePrivateEndpoint depends on vnet and storageAccount
        assert ("storagePrivateEndpoint", "vnet") in edge_pairs
        assert ("storagePrivateEndpoint", "storageAccount") in edge_pairs
        # functionApp depends on vnet
        assert ("functionApp", "vnet") in edge_pairs

    def test_empty_template(self):
        result = self.parser.parse("// empty bicep file\nparam x string")
        assert len(result.resources) == 0
        assert len(result.edges) == 0
        assert len(result.params) == 1

    def test_unknown_resource_type(self):
        bicep = """
resource mystery 'Microsoft.Unknown/things@2023-01-01' = {
  name: 'test-thing'
  location: 'westeurope'
}
"""
        result = self.parser.parse(bicep)
        assert len(result.resources) == 1
        assert result.resources[0].category == "unknown"
        assert result.resources[0].icon == "📦"
