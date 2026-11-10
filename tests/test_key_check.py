"""The API key check reports each failed step and keeps going (no network)."""

import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "check_key_privileges",
    Path(__file__).resolve().parent.parent / "scripts" / "check_key_privileges.py",
)
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)


def test_a_failing_step_is_reported_and_the_rest_still_run():
    def denied():
        raise PermissionError("action [cluster:monitor/inference] is unauthorized")

    ran = []
    results = check.run_checks(
        [("read an image (EIS)", denied), ("search by words", lambda: ran.append(1))]
    )
    assert results[0][0] == "read an image (EIS)" and "unauthorized" in results[0][1]
    assert results[1] == ("search by words", None) and ran == [1]


def test_every_step_has_a_hint_and_the_report_names_the_failure():
    names = [name for name, _ in check._checks()]
    assert all(name in check.HINTS for name in names)
    text = check.report([(names[0], "PermissionError: unauthorized"), (names[1], None)], "test key")
    assert "FAIL: PermissionError" in text and "monitor_inference" in text and "| PASS |" in text
