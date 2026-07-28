"""Codec, digest, and CLI for the committed contract-tier corpus.

Not re-exported from `qa_helpers/__init__.py`: it imports schemathesis/hypothesis,
and the e2e/resilience/webhook suites must keep importing `qa_helpers` without them.

The gating contract tier replays this committed corpus (`corpus.json`) instead of
generating on the fly, so the verdict is a pure function of the commit: no PRNG,
no import-order sensitivity, nothing to monkeypatch. Generation only happens in
`--refresh`, run by a human, whose output is a reviewable diff.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CORPUS_PATH = Path(__file__).resolve().parents[1] / "tests" / "contract" / "corpus.json"
ANNOTATION_KEYS = frozenset(
    {"description", "summary", "title", "example", "examples", "operationId"}
)
MAX_EXAMPLES_PER_OPERATION = 25

_HTTP_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})
_CORPUS_VERSION = 1


def canonical_json(obj: Any) -> bytes:
    """Sorted, ASCII-escaped, compact — the byte-stable form used for digests
    and the on-disk corpus file. `ensure_ascii=True` is load-bearing: it is
    what lets a lone surrogate or a NUL byte survive a file round-trip as an
    escape rather than an encode error."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def _strip_annotations(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_annotations(v) for k, v in obj.items() if k not in ANNOTATION_KEYS}
    if isinstance(obj, list):
        return [_strip_annotations(v) for v in obj]
    return obj


def schema_projection(spec: dict[str, Any]) -> dict[str, Any]:
    """The generation-relevant slice of an OpenAPI document: per-operation
    parameters, request body schema, and documented response statuses, plus
    every component schema — annotation-only keys stripped throughout. Prose
    edits (descriptions, summaries, examples) do not change this; a new
    endpoint, a widened field, a new enum value, or a changed bound does."""
    operations: list[dict[str, Any]] = []
    for path, path_item in spec.get("paths", {}).items():
        for method, op in path_item.items():
            if method.lower() not in _HTTP_METHODS:
                continue
            parameters = sorted(
                (
                    {
                        "name": p["name"],
                        "in": p["in"],
                        "required": p.get("required", False),
                        "schema": _strip_annotations(p.get("schema", {})),
                    }
                    for p in op.get("parameters", [])
                ),
                key=lambda p: (p["in"], p["name"]),
            )
            request_body = None
            if "requestBody" in op:
                rb = op["requestBody"]
                request_body = {
                    "required": rb.get("required", False),
                    "content": {
                        media: _strip_annotations(body.get("schema", {}))
                        for media, body in rb.get("content", {}).items()
                    },
                }
            operations.append(
                {
                    "key": f"{method.upper()} {path}",
                    "parameters": parameters,
                    "requestBody": request_body,
                    "responses": sorted(op.get("responses", {}).keys()),
                }
            )
    operations.sort(key=lambda o: o["key"])
    return {
        "operations": operations,
        "components_schemas": _strip_annotations(spec.get("components", {}).get("schemas", {})),
    }


def schema_digest(spec: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(schema_projection(spec))).hexdigest()


@dataclass(frozen=True)
class Corpus:
    version: int
    generated_with: dict[str, Any]
    schema_digest: str
    operations: list[dict[str, Any]]

    def operation_keys(self) -> list[str]:
        return [op["key"] for op in self.operations]

    def cases(self, key: str) -> list[dict[str, Any]]:
        for op in self.operations:
            if op["key"] == key:
                return op["cases"]
        raise KeyError(key)

    def digest(self) -> str:
        return "sha256:" + hashlib.sha256(canonical_json(self.operations)).hexdigest()

    def dump(self) -> bytes:
        payload = {
            "version": self.version,
            "generated_with": self.generated_with,
            "schema_digest": self.schema_digest,
            "operations": self.operations,
        }
        return canonical_json(payload) + b"\n"


