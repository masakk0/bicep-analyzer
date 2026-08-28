"""
src/agent/agent.py
───────────────────
LLM-agnostic agent with a tool-use loop.
Receives a natural-language question about the infrastructure and answers
using graph tools.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Callable, Optional

from litellm import completion

from src.graph.builder import InfraGraph
from src.analyzer.risk_engine import RiskEngine
from src.agent.tools import TOOL_SCHEMAS, ToolExecutor


# ─────────────────────────────────────────────────────────────
# Data models
# ─────────────────────────────────────────────────────────────
@dataclass
class AgentStep:
    """Single step in the agent's reasoning."""
    type: str            # "tool_call" | "tool_result" | "answer"
    content: str
    tool_name: Optional[str] = None
    tool_args: Optional[dict] = None


@dataclass
class AgentResponse:
    answer: str
    steps: list[AgentStep] = field(default_factory=list)
    total_tokens: int = 0


# ─────────────────────────────────────────────────────────────
# Agent
# ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a cloud architect specializing in Azure and Bicep infrastructure.
You can use tools to query the infrastructure graph.

Guidelines:
- Always answer in English
- Use tools to collect data before answering
- Be precise and technical; refer to resources by symbolic name
- When you identify a problem, always propose a concrete Bicep solution
- If you simulate a failure, explain the operational consequences, not only the technical ones
- Only modify the document with replace_bicep_text when the user explicitly asks
- Before modifying, use the read tools; prefer small, unambiguous replacements
- After a successful modification, save with save_bicep_file and describe exactly what changed
"""


class BicepTwinAgent:
    """
    Conversational agent backed by any LiteLLM-supported provider and model.
    The model must support OpenAI-compatible tool calling.
    """

    def __init__(
        self,
        graph: InfraGraph,
        risk_engine: RiskEngine,
        model: Optional[str] = None,
        max_iterations: int = 10,
        verbose: bool = True,
        api_key: Optional[str] = None,
        document_handler: Optional[Callable[[], dict]] = None,
        edit_handler: Optional[Callable[[str, str], dict]] = None,
        save_handler: Optional[Callable[[Optional[str]], dict]] = None,
    ):
        self.graph = graph
        self.risk_engine = risk_engine
        self.model = model or os.environ.get("LLM_MODEL", "openai/gpt-4.1-mini")
        self.max_iterations = max_iterations
        self.verbose = verbose
        self.executor = ToolExecutor(
            graph, risk_engine, document_handler, edit_handler, save_handler
        )
        self.api_key = api_key or os.environ.get("LLM_API_KEY", "")
        self.api_base = os.environ.get("LLM_API_BASE")
        self.api_version = os.environ.get("LLM_API_VERSION")
        self._history: list[dict] = []

    def _complete(self, messages: list[dict], tools: Optional[list[dict]] = None):
        options = {
            "model": self.model,
            "messages": messages,
            "api_key": self.api_key or None,
            "api_base": self.api_base,
            "api_version": self.api_version,
        }
        if tools is not None:
            options.update({"tools": tools, "tool_choice": "auto"})
        return completion(**options)

    def chat(self, user_message: str) -> AgentResponse:
        """
        Send a message to the agent and get a response.
        Conversation history is preserved.
        """
        self._history.append({"role": "user", "content": user_message})

        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + self._history
        steps: list[AgentStep] = []
        total_tokens = 0

        for iteration in range(self.max_iterations):
            response = self._complete(messages, TOOL_SCHEMAS)

            total_tokens += response.usage.total_tokens if response.usage else 0
            message = response.choices[0].message

            # No tool call means this is the final response.
            if not message.tool_calls:
                answer = message.content or ""
                self._history.append({"role": "assistant", "content": answer})
                steps.append(AgentStep(type="answer", content=answer))
                return AgentResponse(answer=answer, steps=steps, total_tokens=total_tokens)

            # Esegui tutti i tool calls
            messages.append(message.model_dump(exclude_unset=True))

            for tool_call in message.tool_calls:
                fn_name = tool_call.function.name
                fn_args = json.loads(tool_call.function.arguments)

                steps.append(AgentStep(
                    type="tool_call",
                    content=f"Calling {fn_name}({json.dumps(fn_args, ensure_ascii=False)})",
                    tool_name=fn_name,
                    tool_args=fn_args,
                ))

                result = self.executor.execute(fn_name, fn_args)

                steps.append(AgentStep(
                    type="tool_result",
                    content=result,
                    tool_name=fn_name,
                ))

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })

        # If iterations are exhausted, request a final response without tools.
        response = self._complete(messages + [
            {"role": "user", "content": "Answer based on the data collected."}
        ])
        answer = response.choices[0].message.content or ""
        self._history.append({"role": "assistant", "content": answer})
        steps.append(AgentStep(type="answer", content=answer))
        return AgentResponse(answer=answer, steps=steps, total_tokens=total_tokens)

    def reset_history(self) -> None:
        """Clear the conversation history."""
        self._history = []

    def update_graph(self, graph: InfraGraph) -> None:
        """Refresh tool context while preserving the conversation history."""
        self.graph = graph
        self.executor.graph = graph

    @property
    def history(self) -> list[dict]:
        return list(self._history)
