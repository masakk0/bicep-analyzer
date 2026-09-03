# Bicep Twin
<img width="791" height="395" alt="image" src="https://github.com/user-attachments/assets/dd4b41c1-47b9-41d2-b6f8-18a3c33daa8b" />

Bicep Twin is a local web application for exploring Azure Bicep templates. It parses a template into an infrastructure graph, identifies configurable architectural risks, visualizes resource dependencies, and provides an optional LLM assistant with controlled graph and document tools.

The project is provider-neutral. Its LLM integration uses [LiteLLM](https://docs.litellm.ai/), so you can select a model from OpenAI, Anthropic, Azure OpenAI, Ollama, OpenRouter, or another supported provider without changing application code.

## Features

- Parse Bicep resources, modules, parameters, and dependencies.
- Visualize the infrastructure graph and inspect resource relationships.
- Evaluate YAML-defined risk rules, including missing private endpoints and risky properties.
- Simulate a resource failure and show direct and cascading impact.
- Edit the active Bicep document through revision-aware, non-ambiguous replacements.
- Save only `.bicep` files inside the project workspace using atomic writes.
- Use an optional LLM assistant with read, analysis, edit, and save tools.

## Requirements

- Python 3.10 or later.
- An LLM provider and model that supports tool/function calling if you want to use the assistant.
- A provider API key, unless using a local model with no authentication.

## Installation

Clone the repository, then create and activate a virtual environment.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create a local environment file from the safe template. Do not commit the resulting `.env` file.

```powershell
Copy-Item .env.example .env
```

## LLM Configuration

All LLM settings are read from environment variables. The application does not contain provider endpoints, credentials, deployments, charge codes, or organization-specific defaults.

| Variable | Required | Description |
| --- | --- | --- |
| `LLM_MODEL` | Yes | LiteLLM model identifier. |
| `LLM_API_KEY` | Usually | Provider API key. Leave unset only when the selected provider does not require it. |
| `LLM_API_BASE` | No | Custom or self-hosted OpenAI-compatible endpoint. |
| `LLM_API_VERSION` | No | API version required by some providers, including Azure OpenAI. |

Examples:

```dotenv
# OpenAI
LLM_MODEL=openai/gpt-4.1-mini
LLM_API_KEY=your-openai-api-key

# Anthropic
# LLM_MODEL=anthropic/claude-sonnet-4-5
# LLM_API_KEY=your-anthropic-api-key

# Ollama (use a tool-capable model)
# LLM_MODEL=ollama/llama3.1
# LLM_API_BASE=http://localhost:11434

# Azure OpenAI
# LLM_MODEL=azure/your-deployment-name
# LLM_API_KEY=your-azure-openai-key
# LLM_API_BASE=https://your-resource.openai.azure.com
# LLM_API_VERSION=2024-10-21
```

LiteLLM supports many more providers and model identifiers. Refer to its provider documentation for the exact identifier and any provider-specific environment variables. The selected model must support OpenAI-compatible tool calling; otherwise the graph assistant cannot operate correctly.

## Run Locally

```powershell
python src/api/server.py
```

Open `http://localhost:5000` in a browser. Set `PORT` to use a different port.

## Usage

1. Open a Bicep file from the workspace, load the sample, or paste a template.
2. Use the Resources, Graph, and Risks views to inspect the infrastructure.
3. Run a failure simulation for a resource to see the dependency impact.
4. Configure the LLM variables and use the Agent tab for questions such as:

```text
What is the highest-risk part of this architecture?
Which resources are exposed without a private endpoint?
What is the cascading impact if the virtual network fails?
Suggest a concrete Bicep change to improve production readiness.
```

The assistant reads graph data through tools before answering. It only edits a Bicep document after an explicit request. Edits use exact, single-occurrence replacements, and saving is restricted to `.bicep` files within the project workspace.

## REST API

| Endpoint | Description |
| --- | --- |
| `POST /api/analyze` | Analyze content and update the active document. |
| `GET/POST/PUT /api/document` | Get, open, or update the versioned Bicep document. |
| `GET /api/files` | List Bicep files in the workspace. |
| `GET /api/graph` | Export the current infrastructure graph. |
| `GET /api/resource/<symbol_name>` | Get resource details and relationships. |
| `GET /api/simulate/<symbol_name>` | Simulate a resource failure. |
| `GET /api/status` | Get graph and LLM-agent availability. |
| `POST /api/chat` | Send a message to the LLM assistant. |
| `POST /api/chat/reset` | Clear the assistant conversation history. |

## Risk Rules

Risk rules live in `config/risk_rules.yaml`. They can be enabled, disabled, or extended without modifying Python code. Supported checks include property matching, missing properties or dependencies, property-content checks, and missing resource categories.

## Security and Public Repository Checklist

- `.env`, virtual environments, test caches, logs, and editor settings are ignored by Git.
- `.env.example` contains placeholders only. Keep real credentials exclusively in `.env` or your secret manager.
- Before pushing, inspect staged changes with `git diff --cached` and scan for keys with your secret-scanning tool of choice.
- Rotate any credential that was ever committed, shared, or exposed in a terminal, chat, issue, or pull request.
- The development server enables Flask debug mode when launched directly. Do not expose it to an untrusted network or use it as a production deployment.
- Bicep files may themselves contain sensitive values. Review templates before sharing them publicly.

## Testing

```powershell
pytest -q
```

The test suite covers parsing, graph behavior, risk evaluation, workspace path protection, API behavior, and generic LLM request configuration.

## Project Layout

```text
config/                 Application settings and risk rules
examples/               Sample Bicep template
src/agent/              LLM adapter and graph tool executor
src/analyzer/           Configurable risk engine
src/api/                Flask API and static UI server
src/graph/              Infrastructure graph construction and queries
src/parser/             Bicep resource and dependency parser
src/ui/static/          Browser UI
src/workspace.py        Versioned, workspace-confined Bicep editing
tests/                  Automated tests
```