def load_corpus(path: Path = CORPUS_PATH) -> Corpus:
    raw = json.loads(path.read_text())
    return Corpus(
        version=raw["version"],
        generated_with=raw["generated_with"],
        schema_digest=raw["schema_digest"],
        operations=raw["operations"],
    )


def _entry_id(method: str, path: str, index: int) -> str:
    slug = path.strip("/").replace("/", "-").replace("{", "").replace("}", "")
    return f"{method.lower()}-{slug}-{index:03d}"


def _is_json_media_type(media_type: str) -> bool:
    return media_type.partition(";")[0].strip() == "application/json"


def _plain(value: Any) -> dict[str, Any]:
    return dict(value) if value else {}


def _encode_body(body: Any, media_type: str | None) -> dict[str, Any]:
    from schemathesis.core import NotSet

    if isinstance(body, NotSet):
        return {"kind": "absent"}
    if isinstance(body, bytes):
        return {"kind": "bytes", "b64": base64.b64encode(body).decode("ascii")}
    if isinstance(body, str) and not (media_type and _is_json_media_type(media_type)):
        return {"kind": "text", "value": body}
    return {"kind": "json", "value": body}


def _decode_body(entry: dict[str, Any]) -> Any:
    from schemathesis.core import NotSet

    body = entry["body"]
    kind = body["kind"]
    if kind == "absent":
        return NotSet()
    if kind == "bytes":
        return base64.b64decode(body["b64"])
    return body["value"]


def case_to_entry(case: Any, index: int) -> dict[str, Any]:
    op = case.operation
    return {
        "id": _entry_id(op.method, op.path, index),
        "path_parameters": _plain(case.path_parameters),
        "query": _plain(case.query),
        "headers": _plain(case.headers),
        "media_type": case.media_type,
        "body": _encode_body(case.body, case.media_type),
    }


def entry_to_case(schema: Any, path: str, method: str, entry: dict[str, Any]) -> Any:
    op = schema[path][method.upper()]
    from schemathesis.core import NotSet

    body = _decode_body(entry)
    kwargs: dict[str, Any] = {
        "path_parameters": dict(entry["path_parameters"]),
        "query": dict(entry["query"]),
        "headers": dict(entry["headers"]),
    }
    if not isinstance(body, NotSet):
        kwargs["body"] = body
        if entry.get("media_type"):
            kwargs["media_type"] = entry["media_type"]
    return op.Case(**kwargs)


def _entry_key(entry: dict[str, Any]) -> bytes:
    without_id = {k: v for k, v in entry.items() if k != "id"}
    return canonical_json(without_id)


def _collect_cases(op: Any, max_examples: int) -> list[Any]:
    from hypothesis import HealthCheck, Phase, given, settings

    collected: list[Any] = []

    @given(case=op.as_strategy())
    @settings(
        max_examples=max_examples,
        derandomize=True,
        deadline=None,
        database=None,
        phases=[Phase.generate],
        suppress_health_check=list(HealthCheck),
    )
    def _collect(case: Any) -> None:
        collected.append(case)

    _collect()
    return collected


def generate_cases(
    schema: Any, max_examples: int = MAX_EXAMPLES_PER_OPERATION
) -> list[dict[str, Any]]:
    """Refresh-only: collects up to `max_examples` deduplicated cases per
    operation. Imports hypothesis lazily so the gating path never needs it."""
    operations: list[dict[str, Any]] = []
    for path, path_item in sorted(schema.raw_schema.get("paths", {}).items()):
        for method in sorted(path_item):
            if method.lower() not in _HTTP_METHODS:
                continue
            op = schema[path][method.upper()]
            collected = _collect_cases(op, max_examples)

            entries = [case_to_entry(case, i) for i, case in enumerate(collected)]
            deduped: dict[bytes, dict[str, Any]] = {}
            for entry in entries:
                deduped[_entry_key(entry)] = entry
            ordered_keys = sorted(deduped)[:max_examples]
            final_entries = []
            for i, key in enumerate(ordered_keys):
                entry = dict(deduped[key])
                entry["id"] = _entry_id(method, path, i)
                # Fixed-point check: a serialisation gap must surface here, not in CI.
                case = entry_to_case(schema, path, method, entry)
                round_tripped = case_to_entry(case, i)
                assert round_tripped == entry, f"non-canonical round-trip for {entry['id']}"
                final_entries.append(entry)

            operations.append(
                {
                    "key": f"{method.upper()} {path}",
                    "path": path,
                    "method": method.upper(),
                    "cases": final_entries,
                }
            )
    operations.sort(key=lambda o: o["key"])
    return operations


