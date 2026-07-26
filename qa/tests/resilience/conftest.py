from __future__ import annotations

# Re-exported pytest fixtures: `toxiproxy` (finalizer removes all toxics) and the
# session-scoped autouse no-leak guard. `vendor_admin` lives in qa/tests/conftest.py
# (shared with the e2e suite) and is inherited automatically from there.
from qa_helpers.toxiproxy import toxiproxy, toxiproxy_no_leak_guard  # noqa: F401
