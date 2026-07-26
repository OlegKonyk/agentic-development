"""Schemathesis v4 contract suite, run directly against the API origin.

Every generated case carries a real bearer obtained via login. The token is
minted fresh per schema operation so a fuzzed /api/auth/logout or
/api/testing/reset only revokes its own session, never a neighbour's.
Unauthenticated 401 is a documented response, so it is never a failure here.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import httpx
import pytest
import schemathesis
from hypothesis import HealthCheck, settings
from qa_helpers import ApiClient, alice_credentials
from schemathesis.specs.openapi.checks import negative_data_rejection, positive_data_acceptance

API_URL = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")

schema = schemathesis.openapi.from_url(f"{API_URL}/openapi.json")


@pytest.fixture
def bearer_headers(api_url: str) -> Iterator[dict[str, str]]:
    with ApiClient(api_url) as client:
        client.login(*alice_credentials())
        yield {"Authorization": f"Bearer {client.token}"}


# derandomize gives a fixed generation order — deterministic in CI by construction.
@schema.parametrize()
@settings(
    max_examples=25,
    derandomize=True,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_api_contract(case: schemathesis.Case, bearer_headers: dict[str, str]) -> None:
    # Two checks are excluded by design:
    # - positive_data_acceptance: due_at-must-be-future and webhook HMAC rules
    #   cannot be expressed in JSON Schema, so schema-valid requests may
    #   legitimately get 4xx.
    # - negative_data_rejection: FastAPI ignores unknown query params/headers
    #   (standard REST leniency), which this check counts as acceptance.
    # Schema conformance, documented statuses, and no-5xx still apply everywhere.
    case.call_and_validate(
        headers=bearer_headers,
        excluded_checks=[positive_data_acceptance, negative_data_rejection],
    )


def test_list_tasks_pagination_is_documented(api_url: str) -> None:
    spec = httpx.get(f"{api_url}/openapi.json", timeout=10.0).json()
    params = {p["name"]: p for p in spec["paths"]["/api/tasks"]["get"]["parameters"]}

    limit_schema = params["limit"]["schema"]
    assert limit_schema["type"] == "integer"
    assert limit_schema["default"] == 20
    assert limit_schema["minimum"] == 1
    assert limit_schema["maximum"] == 100
    assert "null" not in limit_schema.get("type", [])

    offset_schema = params["offset"]["schema"]
    assert offset_schema["type"] == "integer"
    assert offset_schema["default"] == 0
    assert offset_schema["minimum"] == 0
    assert offset_schema["maximum"] == 2147483647
    assert "null" not in offset_schema.get("type", [])

    page_schema = spec["paths"]["/api/tasks"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    ref = page_schema["$ref"].split("/")[-1]
    task_page = spec["components"]["schemas"][ref]
    assert set(task_page["required"]) == {"items", "total", "limit", "offset"}


def test_reminder_health_operation_is_documented_and_401s_unauthenticated(api_url: str) -> None:
    spec = httpx.get(f"{api_url}/openapi.json", timeout=10.0).json()
    assert "/api/reminders/health" in spec["paths"]
    assert "get" in spec["paths"]["/api/reminders/health"]

    resp = httpx.get(f"{api_url}/api/reminders/health", timeout=10.0)
    assert resp.status_code == 401