def _load_live_schema(api_url: str) -> Any:
    import schemathesis

    return schemathesis.openapi.from_url(f"{api_url}/openapi.json")


def _cmd_refresh(api_url: str, path: Path) -> int:
    import schemathesis

    schema = _load_live_schema(api_url)
    operations = generate_cases(schema)
    corpus = Corpus(
        version=_CORPUS_VERSION,
        generated_with={
            "schemathesis": schemathesis.__version__,
            "hypothesis": __import__("hypothesis").__version__,
            "max_examples_per_operation": MAX_EXAMPLES_PER_OPERATION,
        },
        schema_digest=schema_digest(schema.raw_schema),
        operations=operations,
    )
    path.write_bytes(corpus.dump())
    print(f"wrote {path} ({len(operations)} operations, digest {corpus.schema_digest})")
    return 0


def _cmd_check(api_url: str, path: Path) -> int:
    import httpx

    live_spec = httpx.get(f"{api_url}/openapi.json", timeout=10.0).json()
    expected = schema_digest(live_spec)
    corpus = load_corpus(path)
    if corpus.schema_digest != expected:
        print(
            "CONTRACT CORPUS DRIFT — the live OpenAPI schema no longer matches the schema\n"
            f"{path} was generated from.\n"
            "Refresh it in this PR:  make stack-up && make contract-refresh\n"
            "then review the corpus.json diff and commit it.\n"
            f"expected {expected}  actual {corpus.schema_digest}"
        )
        return 1
    print("contract corpus is current")
    return 0


def _cmd_replay(api_url: str, path: Path, entry_id: str) -> int:
    from schemathesis.specs.openapi.checks import negative_data_rejection, positive_data_acceptance

    from qa_helpers import ApiClient, alice_credentials

    schema = _load_live_schema(api_url)
    corpus = load_corpus(path)
    for op in corpus.operations:
        for entry in op["cases"]:
            if entry["id"] == entry_id:
                case = entry_to_case(schema, op["path"], op["method"], entry)
                with ApiClient(api_url) as client:
                    client.login(*alice_credentials())
                    headers = {"Authorization": f"Bearer {client.token}"}
                    print(f"replaying {entry_id} ({op['key']})")
                    print(f"request: {entry}")
                    try:
                        response = case.call_and_validate(
                            headers=headers,
                            excluded_checks=[positive_data_acceptance, negative_data_rejection],
                        )
                    except AssertionError as exc:
                        print(f"VIOLATION: {exc}")
                        return 1
                    print(f"response: {response.status_code} — no violation")
                    return 0
    print(f"no entry {entry_id!r} in {path}")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-url",
        default=os.environ.get("API_URL", "http://localhost:8000"),
        help="Live API origin to fetch the schema from / replay against.",
    )
    parser.add_argument("--corpus", type=Path, default=CORPUS_PATH)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--refresh", action="store_true", help="Regenerate the committed corpus.")
    group.add_argument("--check", action="store_true", help="Verify the corpus is current.")
    group.add_argument("--replay", metavar="ENTRY_ID", help="Replay one corpus entry.")
    args = parser.parse_args(argv)

    api_url = args.api_url.rstrip("/")
    if args.refresh:
        return _cmd_refresh(api_url, args.corpus)
    if args.check:
        return _cmd_check(api_url, args.corpus)
    return _cmd_replay(api_url, args.corpus, args.replay)


if __name__ == "__main__":
    sys.exit(main())
