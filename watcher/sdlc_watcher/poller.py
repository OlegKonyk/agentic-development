"""Poll GitHub for open issues/PRs carrying phase labels, via the gh CLI.

The watcher's poll loop is the SDK-side equivalent of the CI `labeled` triggers:
each (number, label) pair fires at most once while the label stays applied, and
re-applying a label after it was removed is the retry mechanism — exactly the
semantics of the label-guarded workflows in docs/sdlc.md.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Iterable

from .models import PHASES, PhaseSpec, Ticket

# Runs `gh <args>` and returns stdout; injectable for tests.
GhRunner = Callable[[list[str]], str]

_LIST_FIELDS = "number,title,labels,url"


def run_gh(args: list[str]) -> str:
    proc = subprocess.run(["gh", *args], capture_output=True, text=True, check=True)
    return proc.stdout


class Poller:
    """Yields each labeled ticket once per label application.

    Dedupe is by (number, label): while a ticket keeps its phase label it is
    considered in flight and is not re-dispatched. When the label disappears
    from the listing (phase done, label moved on), the pair is forgotten, so a
    later re-application of the same label dispatches again.
    """

    def __init__(
        self,
        repo: str,
        phases: Iterable[PhaseSpec] = PHASES,
        run: GhRunner = run_gh,
    ) -> None:
        self.repo = repo
        self.phases = tuple(phases)
        self._run = run
        self._in_flight: set[tuple[int, str]] = set()

    def poll(self) -> list[Ticket]:
        """Return tickets not yet dispatched for their current label."""
        current = self.list_labeled()
        current_keys = {t.key for t in current}
        self._in_flight &= current_keys  # forget pairs whose label was removed
        fresh = [t for t in current if t.key not in self._in_flight]
        self._in_flight |= {t.key for t in fresh}
        return fresh

    def list_labeled(self) -> list[Ticket]:
        """List all open issues/PRs currently carrying a watched phase label."""
        tickets: list[Ticket] = []
        for phase in self.phases:
            subcommand = "issue" if phase.kind == "issue" else "pr"
            out = self._run(
                [
                    subcommand,
                    "list",
                    "--repo",
                    self.repo,
                    "--state",
                    "open",
                    "--label",
                    phase.label,
                    "--json",
                    _LIST_FIELDS,
                ]
            )
            for item in json.loads(out):
                names = {lbl["name"] for lbl in item.get("labels", [])}
                if phase.label not in names:
                    continue  # guard against loose server-side label matching
                tickets.append(
                    Ticket(
                        number=item["number"],
                        kind=phase.kind,
                        title=item.get("title", ""),
                        label=phase.label,
                        url=item.get("url", ""),
                    )
                )
        return tickets
