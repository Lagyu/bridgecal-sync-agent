from __future__ import annotations

from bridgecal.commands.doctor import _classify_outlook_failure


def test_classify_outlook_server_execution_failed_as_prerequisite_issue() -> None:
    assert _classify_outlook_failure(RuntimeError("Server execution failed")) == 2


def test_classify_outlook_unknown_failure_as_runtime_issue() -> None:
    assert _classify_outlook_failure(RuntimeError("unexpected failure")) == 4
