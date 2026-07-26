.PHONY: install lint test stack-up stack-down gateway-dev seed e2e contract qa-local clean

install:
	uv sync --all-packages
	cd gateway && npm ci

lint:
	uv run ruff check .
	uv run ruff format --check .
	python3 scripts/state_lint.py

test:
	uv run pytest apps/api apps/web -q

stack-up:
	docker compose up -d --wait --wait-timeout 120

stack-down:
	docker compose down -v

gateway-dev:
	cd gateway && npx wrangler dev --port 8787 --var RATE_LIMIT:600

seed:
	uv run python -c "from qa_helpers.client import ApiClient; c = ApiClient(); c.reset(); c.seed()"

e2e:
	uv run pytest qa/tests/e2e -q --base-url http://localhost:8787

contract:
	uv run pytest qa/tests/contract -q

# Run the QA agent locally against a running stack (mirrors phase-qa tier 2)
qa-local:
	mkdir -p context agent-out agent-artifacts
	scripts/run_agent.sh qa "/qa:qa-run context"

clean:
	rm -rf reports test-results agent-out agent-artifacts context data
