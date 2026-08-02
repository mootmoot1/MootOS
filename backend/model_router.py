"""Replaceable AI model-provider boundary for MootOS."""

import os
from dataclasses import dataclass
from typing import Protocol

from dotenv import load_dotenv
from openai import OpenAI

from backend.conversation_guidance import build_conversation_instructions


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


class ModelRouter:
    """Select and call the configured replaceable AI provider."""

    def __init__(self) -> None:
        self.provider_name = os.getenv("AI_PROVIDER", "openai").lower()
        self.providers: dict[str, ModelProvider] = {
            "openai": OpenAIProvider(),
        }

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
        """Apply conversation guidance and generate through the selected provider."""
        provider = self._get_provider()
        provider.ensure_ready()
        refined_instructions = build_conversation_instructions(
            base_instructions=instructions,
            messages=messages,
        )
        return provider.generate(
            messages=messages,
            instructions=refined_instructions,
        )


def get_model_router() -> ModelRouter:
    """Build the current model router from environment settings."""
    return ModelRouter()
