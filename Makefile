.PHONY: setup smoke fetch-sample score seed serve test lint

setup:
	uv sync

smoke:
	uv run python scripts/smoke_test.py

fetch-sample:
	uv run python scripts/fetch_off_sample.py

score:
	uv run python scripts/score.py

seed:
	uv run python scripts/seed_off.py

serve:
	uv run uvicorn app.main:app --reload

test:
	uv run pytest

lint:
	uv run ruff check . && uv run ruff format --check .
