from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from tools.finalization_specs import CommandSpec, FileBoundarySpec, SprintSpec
from tools.finalize_sprint import (
    BOUNDARY_FAILURE,
    COMMAND_FAILURE,
    INTERRUPTED,
    PASS,
    PHASE_PRE_STAGE,
    PHASE_STAGED,
    SUSPICIOUS_ARTIFACT,
    TEST_FAILURE,
    TIMEOUT,
    ArtifactScanReport,
    BoundaryReport,
    GitClient,
    classify_git_boundary,
    run_command_gate,
    run_harness,
    scan_suspicious_root_artifacts,
)


def _cmd(code: str) -> CommandSpec:
    return CommandSpec("gate", (sys.executable, "-c", code), "pytest", timeout_seconds=5)


def test_passing_command() -> None:
    result = run_command_gate(_cmd("print('137 passed')"), default_timeout=5)
    assert result.classification == PASS
    assert result.exit_code == 0
    assert "137 passed" in result.stdout


def test_pytest_or_verifier_failure_classifies_as_test_failure() -> None:
    result = run_command_gate(_cmd("import sys; print('failed'); sys.exit(1)"), default_timeout=5)
    assert result.classification == TEST_FAILURE
    assert result.exit_code == 1


def test_nonexistent_command_classifies_as_command_failure() -> None:
    result = run_command_gate(CommandSpec("missing", ("definitely-not-a-real-command-7g",), "command", timeout_seconds=1), default_timeout=1)
    assert result.classification == COMMAND_FAILURE
    assert result.exit_code is None


def test_timeout_classification() -> None:
    result = run_command_gate(CommandSpec("timeout", (sys.executable, "-c", "import time; time.sleep(2)"), "pytest", timeout_seconds=0.1), default_timeout=5)
    assert result.classification == TIMEOUT
    assert result.exit_code is None


def test_interrupted_process_classification(monkeypatch) -> None:
    def raise_interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(subprocess, "run", raise_interrupt)
    result = run_command_gate(_cmd("print('never')"), default_timeout=1)
    assert result.classification == INTERRUPTED


class FakeGit:
    def __init__(self, outputs: dict[tuple[str, ...], str]) -> None:
        self.outputs = outputs

    def output(self, args):
        return self.outputs[tuple(args)]


def _spec() -> SprintSpec:
    return SprintSpec(
        sprint_name="X",
        expected_files=FileBoundarySpec(modified=("a.py",), added=("b.py",)),
        focused_tests=(CommandSpec("ok", (sys.executable, "-c", "print('ok')"), "pytest", timeout_seconds=5),),
    )


def _git_status(status: str, branch: str = "master") -> FakeGit:
    head = "a" * 40
    return FakeGit(
        {
            ("branch", "--show-current"): branch,
            ("rev-parse", "HEAD"): head,
            ("rev-parse", "origin/master"): head,
            ("status", "--short", "--untracked-files=all"): status,
        }
    )


def test_clean_expected_git_boundary_pre_stage() -> None:
    report = classify_git_boundary(_spec(), PHASE_PRE_STAGE, _git_status(" M a.py\n?? b.py"))
    assert report.classification == PASS
    assert report.expected_modified == ["a.py"]
    assert report.expected_added == ["b.py"]


def test_unexpected_modified_file_boundary_failure() -> None:
    report = classify_git_boundary(_spec(), PHASE_PRE_STAGE, _git_status(" M a.py\n M surprise.py\n?? b.py"))
    assert report.classification == BOUNDARY_FAILURE
    assert "surprise.py" in report.unexpected_modified


def test_unexpected_untracked_file_boundary_failure() -> None:
    report = classify_git_boundary(_spec(), PHASE_STAGED, _git_status("M  a.py\nA  b.py\n?? surprise.txt"))
    assert report.classification == BOUNDARY_FAILURE
    assert "surprise.txt" in report.unexpected_untracked


def test_suspicious_activate_artifact() -> None:
    report = scan_suspicious_root_artifacts(untracked_paths=["Set-ExecutionPolicy Activate.ps1 junk.txt"])
    assert report.classification == SUSPICIOUS_ARTIFACT
    assert report.suspicious_paths == ["Set-ExecutionPolicy Activate.ps1 junk.txt"]


