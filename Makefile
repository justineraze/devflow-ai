.PHONY: help test lint fix typecheck check coverage smoke

# Default target: a single yes/no answer for "is the repo green?"
help:
	@echo "make test       — run pytest (unit + e2e, smoke deselected) with coverage"
	@echo "make lint       — run ruff check on src/ + tests/"
	@echo "make typecheck  — run mypy on src/"
	@echo "make fix        — auto-fix ruff issues"
	@echo "make coverage   — open HTML coverage report"
	@echo "make smoke      — run smoke tests (real Claude API, costs money)"
	@echo "make check      — test + lint + typecheck, the canonical 'is it green?' command"

test:
	uv run pytest -q

lint:
	uv run ruff check src/ tests/

fix:
	uv run ruff check src/ tests/ --fix

typecheck:
	uv run mypy src/

coverage:
	uv run pytest -q --cov=src/devflow --cov-report=html --cov-fail-under=0
	@echo "→ open htmlcov/index.html"
	@command -v open >/dev/null 2>&1 && open htmlcov/index.html || true

smoke:
	uv run pytest -m smoke -o addopts="" tests/smoke -v

check: test lint typecheck
