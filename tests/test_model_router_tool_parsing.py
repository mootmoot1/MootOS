"""Focused tests for the OpenAI provider boundary: the dotted-internal-name
<-> OpenAI-safe-function-name mapping, and tool-call response parsing.

MootOS internal tool names are stable and dotted (``projects.list``,
``tasks.create``). OpenAI function-tool names must not contain ``.`` --
sending a dotted name unchanged makes the live Responses API reject the
request outright (confirmed against live Railway/OpenAI traffic). These
tests exercise ``OpenAIProvider._encode_tool_name`` /
``_decode_tool_name`` / ``_build_function_tools`` / ``_parse_tool_response``
directly against plain ``SimpleNamespace`` stand-ins for the Responses
API's ``response.output`` items, so they run with no network access and no
API key. See backend/model_router.py -- every OpenAI-native shape is built
and consumed only inside this class; internal MootOS code never sees a
provider-safe name.
"""

import re
from types import SimpleNamespace

import pytest

from backend.model_router import ModelProviderError, OpenAIProvider
from backend.tool_registry import get_tool_registry


# OpenAI function names: letters, digits, underscores, hyphens.
OPENAI_FUNCTION_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

# Dotted internal names that are always registered, across every
# configuration. The provider-boundary tests below derive the rest from the
# live registry rather than hard-coding a count, so adding a tool (V0.3C
# added self.state/self.architecture, and web.search when configured) does
# not require editing an unrelated encoding test.
REFERENCE_TOOL_NAMES = ("projects.list", "memory.search", "tasks.list", "tasks.create")


def _provider() -> OpenAIProvider:
    return OpenAIProvider()


def _function_call(name, arguments="{}", call_id="call-1"):
    return SimpleNamespace(type="function_call", name=name, arguments=arguments, call_id=call_id)


# --- Name encoding / decoding -------------------------------------------------


def test_encode_maps_dots_to_the_d_escape_token():
    provider = _provider()
    assert provider._encode_tool_name("projects.list") == "projects_dlist"
    assert provider._encode_tool_name("tasks.create") == "tasks_dcreate"


@pytest.mark.parametrize("internal_name", REFERENCE_TOOL_NAMES)
def test_each_reference_tool_name_round_trips_through_encode_and_decode(internal_name):
    provider = _provider()
    encoded = provider._encode_tool_name(internal_name)
    assert "." not in encoded
    assert provider._decode_tool_name(encoded) == internal_name


def test_encode_decode_round_trips_all_currently_registered_tools():
    provider = _provider()
    definitions = get_tool_registry().list_definitions()
    assert set(REFERENCE_TOOL_NAMES) <= {d.name for d in definitions}
    for definition in definitions:
        encoded = provider._encode_tool_name(definition.name)
        assert provider._decode_tool_name(encoded) == definition.name


def test_encode_decode_round_trips_names_with_underscores_and_repeated_dots():
    # Not real MootOS tool names today, but the escape must stay correct
    # (and collision-free) for any future name shaped like this. In
    # particular, a naive "." -> "_" substitution would make "a_b" and
    # "a..b" collide on the same encoded string ("a__b"); this scheme must
    # not.
    provider = _provider()
    for name in ("tasks.create_v2", "a_b.c_d", "already_safe", "a.b.c", "_leading.dot", "a..b"):
        encoded = provider._encode_tool_name(name)
        assert provider._decode_tool_name(encoded) == name

    assert provider._encode_tool_name("a_b") != provider._encode_tool_name("a..b")


def test_provider_facing_tool_definitions_contain_only_openai_valid_names():
    """_build_function_tools() output must never contain '.' or anything
    outside OpenAI's allowed function-name character set."""
    provider = _provider()
    catalog = get_tool_registry().catalog()
    assert set(REFERENCE_TOOL_NAMES) <= {entry["name"] for entry in catalog}

    function_tools = provider._build_function_tools(catalog)

    assert len(function_tools) == len(catalog)
    for function_tool in function_tools:
        name = function_tool["name"]
        assert "." not in name
        assert OPENAI_FUNCTION_NAME_PATTERN.match(name), f"invalid provider function name: {name!r}"


def test_build_function_tools_names_round_trip_back_to_the_original_catalog():
    provider = _provider()
    catalog = get_tool_registry().catalog()

    function_tools = provider._build_function_tools(catalog)

    decoded_names = {provider._decode_tool_name(tool["name"]) for tool in function_tools}
    assert decoded_names == {tool["name"] for tool in catalog}


