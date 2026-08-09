"""Replaceable AI model-provider boundary for MootOS."""

import json
import os
from dataclasses import dataclass
from typing import Any, Optional, Protocol

from dotenv import load_dotenv
from openai import OpenAI

from backend.model_input import (
    ModelInputBudgetError,
    ModelInputDiagnostics,
    prepare_model_input,
)
from backend.tool_types import ToolRequest, ToolResult


load_dotenv()

PROVIDER_TIMEOUT_SECONDS = 45.0
PROVIDER_MAX_RETRIES = 0


class ModelConfigurationError(RuntimeError):
    """Raised when the selected model provider is not configured."""


class ModelProviderError(RuntimeError):
    """Raised when a configured provider fails to return a usable response."""


@dataclass(frozen=True)
class ModelResponse:
    """Normalized response returned by every MootOS model provider."""

    text: str
    provider: str
    model: str


@dataclass(frozen=True)
class ToolConversationTurn:
    """One normalized provider turn from a tool-calling conversation.

    ``kind`` is either ``"final"`` (the model answered in plain text) or
    ``"tool_calls"`` (the model wants to invoke one or more registered
    tools). ``state`` is an opaque continuation object owned entirely by the
    provider that produced it -- callers must pass it back unmodified to
    ``continue_tool_turn`` and must never inspect its contents. This is what
    keeps provider-native tool-call objects (OpenAI Responses API items, or
    any future provider's own format) from ever leaking outside
    ``backend/model_router.py``.
    """

    kind: str
    text: Optional[str]
    tool_requests: list[ToolRequest]
    provider: str
    model: str
    state: Any = None


class ModelProvider(Protocol):
    """Interface that every future local or cloud model provider must follow."""

    name: str
    model: str

    def ensure_ready(self) -> None:
        """Raise a configuration error when the provider cannot run."""

    def generate(
        self,
        messages: list[dict[str, str]],
        instructions: str,
    ) -> ModelResponse:
        """Generate one assistant response."""

    # Tool calling is an optional provider capability, not part of the
    # required Protocol surface: a provider that never implements
    # start_tool_turn/continue_tool_turn simply cannot run tool-calling
    # conversations. ModelRouter checks for these with hasattr() rather
    # than requiring every provider to declare a no-op version.


