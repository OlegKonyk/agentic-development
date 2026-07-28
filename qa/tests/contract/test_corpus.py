"""Drift guard and corpus invariants — no live generation, so these tests are
themselves deterministic; they only need a running API to fetch the live schema."""

from __future__ import annotations

import os

import httpx
from qa_helpers.contract_corpus import (
    CORPUS_PATH,
    MAX_EXAMPLES_PER_OPERATION,
    entry_to_case,
    load_corpus,
    schema_digest,
)
from test_api_contract import schema

API_URL = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")

CORPUS = load_corpus()


def test_corpus_matches_live_schema() -> None:
    live_spec = httpx.get(f"{API_URL}/openapi.json", timeout=10.0).json()
    expected = schema_digest(live_spec)
    assert CORPUS.schema_digest == expected, (
        "CONTRACT CORPUS DRIFT — the live OpenAPI schema no longer matches the schema\n"
        f"{CORPUS_PATH} was generated from.\n"
        "Refresh it in this PR:  make stack-up && make contract-refresh\n"
        "then review the corpus.json diff and commit it.\n"
        f"expected {expected}  actual {CORPUS.schema_digest}"
    )


def test_corpus_covers_every_documented_operation() -> None:
    live_spec = httpx.get(f"{API_URL}/openapi.json", timeout=10.0).json()
    live_keys = {
        f"{method.upper()} {path}"
        for path, item in live_spec.get("paths", {}).items()
        for method in item
        if method.lower() in {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
    }
    assert set(CORPUS.operation_keys()) == live_keys


def test_corpus_is_canonical() -> None:
    assert CORPUS_PATH.read_bytes() == CORPUS.dump()


def test_corpus_case_budget() -> None:
    for op in CORPUS.operations:
        assert 1 <= len(op["cases"]) <= MAX_EXAMPLES_PER_OPERATION, op["key"]


def test_every_entry_reconstructs() -> None:
    for op in CORPUS.operations:
        for entry in op["cases"]:
            entry_to_case(schema, op["path"], op["method"], entry)
