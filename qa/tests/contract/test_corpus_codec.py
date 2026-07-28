"""Codec unit coverage — no HTTP, no live schema."""

from __future__ import annotations

import base64
from types import SimpleNamespace

from qa_helpers.contract_corpus import (
    canonical_json,
    case_to_entry,
    schema_projection,
)
from schemathesis.core import NotSet


def _case(**overrides: object) -> SimpleNamespace:
    defaults = {
        "operation": SimpleNamespace(method="post", path="/api/tasks"),
        "path_parameters": {},
        "query": {},
        "headers": {},
        "media_type": "application/json",
        "body": NotSet(),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_json_body_round_trips_surrogate_and_nul() -> None:
    entry = case_to_entry(_case(body={"email": "a\x00b\ud800"}), 0)
    assert entry["body"] == {"kind": "json", "value": {"email": "a\x00b\ud800"}}
    raw = canonical_json(entry)
    restored = __import__("json").loads(raw)
    assert restored["body"]["value"]["email"] == "a\x00b\ud800"


def test_bytes_body_encodes_as_base64() -> None:
    entry = case_to_entry(_case(body=b"\x00\x01\xff", media_type="application/octet-stream"), 0)
    assert entry["body"]["kind"] == "bytes"
    assert base64.b64decode(entry["body"]["b64"]) == b"\x00\x01\xff"


def test_text_body_kind_for_non_json_media_type() -> None:
    entry = case_to_entry(_case(body="plain text", media_type="text/plain"), 0)
    assert entry["body"] == {"kind": "text", "value": "plain text"}


def test_absent_body_kind() -> None:
    entry = case_to_entry(_case(body=NotSet()), 0)
    assert entry["body"] == {"kind": "absent"}


def test_schema_projection_ignores_annotation_only_edits() -> None:
    base = {
        "paths": {
            "/x": {
                "get": {
                    "summary": "original",
                    "description": "original",
                    "parameters": [],
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
        "components": {"schemas": {}},
    }
    edited = {
        "paths": {
            "/x": {
                "get": {
                    "summary": "changed",
                    "description": "changed too",
                    "parameters": [],
                    "responses": {"200": {"description": "still ok"}},
                }
            }
        },
        "components": {"schemas": {}},
    }
    assert schema_projection(base) == schema_projection(edited)


def test_schema_projection_reacts_to_new_parameter() -> None:
    base = {
        "paths": {"/x": {"get": {"parameters": [], "responses": {}}}},
        "components": {"schemas": {}},
    }
    with_param = {
        "paths": {
            "/x": {
                "get": {
                    "parameters": [{"name": "q", "in": "query", "schema": {"type": "string"}}],
                    "responses": {},
                }
            }
        },
        "components": {"schemas": {}},
    }
    assert schema_projection(base) != schema_projection(with_param)


def test_schema_projection_reacts_to_widened_bound() -> None:
    narrow = {
        "paths": {
            "/x": {
                "get": {
                    "parameters": [
                        {
                            "name": "limit",
                            "in": "query",
                            "schema": {"type": "integer", "maximum": 100},
                        }
                    ],
                    "responses": {},
                }
            }
        },
        "components": {"schemas": {}},
    }
    wide = {
        "paths": {
            "/x": {
                "get": {
                    "parameters": [
                        {
                            "name": "limit",
                            "in": "query",
                            "schema": {"type": "integer", "maximum": 1000},
                        }
                    ],
                    "responses": {},
                }
            }
        },
        "components": {"schemas": {}},
    }
    assert schema_projection(narrow) != schema_projection(wide)


def test_schema_projection_reacts_to_changed_component_schema() -> None:
    base = {"paths": {}, "components": {"schemas": {"Task": {"type": "object"}}}}
    changed = {"paths": {}, "components": {"schemas": {"Task": {"type": "string"}}}}
    assert schema_projection(base) != schema_projection(changed)


def test_canonical_json_stable_under_key_reordering() -> None:
    a = {"b": 1, "a": 2}
    b = {"a": 2, "b": 1}
    assert canonical_json(a) == canonical_json(b)
