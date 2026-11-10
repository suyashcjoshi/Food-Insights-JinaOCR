.PHONY: setup smoke fetch-sample score seed serve test lint check-key

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

check-key:
	uv run python scripts/check_key_privileges.py

lint:
	uv run ruff check . && uv run ruff format --check .
