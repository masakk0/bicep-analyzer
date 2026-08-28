"""
src/api/server.py
──────────────────
Flask REST API and static UI server.
Run with: python src/api/server.py
"""

from __future__ import annotations

import os
import sys
from dataclasses import asdict
from pathlib import Path

# Ensure project root is on sys.path when launched via `python src/api/server.py`
_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

# Load .env from the project root, regardless of the current working directory.
_ENV_PATH = _ROOT / ".env"
load_dotenv(dotenv_path=_ENV_PATH, override=True)

from src.parser.bicep_parser import BicepParser
from src.graph.builder import InfraGraph
from src.analyzer.risk_engine import RiskEngine
from src.agent.agent import BicepTwinAgent
from src.workspace import BicepWorkspace

# ─────────────────────────────────────────────
app = Flask(__name__, static_folder=None)
CORS(app)

UI_DIR = Path(__file__).parent.parent / "ui" / "static"
parser = BicepParser()
risk_engine = RiskEngine()
workspace = BicepWorkspace(_ROOT)

# Session state (in-memory, currently single-user).
_state: dict = {"graph": None, "agent": None}


def _serialize_risks(risks) -> list[dict]:
    return [asdict(risk) for risk in risks]


def _analysis_for(content: str) -> tuple[InfraGraph, list]:
    result = parser.parse(content)
    if not result.resources:
        raise ValueError("No resources found in the template")
    graph = InfraGraph(result)
    return graph, risk_engine.evaluate(graph)


def _llm_is_configured() -> bool:
    return bool(os.environ.get("LLM_MODEL")) and bool(
        os.environ.get("LLM_API_KEY") or os.environ.get("LLM_API_BASE")
    )


def _install_graph(graph: InfraGraph) -> None:
    _state["graph"] = graph
    agent: BicepTwinAgent = _state.get("agent")
    if agent:
        agent.update_graph(graph)
        return

    if _llm_is_configured():
        try:
            _state["agent"] = BicepTwinAgent(
                graph=graph,
                risk_engine=risk_engine,
                api_key=os.environ.get("LLM_API_KEY"),
                document_handler=lambda: asdict(workspace.snapshot()),
                edit_handler=_agent_replace,
                save_handler=_agent_save,
            )
        except Exception as error:
            app.logger.error(f"Agent initialization error: {error}")


def _payload(graph: InfraGraph, risks: list) -> dict:
    return {
        "graph": graph.to_dict(),
        "summary": graph.summary(),
        "risks": _serialize_risks(risks),
        "document": asdict(workspace.snapshot()),
    }


def _update_document(content: str, revision=None, save=False, path=None, detach=False) -> dict:
    graph, risks = _analysis_for(content)
    if detach:
        workspace.new(content)
    else:
        workspace.update(content, revision)
    if save or path:
        workspace.save(path)
    _install_graph(graph)
    return _payload(graph, risks)


def _agent_replace(old_text: str, new_text: str) -> dict:
    current = workspace.snapshot()
    occurrences = current.content.count(old_text)
    if not old_text or occurrences != 1:
        raise ValueError(
            f"The text to replace must occur exactly once; occurrences: {occurrences}"
        )
    content = current.content.replace(old_text, new_text, 1)
    graph, risks = _analysis_for(content)
    workspace.replace(old_text, new_text, current.revision)
    _install_graph(graph)
    return {
        "updated": True,
        "document": asdict(workspace.snapshot()),
        "summary": graph.summary(),
        "risk_count": len(risks),
    }


def _agent_save(path=None) -> dict:
    return {"saved": True, "document": asdict(workspace.save(path))}


# ─────────────────────────────────────────────
# Static UI
# ─────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(UI_DIR, "index.html")

@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(UI_DIR, filename)


# ─────────────────────────────────────────────
# API
# ─────────────────────────────────────────────
@app.route("/api/analyze", methods=["POST"])
def analyze():
    data = request.get_json() or {}
    content = data.get("content", "").strip()
    if not content:
        return jsonify({"error": "Template vuoto"}), 400

    try:
        return jsonify(_update_document(
            content,
            revision=data.get("revision"),
            save=bool(data.get("save")),
            path=data.get("path"),
            detach=bool(data.get("detach")),
        ))
    except (ValueError, OSError) as error:
        return jsonify({"error": str(error)}), 400


