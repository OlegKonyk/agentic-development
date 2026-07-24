"""Unit tests for the poller's label mapping and (number, label) dedupe."""

from __future__ import annotations

import json

from sdlc_watcher.poller import Poller


def make_runner(payloads: dict[str, list[dict]]):
    """Fake gh runner: serves canned JSON per --label, and records the calls."""
    calls: list[list[str]] = []

    def run(args: list[str]) -> str:
        calls.append(args)
        label = args[args.index("--label") + 1]
        return json.dumps(payloads.get(label, []))

    return run, calls


def issue(number: int, title: str, *labels: str) -> dict:
    return {
        "number": number,
        "title": title,
        "labels": [{"name": name} for name in labels],
        "url": f"https://github.com/acme/demo/issues/{number}",
    }


PAYLOADS = {
    "stage:spec": [issue(7, "Add due dates", "stage:spec")],
    "stage:dev": [issue(9, "Bulk delete", "stage:dev", "enhancement")],
    "qa-ready": [issue(12, "feat: bulk delete", "qa-ready")],
}


def test_label_mapping_to_phase_and_kind() -> None:
    run, calls = make_runner(PAYLOADS)
    poller = Poller("acme/demo", run=run)

    tickets = {t.key: t for t in poller.poll()}

    assert set(tickets) == {(7, "stage:spec"), (9, "stage:dev"), (12, "qa-ready")}
    assert tickets[(7, "stage:spec")].phase.name == "product"
    assert tickets[(7, "stage:spec")].kind == "issue"
    assert tickets[(9, "stage:dev")].phase.name == "dev"
    assert tickets[(12, "qa-ready")].phase.name == "qa"
    assert tickets[(12, "qa-ready")].kind == "pr"

    # issue labels queried via `gh issue list`, PR labels via `gh pr list`
    by_label = {args[args.index("--label") + 1]: args[0] for args in calls}
    assert by_label["stage:spec"] == "issue"
    assert by_label["qa-ready"] == "pr"


def test_dedupe_while_label_stays_applied() -> None:
    run, _ = make_runner(PAYLOADS)
    poller = Poller("acme/demo", run=run)

    first = poller.poll()
    second = poller.poll()

    assert len(first) == 3
    assert second == []  # same (number, label) pairs are in flight — never re-dispatched


def test_relabel_after_removal_dispatches_again() -> None:
    payloads = {"qa-ready": [issue(12, "feat: bulk delete", "qa-ready")]}
    run, _ = make_runner(payloads)
    poller = Poller("acme/demo", run=run)

    assert [t.key for t in poller.poll()] == [(12, "qa-ready")]

    payloads["qa-ready"] = []  # QA finished: label removed
    assert poller.poll() == []

    payloads["qa-ready"] = [issue(12, "feat: bulk delete", "qa-ready")]  # rework relabeled
    assert [t.key for t in poller.poll()] == [(12, "qa-ready")]


def test_label_advance_dispatches_next_phase_for_same_number() -> None:
    payloads = {"stage:spec": [issue(7, "Add due dates", "stage:spec")]}
    run, _ = make_runner(payloads)
    poller = Poller("acme/demo", run=run)

    assert [t.phase.name for t in poller.poll()] == ["product"]

    # spec done: label moved stage:spec -> stage:design
    payloads["stage:spec"] = []
    payloads["stage:design"] = [issue(7, "Add due dates", "stage:design")]
    assert [t.phase.name for t in poller.poll()] == ["design"]


def test_loose_label_match_is_filtered() -> None:
    # gh matched something, but the payload item does not actually carry the label
    payloads = {"stage:spec": [issue(8, "Mislabeled", "stage:design")]}
    run, _ = make_runner(payloads)
    poller = Poller("acme/demo", run=run)

    assert poller.poll() == []
