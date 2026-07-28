from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

REPORTS_DIR = Path(__file__).resolve().parents[3] / "reports"


@pytest.fixture
def record_contract_failure(
    _contract_failures: list[dict[str, Any]],
) -> Callable[[str, dict[str, Any], BaseException], None]:
    def _record(operation_key: str, entry: dict[str, Any], error: BaseException) -> None:
        _contract_failures.append(
            {
                "entry_id": entry["id"],
                "operation": operation_key,
                "request": {
                    "path_parameters": entry["path_parameters"],
                    "query": entry["query"],
                    "headers": entry["headers"],
                    "media_type": entry["media_type"],
                    "body": entry["body"],
                },
                "error": str(error),
            }
        )

    return _record


@pytest.fixture(scope="session")
def _contract_failures() -> list[dict[str, Any]]:
    return []


@pytest.fixture(scope="session")
def _contract_sent() -> list[str]:
    return []


@pytest.fixture(scope="session", autouse=True)
def _contract_run_record(
    _contract_failures: list[dict[str, Any]], _contract_sent: list[str]
) -> Iterator[None]:
    yield
    from qa_helpers.contract_corpus import load_corpus

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    corpus = load_corpus()
    run = {
        "corpus_digest": corpus.digest(),
        "schema_digest": corpus.schema_digest,
        "case_count": sum(len(op["cases"]) for op in corpus.operations),
        "sent": list(_contract_sent),
    }
    (REPORTS_DIR / "contract-run.json").write_text(json.dumps(run, sort_keys=True, indent=2))
    (REPORTS_DIR / "contract-failures.json").write_text(
        json.dumps(_contract_failures, sort_keys=True, indent=2)
    )
