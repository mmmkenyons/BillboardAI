"""Sprint 7G deterministic finalization-harness verifier."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.finalization_specs import PYTHON_EXE, CommandSpec, FileBoundarySpec, SprintSpec, get_sprint_spec  # noqa: E402
from tools.finalize_sprint import (  # noqa: E402
    BOUNDARY_FAILURE,
    COMMAND_FAILURE,
    PASS,
    PHASE_PRE_STAGE,
    PHASE_STAGED,
    SUSPICIOUS_ARTIFACT,
    TEST_FAILURE,
    TIMEOUT,
    ArtifactScanReport,
    BoundaryReport,
    classify_git_boundary,
    run_command_gate,
    run_harness,
    scan_suspicious_root_artifacts,
)


class FakeGit:
    def __init__(self, status: str) -> None:
        head = "b" * 40
        self.outputs = {
            ("branch", "--show-current"): "master",
            ("rev-parse", "HEAD"): head,
            ("rev-parse", "origin/master"): head,
            ("status", "--short", "--untracked-files=all"): status,
        }

    def output(self, args):
        return self.outputs[tuple(args)]


def check(name: str, condition: bool, failures: list[str]) -> None:
    print(("PASS" if condition else "FAIL") + f" {name}")
    if not condition:
        failures.append(name)


def main() -> int:
    failures: list[str] = []
    harness_text = (ROOT / "tools" / "finalize_sprint.py").read_text(encoding="utf-8")
    spec_text = (ROOT / "tools" / "finalization_specs.py").read_text(encoding="utf-8")
    rules_text = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / ".clinerules").glob("*.md"))

    check("direct authoritative Python convention", PYTHON_EXE == r"D:\BillboardAI\bb_env\Scripts\python.exe" and PYTHON_EXE in spec_text, failures)
    check(
        "no Activate.ps1 dependency",
        "Activate.ps1" not in spec_text and "Set-ExecutionPolicy" not in spec_text and "Set-ExecutionPolicy" not in harness_text.replace('"Set-ExecutionPolicy",', ""),
        failures,
    )
    check("subprocess argv execution", "subprocess.run(argv" in harness_text and "list(command.argv)" in harness_text, failures)
    check("shell=False/default-safe execution", "shell=False" in harness_text and "shell=True" not in harness_text, failures)

    ok = run_command_gate(CommandSpec("ok", (sys.executable, "-c", "print('ok')"), "pytest", timeout_seconds=5), default_timeout=5)
    check("PASS classification", ok.classification == PASS and ok.exit_code == 0, failures)
    fail = run_command_gate(CommandSpec("fail", (sys.executable, "-c", "import sys; sys.exit(2)"), "pytest", timeout_seconds=5), default_timeout=5)
    check("TEST_FAILURE classification", fail.classification == TEST_FAILURE and fail.exit_code == 2, failures)
    missing = run_command_gate(CommandSpec("missing", ("definitely-not-real-7g",), "command", timeout_seconds=1), default_timeout=1)
    check("COMMAND_FAILURE classification", missing.classification == COMMAND_FAILURE, failures)
    timeout = run_command_gate(CommandSpec("timeout", (sys.executable, "-c", "import time; time.sleep(2)"), "pytest", timeout_seconds=0.1), default_timeout=0.1)
    check("TIMEOUT classification", timeout.classification == TIMEOUT, failures)

    spec = SprintSpec("X", expected_files=FileBoundarySpec(modified=("a.py",), added=("b.py",)))
    check("boundary detection", classify_git_boundary(spec, PHASE_STAGED, FakeGit("M  a.py\nA  b.py")).classification == PASS and classify_git_boundary(spec, PHASE_STAGED, FakeGit("M  a.py\nA  b.py\n?? extra.txt")).classification == BOUNDARY_FAILURE, failures)
    check("suspicious artifact detection", scan_suspicious_root_artifacts(untracked_paths=["Set-ExecutionPolicy Activate.ps1 output.txt"]).classification == SUSPICIOUS_ARTIFACT, failures)
    check("ignored log path", any(line.strip() == "output/" for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()), failures)
    check("pre-stage mode", classify_git_boundary(spec, PHASE_PRE_STAGE, FakeGit(" M a.py\n?? b.py")).classification == PASS, failures)
    check("staged mode", classify_git_boundary(spec, PHASE_STAGED, FakeGit("M  a.py\nA  b.py")).classification == PASS, failures)
    check("informational test-count policy", run_command_gate(CommandSpec("count", (sys.executable, "-c", "print('138 passed')"), "pytest", timeout_seconds=5), default_timeout=5).classification == PASS, failures)

    with tempfile.TemporaryDirectory(prefix="sprint7g_verify_") as tmp:
        import tools.finalize_sprint as finalize_sprint

        original_boundary = finalize_sprint.classify_git_boundary
        original_scan = finalize_sprint.scan_suspicious_root_artifacts
        try:
            finalize_sprint.classify_git_boundary = lambda _spec, _phase: BoundaryReport(PASS)  # type: ignore[assignment]
            finalize_sprint.scan_suspicious_root_artifacts = lambda *args, **kwargs: ArtifactScanReport(PASS)  # type: ignore[assignment]
            fake_spec = SprintSpec(
                "DOGFOOD",
                expected_files=FileBoundarySpec(),
                focused_tests=(CommandSpec("dogfood", (sys.executable, "-c", "print('dogfood pass')"), "pytest", timeout_seconds=5),),
            )
            before_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, shell=False).stdout.strip()
            summary = run_harness(fake_spec, PHASE_PRE_STAGE, Path(tmp) / "output" / "finalization_logs")
            after_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, shell=False).stdout.strip()
        finally:
            finalize_sprint.classify_git_boundary = original_boundary  # type: ignore[assignment]
            finalize_sprint.scan_suspicious_root_artifacts = original_scan  # type: ignore[assignment]
        check("no Git mutation", before_head == after_head and summary.result == PASS, failures)

    sprint7g = get_sprint_spec("7G")
    check("Sprint 7G spec exists", sprint7g.sprint_name == "7G" and sprint7g.sprint_verifier is not None, failures)
    check("clinerules protections", all(fragment in rules_text for fragment in ["Never activate bb_env", "Activate.ps1", "Set-ExecutionPolicy", "finalize_sprint.py", "TEST_FAILURE", "git clean"]), failures)

    total = 17
    passed = total - len(failures)
    print(f"Sprint 7G verifier: PASS {passed}/{total} FAIL {len(failures)}/{total}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
