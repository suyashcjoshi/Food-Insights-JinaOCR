"""Check what the API key in .env can do, one app action at a time.

    uv run python scripts/check_key_privileges.py        # or: make check-key

Runs every Elasticsearch / EIS action the app makes (read a tiny image, create the indices, index, search by
words and by meaning, aggregate, update, log, delete) and prints PASS or FAIL for each, with the privilege
that usually explains a FAIL. Use it with a restricted key (see the README) to find what the key is missing.

It touches only the two configured indices (ES_INDEX, ES_LOG_INDEX), with one test document and one test log
entry that it deletes at the end. Costs one EIS call (a 32 px white image). Writes _notes/reports/key_privileges.md.
"""

from __future__ import annotations

import contextlib
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image

from app import eis, es
from app.images import to_data_url

REPORTS = ROOT / "_notes" / "reports"  # git-ignored local notes
LABEL_ID, LOG_ID = "keycheck-label", "keycheck-log"
DAY = datetime.now(UTC).strftime("%Y-%m-%d")

# (step, what a FAIL usually means)
HINTS = {
    "read an image (EIS)": "cluster privilege monitor_inference",
    "create the indices": "index privilege create_index (or view_index_metadata for the exists check)",
    "index a label": "index privilege index / write; a refresh error (unpromotable) means maintenance (writes use refresh=True)",
    "search by words": "index privilege read",
    "search by meaning": "index privilege read (and the embedding endpoint)",
    "aggregate (Library counts)": "index privilege read",
    "get and update a label": "index privilege read / write (an update refreshes too: maintenance)",
    "log an entry, sum the day": "index privilege write / read on the log index (and maintenance for the refresh)",
    "delete a log entry": "index privilege delete / write (and maintenance for the refresh)",
}


def _read_tiny_image() -> None:
    call = eis.read(to_data_url(Image.new("RGB", (32, 32), "white")))
    if not call.ok:
        raise RuntimeError(f"HTTP {call.status}: {call.raw[:120]}")


def _index_label() -> None:
    es.index_doc(
        {
            "id": LABEL_ID,
            "captured_at": datetime.now(UTC).isoformat(),
            "product_name": "key check",
            "plain_text": "key check peanuts",
            "nutrients": {},
            "allergen_mentions": [],
            "source": "keycheck",
        }
    )


def _log_and_sum() -> None:
    es.log_entry(
        {
            "id": LOG_ID,
            "label_id": LABEL_ID,
            "day": DAY,
            "eaten_at": datetime.now(UTC).isoformat(),
            "net_carbs_g": 1.0,
            "calories_kcal": 1,
        }
    )
    es.day_summary(DAY)


def _checks() -> list[tuple[str, Callable[[], object]]]:
    return [
        ("read an image (EIS)", _read_tiny_image),
        ("create the indices", lambda: (es.ensure_index(), es.ensure_log_index())),
        ("index a label", _index_label),
        ("search by words", lambda: es._search("peanuts")),
        ("search by meaning", lambda: es._search("peanuts", mode="meaning")),
        ("aggregate (Library counts)", lambda: es._aggregate("")),
        (
            "get and update a label",
            lambda: (
                es.get_doc(LABEL_ID),
                es.update_doc(LABEL_ID, {"product_name": "key check 2"}),
            ),
        ),
        ("log an entry, sum the day", _log_and_sum),
        ("delete a log entry", lambda: es.delete_log_entry(LOG_ID)),
    ]


def run_checks(checks: list[tuple[str, Callable[[], object]]]) -> list[tuple[str, str | None]]:
    """(step, None) when it worked, (step, error text) when it did not. A failure never stops the rest."""
    results: list[tuple[str, str | None]] = []
    for name, action in checks:
        try:
            action()
            results.append((name, None))
        except Exception as exc:  # noqa: BLE001  every failure is reported, none is raised
            results.append((name, f"{type(exc).__name__}: {str(exc)[:160]}".replace("\n", " ")))
    return results


def _cleanup() -> None:
    """Remove the test label (the log entry is removed by its own step). Never raises."""
    with contextlib.suppress(
        Exception
    ):  # a key without delete rights leaves one tiny test document
        es.client().delete(index=es.index_name(), id=LABEL_ID, refresh=True)


def _who() -> str:
    try:
        info = es.client().security.authenticate().body
        key = (info.get("api_key") or {}).get("name") or info.get("username")
        return f"{key} ({info.get('authentication_type')})"
    except Exception:  # noqa: BLE001
        return "unknown (could not read the key's details)"


def report(results: list[tuple[str, str | None]], who: str) -> str:
    lines = [
        "# API key privilege check",
        "",
        f"Key: {who}. Indices: `{es.index_name()}`, `{es.log_index_name()}`. Run: {datetime.now(UTC):%Y-%m-%d %H:%M} UTC",
        "",
        "| Step | Result | If it failed, check |",
        "|---|---|---|",
    ]
    for name, error in results:
        lines.append(
            f"| {name} | PASS | |"
            if error is None
            else f"| {name} | FAIL: {error} | {HINTS[name]} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    results = run_checks(_checks())
    _cleanup()
    who = _who()
    failed = [name for name, error in results if error]
    for name, error in results:
        print(
            f"{'PASS' if error is None else 'FAIL'}  {name}" + (f"  ->  {error}" if error else "")
        )
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "key_privileges.md").write_text(report(results, who))
    print(
        f"{len(results) - len(failed)}/{len(results)} steps passed for key {who}"
        f" -> _notes/reports/key_privileges.md"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
