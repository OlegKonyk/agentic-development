"""CLI entrypoint: the watch loop (poll → dispatch → sleep)."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from .models import PHASES
from .poller import Poller

log = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sdlc-watcher",
        description="Watch a repo's phase labels and dispatch Claude agent runs (SDK twin of CI).",
    )
    parser.add_argument("--repo", required=True, metavar="OWNER/NAME", help="GitHub repository")
    parser.add_argument(
        "--interval", type=float, default=60.0, metavar="SECONDS", help="poll interval (default 60)"
    )
    parser.add_argument(
        "--phase",
        choices=sorted(p.name for p in PHASES),
        default=None,
        help="watch only this phase",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="log what would be dispatched without running agents (default)",
    )
    mode.add_argument(
        "--execute",
        action="store_true",
        help="actually dispatch agent runs (turns dry-run off)",
    )
    return parser


async def amain(args: argparse.Namespace) -> int:
    # Imported here so poller-only usage (and tests) never needs the SDK installed.
    from .dispatcher import Dispatcher

    phases = tuple(p for p in PHASES if args.phase is None or p.name == args.phase)
    poller = Poller(args.repo, phases=phases)
    dispatcher = Dispatcher(repo=args.repo, repo_root=Path.cwd(), dry_run=not args.execute)
    log.info(
        "watching %s every %.0fs — phases: %s (mode: %s)",
        args.repo,
        args.interval,
        ", ".join(p.name for p in phases),
        "EXECUTE" if args.execute else "dry-run",
    )
    while True:
        try:
            tickets = await asyncio.to_thread(poller.poll)
        except Exception:
            log.exception("poll failed; retrying next interval")
            tickets = []
        for ticket in tickets:
            await dispatcher.dispatch(ticket)
        await asyncio.sleep(args.interval)


def cli() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        raise SystemExit(asyncio.run(amain(args)))
    except KeyboardInterrupt:
        raise SystemExit(130) from None


if __name__ == "__main__":
    cli()
