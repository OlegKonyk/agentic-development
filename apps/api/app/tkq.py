"""Taskiq broker + scheduler wiring.

Compose runs `taskiq worker app.tkq:broker` and `taskiq scheduler app.tkq:scheduler`
against this module; unit tests flip TASKIQ_BROKER=inmemory to run tasks inline.
"""

import os

import taskiq_fastapi
from taskiq import AsyncBroker, InMemoryBroker, TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_redis import ListQueueBroker


def _redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://localhost:6379/0")


def _make_broker() -> AsyncBroker:
    if os.environ.get("TASKIQ_BROKER") == "inmemory":
        return InMemoryBroker(await_inplace=True)
    return ListQueueBroker(url=_redis_url())


broker = _make_broker()

scheduler = TaskiqScheduler(broker=broker, sources=[LabelScheduleSource(broker)])

# Resolves the app lazily (at broker startup), so no circular import here.
taskiq_fastapi.init(broker, "app.main:app")

# Imported last so `taskiq worker/scheduler app.tkq:...` sees the registered
# tasks; jobs.py imports `broker` from this module, hence the tail import.
import app.jobs  # noqa: E402, F401