def test_logs_created_only_under_configured_output_log_root(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("tools.finalize_sprint.classify_git_boundary", lambda spec, phase: BoundaryReport(PASS))
    monkeypatch.setattr("tools.finalize_sprint.scan_suspicious_root_artifacts", lambda *args, **kwargs: ArtifactScanReport(PASS))
    summary = run_harness(_spec(), PHASE_PRE_STAGE, tmp_path / "output" / "finalization_logs")
    log_dir = tmp_path / summary.log_dir
    assert (log_dir / "summary.json").exists()
    assert (log_dir / "summary.txt").exists()
    assert not (tmp_path / "summary.json").exists()


def test_no_root_log_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("tools.finalize_sprint.classify_git_boundary", lambda spec, phase: BoundaryReport(PASS))
    monkeypatch.setattr("tools.finalize_sprint.scan_suspicious_root_artifacts", lambda *args, **kwargs: ArtifactScanReport(PASS))
    run_harness(_spec(), PHASE_PRE_STAGE, tmp_path / "output" / "finalization_logs")
    root_files = {p.name for p in tmp_path.iterdir() if p.is_file()}
    assert "summary.json" not in root_files
    assert "summary.txt" not in root_files


def test_pre_stage_mode_uses_unstaged_boundary() -> None:
    report = classify_git_boundary(_spec(), PHASE_PRE_STAGE, _git_status(" M a.py\n?? b.py"))
    assert report.classification == PASS


def test_staged_mode_uses_cached_boundary() -> None:
    report = classify_git_boundary(_spec(), PHASE_STAGED, _git_status("M  a.py\nA  b.py"))
    assert report.classification == PASS


def test_count_change_with_exit_zero_remains_pass() -> None:
    result = run_command_gate(_cmd("print('138 passed in 1.0s')"), default_timeout=5)
    assert result.classification == PASS


def test_required_failure_stops_subsequent_required_gates(tmp_path, monkeypatch) -> None:
    spec = SprintSpec(
        sprint_name="X",
        expected_files=FileBoundarySpec(),
        focused_tests=(
            CommandSpec("fail", (sys.executable, "-c", "import sys; sys.exit(1)"), "pytest", timeout_seconds=5),
            CommandSpec("skip", (sys.executable, "-c", "print('should not run')"), "pytest", timeout_seconds=5),
        ),
    )
    monkeypatch.setattr("tools.finalize_sprint.classify_git_boundary", lambda spec, phase: BoundaryReport(PASS))
    monkeypatch.setattr("tools.finalize_sprint.scan_suspicious_root_artifacts", lambda *args, **kwargs: ArtifactScanReport(PASS))
    summary = run_harness(spec, PHASE_PRE_STAGE, tmp_path / "logs")
    assert summary.result == TEST_FAILURE
    assert [gate["gate_name"] for gate in summary.gates] == ["fail"]


def test_report_serialization_deserialization(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("tools.finalize_sprint.classify_git_boundary", lambda spec, phase: BoundaryReport(PASS))
    monkeypatch.setattr("tools.finalize_sprint.scan_suspicious_root_artifacts", lambda *args, **kwargs: ArtifactScanReport(PASS))
    summary = run_harness(_spec(), PHASE_PRE_STAGE, tmp_path / "logs")
    data = json.loads((tmp_path / summary.log_dir / "summary.json").read_text(encoding="utf-8"))
    assert data["result"] == PASS
    assert data["gates"][0]["classification"] == PASS


def test_git_client_uses_argv_and_shell_false(monkeypatch, tmp_path) -> None:
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="master\n", stderr="")

    git = GitClient(tmp_path, runner=fake_run)
    assert git.output(["branch", "--show-current"]) == "master"
    assert calls[0][0] == ["git", "branch", "--show-current"]
    assert calls[0][1]["shell"] is False


def test_git_client_preserves_leading_status_spaces(tmp_path) -> None:
    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, stdout=" M a.py\n", stderr="")

    git = GitClient(tmp_path, runner=fake_run)
    assert git.output(["status", "--short"]) == " M a.py"
