from __future__ import annotations

from pathlib import Path

from bridgecal.windows_scheduler import (
    _ps_single_quoted,
    build_register_task_script,
    build_remove_task_script,
)


def test_ps_single_quoted_escapes_single_quote() -> None:
    assert _ps_single_quoted("a'b") == "'a''b'"


def test_build_register_task_script_contains_expected_values(tmp_path: Path) -> None:
    runner_path = tmp_path / "scripts" / "run-bridgecal-daemon.ps1"
    config_path = tmp_path / "config.toml"

    script = build_register_task_script(
        runner_path=runner_path,
        config_path=config_path,
        interval_seconds=300,
        task_name="BridgeCal Test Task",
    )

    assert "BridgeCal Test Task" in script
    assert str(runner_path) in script
    assert str(config_path) in script
    assert "-RunLevel Highest" in script
    assert "-IntervalSeconds $intervalSeconds" in script


def test_build_remove_task_script_contains_unregister() -> None:
    script = build_remove_task_script("BridgeCal Test Task")

    assert "BridgeCal Test Task" in script
    assert "Unregister-ScheduledTask" in script
