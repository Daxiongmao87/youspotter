.PHONY: test lint format-check

test:
	pytest

lint:
	ruff check .

format-check:
	black --check .
	isort --check-only . || true