@app.route("/api/document", methods=["GET", "POST", "PUT"])
def document():
    if request.method == "GET":
        return jsonify(asdict(workspace.snapshot()))

    data = request.get_json() or {}
    try:
        if request.method == "POST":
            snapshot = workspace.open(data.get("path", ""))
            graph, risks = _analysis_for(snapshot.content)
            _install_graph(graph)
            return jsonify(_payload(graph, risks))
        return jsonify(_update_document(
            data.get("content", ""),
            revision=data.get("revision"),
            save=bool(data.get("save", True)),
            path=data.get("path"),
            detach=bool(data.get("detach")),
        ))
    except (ValueError, OSError) as error:
        return jsonify({"error": str(error)}), 400


@app.route("/api/files")
def list_bicep_files():
    files = [
        path.relative_to(_ROOT).as_posix()
        for path in _ROOT.rglob("*.bicep")
        if ".git" not in path.parts and ".venv" not in path.parts
    ]
    return jsonify({"files": sorted(files)})


@app.route("/api/graph")
def export_graph():
    graph: InfraGraph = _state.get("graph")
    if not graph:
        return jsonify({"error": "No template analyzed"}), 400
    return jsonify({"graph": graph.to_dict(), "summary": graph.summary()})


@app.route("/api/resource/<symbol_name>")
def resource_detail(symbol_name):
    graph: InfraGraph = _state.get("graph")
    if not graph:
        return jsonify({"error": "No template analyzed"}), 400

    node = graph.get_resource(symbol_name)
    if not node:
        return jsonify({"error": f"Resource '{symbol_name}' not found"}), 404

    return jsonify({
        **{k: v for k, v in node.items() if k != "raw_properties"},
        "dependencies": [
            {k: v for k, v in d.items() if k != "raw_properties"}
            for d in graph.get_dependencies(symbol_name)
        ],
        "dependents": [
            {k: v for k, v in d.items() if k != "raw_properties"}
            for d in graph.get_dependents(symbol_name)
        ],
    })


@app.route("/api/simulate/<symbol_name>")
def simulate_failure(symbol_name):
    graph: InfraGraph = _state.get("graph")
    if not graph:
        return jsonify({"error": "No template analyzed"}), 400

    result = graph.simulate_failure(symbol_name)

    def clean(lst):
        return [{k: v for k, v in r.items() if k != "raw_properties"} for r in lst]

    if "error" in result:
        return jsonify(result), 404

    return jsonify({
        "failed_resource": {k: v for k, v in result["failed_resource"].items() if k != "raw_properties"},
        "direct_dependents": clean(result["direct_dependents"]),
        "all_impacted": clean(result["all_impacted"]),
        "impact_count": result["impact_count"],
    })


@app.route("/api/status", methods=["GET"])
def status():
    return jsonify({
        "llm_configured": _llm_is_configured(),
        "agent_ready": _state.get("agent") is not None,
        "graph_loaded": _state.get("graph") is not None,
    })


@app.route("/api/chat", methods=["POST"])
def chat():
    agent: BicepTwinAgent = _state.get("agent")
    if not agent:
        return jsonify({"error": "Agent unavailable. Configure LLM_API_KEY in the .env file"}), 400

    data = request.get_json()
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "Messaggio vuoto"}), 400

    try:
        previous_revision = workspace.snapshot().revision
        response = agent.chat(message)
        result = {
            "answer": response.answer,
            "steps": [
                {"type": s.type, "content": s.content, "tool_name": s.tool_name}
                for s in response.steps
            ],
            "total_tokens": response.total_tokens,
        }
        if workspace.snapshot().revision != previous_revision:
            graph: InfraGraph = _state["graph"]
            result["analysis"] = _payload(graph, risk_engine.evaluate(graph))
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/chat/reset", methods=["POST"])
def chat_reset():
    agent: BicepTwinAgent = _state.get("agent")
    if agent:
        agent.reset_history()
    return jsonify({"ok": True})


@app.route("/api/example")
def get_example():
    example_path = Path(__file__).parent.parent.parent / "examples" / "sample.bicep"
    if example_path.exists():
        return jsonify({"content": example_path.read_text(encoding="utf-8")})
    return jsonify({"error": "Example not found"}), 404


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n🔷 Bicep Twin running at http://localhost:{port}\n")
    app.run(debug=True, port=port)