"""Tests for strict Continuous Builder blueprint parsing."""

import hashlib
import json
from dataclasses import FrozenInstanceError, replace

import pytest

from backend.continuous_builder.blueprint_parser import (
    BlueprintParseError,
    parse_blueprint,
)
from test_continuous_builder_blueprint import make_blueprint


def payload():
    return json.dumps(make_blueprint().to_dict(), ensure_ascii=False)


def test_parser_canonicalizes_utf8_and_binds_digest():
    parsed = parse_blueprint(payload())
    assert (
        parsed.canonical_json.encode("utf-8")
        == parsed.blueprint.canonical_bytes()
    )
    assert parsed.content_sha256 == hashlib.sha256(
        parsed.blueprint.canonical_bytes()
    ).hexdigest()
    assert parsed.signer_authenticated is False
    assert parsed.persisted is False


def test_parser_rejects_unknown_missing_duplicate_and_unsupported_schema():
    raw = make_blueprint().to_dict()
    raw["surprise"] = True
    with pytest.raises(BlueprintParseError, match="unknown"):
        parse_blueprint(json.dumps(raw))
    raw = make_blueprint().to_dict()
    del raw["goal"]
    with pytest.raises(BlueprintParseError, match="missing"):
        parse_blueprint(json.dumps(raw))
    duplicate = payload()[:-1] + ',"goal":"duplicate"}'
    with pytest.raises(BlueprintParseError, match="duplicate"):
        parse_blueprint(duplicate)
    raw = make_blueprint().to_dict()
    raw["schema_version"] = "99"
    with pytest.raises(BlueprintParseError, match="schema version"):
        parse_blueprint(json.dumps(raw))


def test_mutation_and_malformed_digest_fail_closed():
    parsed = parse_blueprint(payload())
    raw = make_blueprint().to_dict()
    raw["goal"] = "Mutated goal."
    with pytest.raises(BlueprintParseError, match="mutation"):
        parse_blueprint(json.dumps(raw), parsed.content_sha256)
    with pytest.raises(BlueprintParseError, match="malformed"):
        parse_blueprint(payload(), "not-a-digest")


def test_invalid_utf8_and_non_json_are_rejected():
    with pytest.raises(BlueprintParseError, match="UTF-8"):
        parse_blueprint(b"\xff")
    with pytest.raises(BlueprintParseError, match="valid JSON"):
        parse_blueprint("not json")


def test_parsed_result_is_immutable_and_rejects_forged_derived_state():
    parsed = parse_blueprint(payload())
    with pytest.raises(FrozenInstanceError):
        parsed.content_sha256 = "0" * 64
    with pytest.raises(BlueprintParseError, match="does not bind"):
        replace(parsed, content_sha256="0" * 64)
    with pytest.raises(BlueprintParseError, match="authority"):
        replace(parsed, signer_authenticated=True)
