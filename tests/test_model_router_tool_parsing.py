"""Focused tests for OpenAIProvider's tool-call response parsing.

These exercise ``OpenAIProvider._parse_tool_response`` directly against
plain ``SimpleNamespace`` stand-ins for the OpenAI Responses API's
``response.output`` items, so they run with no network access and no API
key. See backend/model_router.py -- every OpenAI-native shape is built and
consumed only inside this class.
"""

from types import SimpleNamespace

import pytest

from backend.model_router import ModelProviderError, OpenAIProvider


def _provider() -> OpenAIProvider:
    return OpenAIProvider()


def _function_call(name="projects.list", arguments="{}", call_id="call-1"):
    return SimpleNamespace(type="function_call", name=name, arguments=arguments, call_id=call_id)


def test_parses_a_valid_function_call_into_a_tool_request():
    response = SimpleNamespace(output=[_function_call(call_id="call-1")], output_text="")

    turn = _provider()._parse_tool_response(response, input_items=[], instructions="x")

    assert turn.kind == "tool_calls"
    assert len(turn.tool_requests) == 1
    assert turn.tool_requests[0].call_id == "call-1"
    assert turn.tool_requests[0].name == "projects.list"


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
            _function_call(name="tasks.list", call_id="dup"),
            _function_call(name="memory.search", call_id="dup"),
        ],
        output_text="",
    )

    with pytest.raises(ModelProviderError, match="duplicate"):
        _provider()._parse_tool_response(response, input_items=[], instructions="x")


def test_distinct_call_ids_in_the_same_turn_are_all_accepted():
    response = SimpleNamespace(
        output=[
            _function_call(name="tasks.list", call_id="a"),
            _function_call(name="memory.search", call_id="b"),
        ],
        output_text="",
    )

    turn = _provider()._parse_tool_response(response, input_items=[], instructions="x")

    assert {request.call_id for request in turn.tool_requests} == {"a", "b"}


def test_malformed_json_arguments_raise_model_provider_error():
    item = _function_call(arguments="{not valid json")
    response = SimpleNamespace(output=[item], output_text="")

    with pytest.raises(ModelProviderError, match="malformed"):
        _provider()._parse_tool_response(response, input_items=[], instructions="x")


def test_non_object_arguments_raise_model_provider_error():
    item = _function_call(arguments="[1, 2, 3]")
    response = SimpleNamespace(output=[item], output_text="")

    with pytest.raises(ModelProviderError, match="non-object"):
        _provider()._parse_tool_response(response, input_items=[], instructions="x")


def test_call_id_check_runs_before_argument_parsing():
    """A call missing its call_id is rejected even if its arguments are also
    malformed -- the ambiguous-matching problem is the one that matters."""
    item = SimpleNamespace(type="function_call", name="tool", arguments="{not json", call_id="")
    response = SimpleNamespace(output=[item], output_text="")

    with pytest.raises(ModelProviderError, match="call_id"):
        _provider()._parse_tool_response(response, input_items=[], instructions="x")
