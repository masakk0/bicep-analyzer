from src.agent.agent import BicepTwinAgent
from src.analyzer.risk_engine import RiskEngine
from src.graph.builder import InfraGraph
from src.parser.bicep_parser import BicepParser


def test_completion_uses_generic_llm_environment(monkeypatch):
    graph = InfraGraph(BicepParser().parse("resource storage 'Microsoft.Storage/storageAccounts@2023-01-01' = { name: 'test' location: 'westeurope' }"))
    monkeypatch.setenv("LLM_MODEL", "ollama/llama3.1")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_API_BASE", "http://localhost:11434")

    agent = BicepTwinAgent(graph, RiskEngine())
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr("src.agent.agent.completion", fake_completion)
    agent._complete([{"role": "user", "content": "Hello"}])

    assert captured["model"] == "ollama/llama3.1"
    assert captured["api_key"] == "test-key"
    assert captured["api_base"] == "http://localhost:11434"
    assert "tools" not in captured