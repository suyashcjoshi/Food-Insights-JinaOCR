.PHONY: setup probe smoke fetch-sample score serve test lint

setup:
	uv sync

probe:
	uv run python scripts/api_probe.py

smoke:
	uv run python scripts/smoke_test.py

fetch-sample:
	uv run python scripts/fetch_off_sample.py

score:
	uv run python scripts/score.py

serve:
	uv run uvicorn app.main:app --reload

test:
	uv run pytest

lint:
	uv run ruff check . && uv run ruff format --check .