def test_build_function_tools_preserves_description_and_schema():
    provider = _provider()
    catalog = get_tool_registry().catalog()

    function_tools = provider._build_function_tools(catalog)

    by_encoded_name = {tool["name"]: tool for tool in function_tools}
    for entry in catalog:
        encoded = provider._encode_tool_name(entry["name"])
        built = by_encoded_name[encoded]
        assert built["type"] == "function"
        assert built["description"] == entry["description"]
        assert built["parameters"] == entry["input_schema"]


def test_decode_rejects_an_invalid_escape_sequence():
    """A lone "_" not followed by "u" or "d" cannot have come from
    _encode_tool_name -- fail closed rather than guess."""
    with pytest.raises(ModelProviderError, match="invalid escape"):
        _provider()._decode_tool_name("tasks_xlist")


# --- Response parsing: mapping back to internal names, fail-closed behavior --


def test_parses_a_valid_encoded_function_call_back_into_the_internal_tool_request():
    response = SimpleNamespace(
        output=[_function_call(name="projects_dlist", call_id="call-1")],
        output_text="",
    )

    turn = _provider()._parse_tool_response(
        response,
        input_items=[],
        instructions="x",
        offered_tools=[{"name": "projects.list"}],
    )

    assert turn.kind == "tool_calls"
    assert len(turn.tool_requests) == 1
    assert turn.tool_requests[0].name == "projects.list"
    assert turn.tool_requests[0].call_id == "call-1"


def test_unknown_provider_tool_name_is_rejected():
    """A name that decodes to something that was never offered fails closed."""
    response = SimpleNamespace(
        output=[_function_call(name="not_da_dreal_dtool", call_id="call-1")],
        output_text="",
    )

    with pytest.raises(ModelProviderError, match="unknown or unmappable"):
        _provider()._parse_tool_response(
            response,
            input_items=[],
            instructions="x",
            offered_tools=[{"name": "projects.list"}],
        )


def test_invalid_provider_escape_sequence_is_rejected():
    response = SimpleNamespace(
        output=[_function_call(name="tasks_xlist", call_id="call-1")],
        output_text="",
    )

    with pytest.raises(ModelProviderError, match="invalid escape"):
        _provider()._parse_tool_response(
            response,
            input_items=[],
            instructions="x",
            offered_tools=[{"name": "tasks.list"}],
        )


def test_provider_name_is_rejected_when_nothing_was_offered_this_round():
    """A force_text round offers no tools at all (see continue_tool_turn);
    a function_call showing up anyway must still be refused, not matched
    against a stale catalog from an earlier round."""
    response = SimpleNamespace(
        output=[_function_call(name="projects_dlist", call_id="call-1")],
        output_text="",
    )

    with pytest.raises(ModelProviderError, match="unknown or unmappable"):
        _provider()._parse_tool_response(
            response,
            input_items=[],
            instructions="x",
            offered_tools=None,
        )


def test_end_to_end_round_trip_for_every_registered_reference_tool():
    """Build the real provider tool schema for the default registry, fake a
    response using each of those provider-safe names, and confirm every one
    decodes back to its correct internal MootOS tool name."""
    provider = _provider()
    catalog = get_tool_registry().catalog()
    function_tools = provider._build_function_tools(catalog)

    output = [
        _function_call(name=function_tool["name"], call_id=f"call-{index}")
        for index, function_tool in enumerate(function_tools)
    ]
    response = SimpleNamespace(output=output, output_text="")

    turn = provider._parse_tool_response(
        response,
        input_items=[],
        instructions="x",
        offered_tools=catalog,
    )

    assert turn.kind == "tool_calls"
    # Every tool actually offered on this request round-trips back to its
    # exact internal dotted name -- derived from the live registry, so a
    # newly registered tool is automatically covered here.
    assert {request.name for request in turn.tool_requests} == {
        entry["name"] for entry in catalog
    }
    # And every request name is the original dotted internal name, never
    # the provider-safe one.
    for request in turn.tool_requests:
        assert "." in request.name


def test_final_text_response_without_tool_calls_still_works():
    response = SimpleNamespace(output=[], output_text="Hello there.")

    turn = _provider()._parse_tool_response(response, input_items=[], instructions="x")

    assert turn.kind == "final"
    assert turn.text == "Hello there."


