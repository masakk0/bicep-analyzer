from pathlib import Path

from src.api.server import app


def test_live_analysis_and_graph_export():
    client = app.test_client()
    content = Path("examples/sample.bicep").read_text(encoding="utf-8")

    response = client.post("/api/analyze", json={"content": content, "detach": True})
    assert response.status_code == 200
    analysis = response.get_json()
    assert analysis["graph"]["nodes"]
    assert analysis["document"]["path"] is None

    updated = client.post(
        "/api/analyze",
        json={"content": content, "revision": analysis["document"]["revision"]},
    )
    assert updated.status_code == 200
    assert client.get("/api/graph").status_code == 200


def test_lists_and_opens_workspace_bicep_files():
    client = app.test_client()

    files = client.get("/api/files").get_json()["files"]
    assert "examples/sample.bicep" in files

    response = client.post("/api/document", json={"path": "examples/sample.bicep"})
    assert response.status_code == 200
    assert response.get_json()["document"]["path"] == "examples/sample.bicep"


def test_rejects_document_path_traversal():
    response = app.test_client().post("/api/document", json={"path": "../outside.bicep"})
    assert response.status_code == 400
    assert "workspace" in response.get_json()["error"]


def test_status_accepts_local_llm_configuration_without_a_key(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "ollama/llama3.1")
    monkeypatch.setenv("LLM_API_BASE", "http://localhost:11434")
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    response = app.test_client().get("/api/status")

    assert response.status_code == 200
    assert response.get_json()["llm_configured"] is True