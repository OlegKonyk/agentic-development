#!/usr/bin/env python3
"""One-command creation of the sdlc-orchestrator GitHub App via the manifest flow.

Starts a localhost callback server, opens the browser on a pre-filled GitHub
App-creation form (one click), exchanges the returned code for the App's
credentials, stores them via gh (SDLC_APP_CLIENT_ID variable +
SDLC_APP_PRIVATE_KEY secret), and opens the installation page (second click).

Stdlib only. Usage: python3 scripts/create_github_app.py
"""

from __future__ import annotations

import html
import json
import subprocess
import sys
import tempfile
import threading
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PORT = 8877


def gh(*args: str, input_: str | None = None) -> str:
    result = subprocess.run(["gh", *args], capture_output=True, text=True, input=input_, check=True)
    return result.stdout.strip()


def build_manifest(repo: str) -> dict:
    owner = repo.split("/")[0].lower()
    return {
        "name": f"sdlc-orchestrator-{owner}"[:34],
        "url": f"https://github.com/{repo}",
        "redirect_url": f"http://localhost:{PORT}/callback",
        "public": False,
        "default_permissions": {
            "contents": "write",
            "issues": "write",
            "pull_requests": "write",
            "statuses": "write",
            "checks": "write",
            "actions": "read",
            "metadata": "read",
        },
        "default_events": [],
        # Webhook must be declared but stays inactive — the pipeline is
        # Actions-triggered, not webhook-triggered.
        "hook_attributes": {"url": "https://example.com/unused", "active": False},
    }


def main() -> int:
    repo = gh("repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner")
    manifest = json.dumps(build_manifest(repo))
    done = threading.Event()
    outcome: dict = {}

    form_page = f"""<!doctype html><title>Create sdlc-orchestrator</title>
<body style="font-family: sans-serif; margin: 4rem auto; max-width: 32rem">
<h2>Create the sdlc-orchestrator GitHub App</h2>
<p>Review the permissions on the next page, then click <b>Create GitHub App</b>.</p>
<form action="https://github.com/settings/apps/new?state=sdlc" method="post">
<input type="hidden" name="manifest" value="{html.escape(manifest, quote=True)}">
<button type="submit" style="font-size:1.2rem;padding:.6rem 1.4rem">Continue to GitHub</button>
</form></body>"""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            url = urllib.parse.urlparse(self.path)
            if url.path == "/":
                self._page(200, form_page)
                return
            if url.path != "/callback":
                self._page(404, "not found")
                return
            code = urllib.parse.parse_qs(url.query).get("code", [""])[0]
            if not code:
                self._page(400, f"missing ?code — retry from http://localhost:{PORT}")
                return
            req = urllib.request.Request(
                f"https://api.github.com/app-manifests/{code}/conversions",
                method="POST",
                headers={"Accept": "application/vnd.github+json"},
            )
            with urllib.request.urlopen(req) as resp:
                outcome.update(json.loads(resp.read()))
            self._page(200, "<h2>App created ✔</h2>You can close this tab.")
            done.set()

        def _page(self, status: int, body: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *args: object) -> None:
            pass

    server = HTTPServer(("localhost", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    print(f"Open http://localhost:{PORT} — one click there, one click on GitHub.")
    webbrowser.open(f"http://localhost:{PORT}")

    if not done.wait(timeout=600):
        print("Timed out waiting for the browser flow.", file=sys.stderr)
        return 1
    server.shutdown()

    client_id, slug, pem = outcome["client_id"], outcome["slug"], outcome["pem"]
    with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as f:
        f.write(pem)
        pem_path = Path(f.name)
    try:
        gh("variable", "set", "SDLC_APP_CLIENT_ID", "--body", client_id)
        gh("secret", "set", "SDLC_APP_PRIVATE_KEY", input_=pem)
    finally:
        pem_path.unlink(missing_ok=True)

    install_url = f"https://github.com/apps/{slug}/installations/new"
    print(f"App '{slug}' created; credentials stored in the repo.")
    print(f"Last step: install it on {repo} → {install_url}")
    webbrowser.open(install_url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