def test_missing_call_id_is_rejected():
    item = SimpleNamespace(type="function_call", name="tool", arguments="{}", call_id="")
    response = SimpleNamespace(output=[item], output_text="")

    with pytest.raises(ModelProviderError, match="call_id"):
        _provider()._parse_tool_response(response, input_items=[], instructions="x")


def test_none_call_id_is_rejected():
    item = SimpleNamespace(type="function_call", name="tool", arguments="{}", call_id=None)
    response = SimpleNamespace(output=[item], output_text="")

    with pytest.raises(ModelProviderError, match="call_id"):
        _provider()._parse_tool_response(response, input_items=[], instructions="x")


def test_whitespace_only_call_id_is_rejected():
    item = SimpleNamespace(type="function_call", name="tool", arguments="{}", call_id="   ")
    response = SimpleNamespace(output=[item], output_text="")

    with pytest.raises(ModelProviderError, match="call_id"):
        _provider()._parse_tool_response(response, input_items=[], instructions="x")


def test_missing_call_id_attribute_entirely_is_rejected():
    # getattr(item, "call_id", None) falls back to None when the attribute
    # is absent entirely, not just empty -- must be rejected the same way.
    item = SimpleNamespace(type="function_call", name="tool", arguments="{}")
    response = SimpleNamespace(output=[item], output_text="")

    with pytest.raises(ModelProviderError, match="call_id"):
        _provider()._parse_tool_response(response, input_items=[], instructions="x")


def test_duplicate_call_id_within_the_same_turn_is_rejected():
    response = SimpleNamespace(
        output=[
            _function_call(name="tasks_dlist", call_id="dup"),
            _function_call(name="memory_dsearch", call_id="dup"),
        ],
        output_text="",
    )

    with pytest.raises(ModelProviderError, match="duplicate"):
        _provider()._parse_tool_response(
            response,
            input_items=[],
            instructions="x",
            offered_tools=[{"name": "tasks.list"}, {"name": "memory.search"}],
        )


def test_distinct_call_ids_in_the_same_turn_are_all_accepted():
    response = SimpleNamespace(
        output=[
            _function_call(name="tasks_dlist", call_id="a"),
            _function_call(name="memory_dsearch", call_id="b"),
        ],
        output_text="",
    )

    turn = _provider()._parse_tool_response(
        response,
        input_items=[],
        instructions="x",
        offered_tools=[{"name": "tasks.list"}, {"name": "memory.search"}],
    )

    assert {request.call_id for request in turn.tool_requests} == {"a", "b"}
    assert {request.name for request in turn.tool_requests} == {"tasks.list", "memory.search"}


def test_malformed_json_arguments_raise_model_provider_error():
    item = _function_call(name="projects_dlist", arguments="{not valid json")
    response = SimpleNamespace(output=[item], output_text="")

    with pytest.raises(ModelProviderError, match="malformed"):
        _provider()._parse_tool_response(
            response, input_items=[], instructions="x", offered_tools=[{"name": "projects.list"}]
        )


def test_non_object_arguments_raise_model_provider_error():
    item = _function_call(name="projects_dlist", arguments="[1, 2, 3]")
    response = SimpleNamespace(output=[item], output_text="")

    with pytest.raises(ModelProviderError, match="non-object"):
        _provider()._parse_tool_response(
            response, input_items=[], instructions="x", offered_tools=[{"name": "projects.list"}]
        )


def test_call_id_check_runs_before_argument_parsing():
    """A call missing its call_id is rejected even if its arguments are also
    malformed -- the ambiguous-matching problem is the one that matters."""
    item = SimpleNamespace(type="function_call", name="tool", arguments="{not json", call_id="")
    response = SimpleNamespace(output=[item], output_text="")

    with pytest.raises(ModelProviderError, match="call_id"):
        _provider()._parse_tool_response(response, input_items=[], instructions="x")


def test_argument_parsing_runs_before_the_name_mapping_check():
    """Malformed arguments on an otherwise-unknown name still report the
    argument problem -- there is no ordering trap that would let an
    unmappable name's arguments be silently ignored."""
    item = _function_call(name="not_da_dreal_dtool", arguments="{not valid json")
    response = SimpleNamespace(output=[item], output_text="")

    with pytest.raises(ModelProviderError, match="malformed"):
        _provider()._parse_tool_response(
            response, input_items=[], instructions="x", offered_tools=[{"name": "projects.list"}]
        )
