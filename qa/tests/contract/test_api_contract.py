"""Schemathesis v4 contract suite, run directly against the API origin."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
import schemathesis
from hypothesis import settings
from qa_helpers import ApiClient

API_URL = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")

schema = schemathesis.openapi.from_url(f"{API_URL}/openapi.json")


@pytest.fixture(scope="session", autouse=True)
def _clean_state() -> Iterator[None]:
    with ApiClient(api_url=API_URL) as client:
        client.reset()
        yield


# derandomize gives a fixed generation order — deterministic in CI by construction.
@schema.parametrize()
@settings(max_examples=25, derandomize=True, deadline=None)
def test_api_contract(case: schemathesis.Case) -> None:
    case.call_and_validate()
