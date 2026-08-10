"""Deterministic, explicit tool registration for the MootOS Tool System.

Registration is intentionally the opposite of dynamic: there is no plugin
discovery, no import-by-name, and no way for a model or request to add a
tool. ``build_default_registry`` calls one explicit Python function
(``backend.tools_reference.register_reference_tools``) that registers each
of the four V0.2A tools by direct reference. Anything not registered here
does not exist as far as MootOS's Tool System is concerned, and looking it
up fails closed with ``ToolNotFoundError``.
"""

import threading
from typing import Any, Optional

from backend.tool_types import DuplicateToolError, ToolDefinition, ToolNotFoundError


class ToolRegistry:
    """An explicit, in-memory collection of registered tool definitions."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        """Register one tool. Raises when the name is already registered."""
        if definition.name in self._tools:
            raise DuplicateToolError(f"Tool '{definition.name}' is already registered")
        self._tools[definition.name] = definition

    def get(self, name: str) -> ToolDefinition:
        """Return one tool definition by its exact name. Fails closed."""
        definition = self._tools.get(name)
        if definition is None:
            raise ToolNotFoundError(f"Unknown tool: {name}")
        return definition

    def list_definitions(self) -> list[ToolDefinition]:
        """Return every registered definition, deterministically ordered by name."""
        return [self._tools[name] for name in sorted(self._tools)]

    def catalog(self) -> list[dict[str, Any]]:
        """Return the safe, JSON-serializable catalog exposed to a model/API."""
        return [definition.to_catalog_entry() for definition in self.list_definitions()]

    def __len__(self) -> int:
        return len(self._tools)


def build_default_registry() -> ToolRegistry:
    """Build the standard MootOS registry: V0.2A reference tools + V0.3C.

    Both registration calls are explicit, by direct reference -- there is
    still no plugin discovery, no filesystem scanning, and no way for a
    request or a model to add a tool. ``register_v03c_tools`` additionally
    registers ``web.search`` only when a search service is configured, so an
    unconfigured deployment honestly reports no web capability.
    """
    # Imported here (not at module load) to avoid a load-order cycle:
    # backend.tools_reference imports ToolDefinition/ToolRegistry from this
    # module's sibling files, and this keeps backend.tool_registry itself
    # free of a hard dependency on the concrete reference tools at import
    # time.
    from backend.tools_reference import register_reference_tools
    from backend.tools_web import register_v03c_tools

    registry = ToolRegistry()
    register_reference_tools(registry)
    register_v03c_tools(registry)
    return registry


_registry_lock = threading.Lock()
_default_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    """Return the process-wide default registry, building it once, lazily."""
    global _default_registry
    with _registry_lock:
        if _default_registry is None:
            _default_registry = build_default_registry()
        return _default_registry


def reset_tool_registry() -> None:
    """Clear the cached default registry. Test-only; production never needs this."""
    global _default_registry
    with _registry_lock:
        _default_registry = None