class OpenAIProvider:
    """OpenAI Responses API implementation of the model-provider interface."""

    name = "openai"

    def __init__(self) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.model = os.getenv("OPENAI_MODEL", "gpt-5-mini")

    def ensure_ready(self) -> None:
        if not self.api_key or self.api_key == "your_api_key_here":
            raise ModelConfigurationError(
                "OpenAI is selected but OPENAI_API_KEY is not configured"
            )

    def generate(
        self,
        messages: list[dict[str, str]],
        instructions: str,
    ) -> ModelResponse:
        self.ensure_ready()
        try:
            client = OpenAI(
                api_key=self.api_key,
                timeout=PROVIDER_TIMEOUT_SECONDS,
                max_retries=PROVIDER_MAX_RETRIES,
            )
            response = client.responses.create(
                model=self.model,
                instructions=instructions,
                input=messages,
                store=False,
            )
        except Exception as error:
            raise ModelProviderError("Model provider request failed") from error

        text = (response.output_text or "").strip()
        if not text:
            raise ModelProviderError("Model provider returned an empty response")
        return ModelResponse(text=text, provider=self.name, model=self.model)

    # --- Tool calling (OpenAI Responses API function tools) -----------------
    #
    # Every OpenAI-native shape (the raw "input" item list, "function_call"
    # output items, "function_call_output" items) is built and consumed only
    # inside this class. Callers outside this module only ever see
    # ToolConversationTurn, ToolRequest, and ToolResult.

    def _build_function_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["input_schema"],
            }
            for tool in tools
        ]

    def _call_responses_api(
        self,
        *,
        instructions: str,
        input_items: list[Any],
        tools: Optional[list[dict[str, Any]]],
    ) -> Any:
        try:
            client = OpenAI(
                api_key=self.api_key,
                timeout=PROVIDER_TIMEOUT_SECONDS,
                max_retries=PROVIDER_MAX_RETRIES,
            )
            return client.responses.create(
                model=self.model,
                instructions=instructions,
                input=input_items,
                tools=tools,
                store=False,
            )
        except Exception as error:
            raise ModelProviderError("Model provider request failed") from error

    def _parse_tool_response(
        self,
        response: Any,
        *,
        input_items: list[Any],
        instructions: str,
    ) -> ToolConversationTurn:
        output_items = list(getattr(response, "output", None) or [])
        tool_requests: list[ToolRequest] = []
        seen_call_ids: set[str] = set()
        for item in output_items:
            if getattr(item, "type", None) != "function_call":
                continue

            # A call_id is how a tool result is matched back to the model's
            # own request on the next turn (see continue_tool_turn). A
            # missing/empty or duplicated call_id makes that matching
            # ambiguous -- rather than guess which result belongs to which
            # call, refuse the whole turn.
            raw_call_id = getattr(item, "call_id", None)
            call_id = str(raw_call_id).strip() if raw_call_id is not None else ""
            if not call_id:
                raise ModelProviderError(
                    "Model provider returned a tool call with a missing call_id"
                )
            if call_id in seen_call_ids:
                raise ModelProviderError(
                    "Model provider returned duplicate tool call_id values"
                )
            seen_call_ids.add(call_id)

            raw_arguments = getattr(item, "arguments", None) or "{}"
            try:
                parsed_arguments = json.loads(raw_arguments)
            except (TypeError, ValueError) as error:
                raise ModelProviderError(
                    "Model provider returned malformed tool arguments"
                ) from error
            if not isinstance(parsed_arguments, dict):
                raise ModelProviderError(
                    "Model provider returned a non-object tool argument payload"
                )
            tool_requests.append(
                ToolRequest(
                    name=str(getattr(item, "name", "")),
                    arguments=parsed_arguments,
                    call_id=call_id,
                )
            )

        state = _OpenAIToolState(
            input_items=input_items + output_items,
            instructions=instructions,
        )

        if tool_requests:
            return ToolConversationTurn(
                kind="tool_calls",
                text=None,
                tool_requests=tool_requests,
                provider=self.name,
                model=self.model,
                state=state,
            )

        text = (getattr(response, "output_text", "") or "").strip()
        if not text:
            raise ModelProviderError("Model provider returned an empty response")
        return ToolConversationTurn(
            kind="final",
            text=text,
            tool_requests=[],
            provider=self.name,
            model=self.model,
            state=state,
        )

    def start_tool_turn(
        self,
        messages: list[dict[str, str]],
        instructions: str,
        tools: list[dict[str, Any]],
    ) -> ToolConversationTurn:
        """Start a fresh tool-calling conversation turn."""
        self.ensure_ready()
        input_items: list[Any] = list(messages)
        response = self._call_responses_api(
            instructions=instructions,
            input_items=input_items,
            tools=self._build_function_tools(tools) if tools else None,
        )
        return self._parse_tool_response(
            response,
            input_items=input_items,
            instructions=instructions,
        )

    def continue_tool_turn(
        self,
        state: Any,
        tool_results: list[ToolResult],
        *,
        force_text: bool = False,
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> ToolConversationTurn:
        """Continue a tool-calling conversation after executing its tool calls.

        ``force_text`` omits the tool list entirely so the provider is asked
        to conclude in plain language instead of requesting another tool --
        used only when MootOS's tool-call budget has been reached and the
        loop must stop safely.
        """
        self.ensure_ready()
        if not isinstance(state, _OpenAIToolState):
            raise ModelProviderError("Invalid tool-conversation continuation state")

        function_outputs = [
            {
                "type": "function_call_output",
                "call_id": result.call_id,
                "output": json.dumps(
                    result.data if result.success else {"error": result.summary},
                    default=str,
                ),
            }
            for result in tool_results
        ]
        continued_input = state.input_items + function_outputs
        response = self._call_responses_api(
            instructions=state.instructions,
            input_items=continued_input,
            tools=None if force_text else (self._build_function_tools(tools) if tools else None),
        )
        return self._parse_tool_response(
            response,
            input_items=continued_input,
            instructions=state.instructions,
        )


@dataclass(frozen=True)
class _OpenAIToolState:
    """Opaque OpenAI-native continuation state for one tool-calling turn.

    Private to this module by convention (leading underscore): nothing
    outside ``backend/model_router.py`` should construct, inspect, or
    depend on this shape.
    """

    input_items: list[Any]
    instructions: str


class ModelRouter:
    """Select, bound, and call the configured replaceable AI provider."""

    def __init__(self) -> None:
        self.provider_name = os.getenv("AI_PROVIDER", "openai").lower()
        self.providers: dict[str, ModelProvider] = {
            "openai": OpenAIProvider(),
        }
        self.last_input_diagnostics: Optional[ModelInputDiagnostics] = None

    def _get_provider(self) -> ModelProvider:
        provider = self.providers.get(self.provider_name)
        if provider is None:
            available = ", ".join(sorted(self.providers))
            raise ModelConfigurationError(
                f"Unknown AI_PROVIDER '{self.provider_name}'. Available: {available}"
            )
        return provider

    def ensure_ready(self) -> None:
        """Validate the selected provider before preparing a chat turn."""
        self._get_provider().ensure_ready()

    def generate(
        self,
        messages: list[dict[str, str]],
        instructions: str,
    ) -> ModelResponse:
        """Apply fixed capabilities, budgets, and guidance before generation."""
        provider = self._get_provider()
        provider.ensure_ready()
        try:
            prepared = prepare_model_input(
                base_instructions=instructions,
                messages=messages,
            )
        except ModelInputBudgetError as error:
            raise ModelProviderError("Model input preparation failed") from error

        self.last_input_diagnostics = prepared.diagnostics
        return provider.generate(
            messages=prepared.messages,
            instructions=prepared.instructions,
        )

    def supports_tools(self) -> bool:
        """Whether the currently selected provider implements tool calling.

        A capability probe, not a readiness check: an unconfigured/unknown
        provider simply reports no tool support rather than raising.
        """
        try:
            provider = self._get_provider()
        except ModelConfigurationError:
            return False
        return hasattr(provider, "start_tool_turn") and hasattr(provider, "continue_tool_turn")

    def generate_with_tools(
        self,
        messages: list[dict[str, str]],
        instructions: str,
        tools: list[dict[str, Any]],
    ) -> ToolConversationTurn:
        """Start a tool-calling turn with the same input budgeting as ``generate``."""
        provider = self._get_provider()
        provider.ensure_ready()
        if not hasattr(provider, "start_tool_turn"):
            raise ModelConfigurationError(
                f"Provider '{provider.name}' does not support tool calling"
            )
        try:
            prepared = prepare_model_input(
                base_instructions=instructions,
                messages=messages,
            )
        except ModelInputBudgetError as error:
            raise ModelProviderError("Model input preparation failed") from error

        self.last_input_diagnostics = prepared.diagnostics
        return provider.start_tool_turn(prepared.messages, prepared.instructions, tools)

    def continue_tool_turn(
        self,
        state: Any,
        tool_results: list[ToolResult],
        *,
        force_text: bool = False,
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> ToolConversationTurn:
        """Continue a tool-calling turn using the provider's own opaque state."""
        provider = self._get_provider()
        provider.ensure_ready()
        if not hasattr(provider, "continue_tool_turn"):
            raise ModelConfigurationError(
                f"Provider '{provider.name}' does not support tool calling"
            )
        return provider.continue_tool_turn(
            state,
            tool_results,
            force_text=force_text,
            tools=tools,
        )


def get_model_router() -> ModelRouter:
    """Build the current model router from environment settings."""
    return ModelRouter()
