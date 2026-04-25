.PHONY: help test lint fix check

# Default target: a single yes/no answer for "is the repo green?"
help:
	@echo "make test    — run pytest (unit + e2e, smoke deselected)"
	@echo "make lint    — run ruff check on src/ + tests/"
	@echo "make fix     — auto-fix ruff issues"
	@echo "make check   — test + lint, the canonical 'is it green?' command"

test:
	pytest -q

lint:
	ruff check src/ tests/

fix:
	ruff check src/ tests/ --fix

check: test lint
