"""Deterministic sprint validation/finalization harness.

The harness intentionally performs no commit or push.  It verifies Git boundary
state, scans for suspicious root artifacts, runs declarative validation gates via
``subprocess`` argv lists, and writes machine/human reports below ignored output
logs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.finalization_specs import CommandSpec, FileBoundarySpec, SprintSpec, get_sprint_spec, list_sprints  # noqa: E402


PASS = "PASS"
TEST_FAILURE = "TEST_FAILURE"
COMMAND_FAILURE = "COMMAND_FAILURE"
TIMEOUT = "TIMEOUT"
INTERRUPTED = "INTERRUPTED"
BOUNDARY_FAILURE = "BOUNDARY_FAILURE"
SUSPICIOUS_ARTIFACT = "SUSPICIOUS_ARTIFACT"

PHASE_PRE_STAGE = "pre-stage"
PHASE_STAGED = "staged"

SUSPICIOUS_ROOT_PATTERNS = (
    "ExecutionPolicy",
    "Activate.ps1",
    "status --short",
    "pytest ",
    "pytest-",
    "pytest_",
    "PowerShell",
    "pwsh",
    "cmd.exe",
    "Set-ExecutionPolicy",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class CommandResult:
    gate_name: str
    argv: list[str]
    command_type: str
    started_at: str
    completed_at: str
    duration_seconds: float
    exit_code: int | None
    classification: str
    stdout: str = ""
    stderr: str = ""


@dataclass
class BoundaryReport:
    classification: str
    expected_modified: list[str] = field(default_factory=list)
    expected_added: list[str] = field(default_factory=list)
    unexpected_modified: list[str] = field(default_factory=list)
    unexpected_untracked: list[str] = field(default_factory=list)
    missing_expected: list[str] = field(default_factory=list)
    staged: list[dict[str, str]] = field(default_factory=list)
    unstaged: list[dict[str, str]] = field(default_factory=list)
    untracked: list[str] = field(default_factory=list)
    branch: str = ""
    head: str = ""
    origin_master: str = ""
    messages: list[str] = field(default_factory=list)


@dataclass
class ArtifactScanReport:
    classification: str
    suspicious_paths: list[str] = field(default_factory=list)


@dataclass
class HarnessSummary:
    sprint: str
    phase: str
    started_at: str
    completed_at: str
    duration: float
    result: str
    git_state: dict
    artifact_scan: dict
    gates: list[dict]
    log_dir: str


class GitClient:
    """Small argv-only Git helper."""

    def __init__(self, repo_root: Path = ROOT, runner: Callable[..., subprocess.CompletedProcess[str]] | None = None) -> None:
        self.repo_root = repo_root
        self._runner = runner or subprocess.run

    def run(self, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return self._runner(["git", *args], cwd=self.repo_root, capture_output=True, text=True, shell=False)

    def output(self, args: Sequence[str]) -> str:
        result = self.run(args)
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout or f"git {' '.join(args)} failed")
        return result.stdout.rstrip("\r\n")


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/")


def parse_name_status(text: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            parts = line.split(maxsplit=1)
        if len(parts) >= 2:
            entries.append({"status": parts[0], "path": _normalize_path(parts[-1])})
    return entries


def parse_short_status(text: str) -> tuple[list[dict[str, str]], list[dict[str, str]], list[str]]:
    staged: list[dict[str, str]] = []
    unstaged: list[dict[str, str]] = []
    untracked: list[str] = []
    for line in text.splitlines():
        if not line:
            continue
        code = line[:2]
        path = _normalize_path(line[3:].strip()) if len(line) > 3 else ""
        if code == "??":
            untracked.append(path)
            continue
        if code[0] != " ":
            staged.append({"status": code[0], "path": path})
        if code[1] != " ":
            unstaged.append({"status": code[1], "path": path})
    return staged, unstaged, untracked


def classify_git_boundary(spec: SprintSpec, phase: str, git: GitClient | None = None) -> BoundaryReport:
    git = git or GitClient()
    boundary = spec.expected_files
    report = BoundaryReport(
        classification=PASS,
        expected_modified=list(boundary.modified),
        expected_added=list(boundary.added),
    )
    try:
        report.branch = git.output(["branch", "--show-current"])
        report.head = git.output(["rev-parse", "HEAD"])
        report.origin_master = git.output(["rev-parse", "origin/master"])
        short = git.output(["status", "--short", "--untracked-files=all"])
        report.staged, report.unstaged, report.untracked = parse_short_status(short)
    except Exception as exc:  # noqa: BLE001 - boundary report must preserve infra failures as boundary failures.
        report.classification = BOUNDARY_FAILURE
        report.messages.append(str(exc))
        return report

    if report.branch != spec.expected_branch:
        report.messages.append(f"Expected branch {spec.expected_branch}, got {report.branch}.")
    if report.head != report.origin_master:
        report.messages.append("HEAD differs from origin/master.")

    expected_status = {path: "M" for path in boundary.modified}
    expected_status.update({path: "A" for path in boundary.added})

    if phase == PHASE_PRE_STAGE:
        entries = list(report.unstaged)
        if report.staged and not boundary.allow_staged_in_pre_stage:
            report.messages.append("Pre-stage phase does not allow staged files.")
            report.unexpected_modified.extend(entry["path"] for entry in report.staged)
        actual = {entry["path"]: entry["status"] for entry in entries}
        allowed_untracked = set(boundary.allow_untracked)
        report.unexpected_untracked.extend(path for path in report.untracked if path not in expected_status and path not in allowed_untracked)
        for path, status in actual.items():
            if path not in expected_status or expected_status[path] != status:
                report.unexpected_modified.append(path)
        for path in expected_status:
            if path not in actual and path not in report.untracked:
                report.missing_expected.append(path)
    elif phase == PHASE_STAGED:
        actual = {entry["path"]: entry["status"] for entry in report.staged}
        for path, status in actual.items():
            if path not in expected_status or expected_status[path] != status:
                report.unexpected_modified.append(path)
        for path in expected_status:
            if actual.get(path) != expected_status[path]:
                report.missing_expected.append(path)
        report.unexpected_modified.extend(entry["path"] for entry in report.unstaged)
        report.unexpected_untracked.extend(path for path in report.untracked if path not in boundary.allow_untracked)
    else:
        report.messages.append(f"Unknown phase: {phase}")

    if report.messages or report.unexpected_modified or report.unexpected_untracked or report.missing_expected:
        report.classification = BOUNDARY_FAILURE
    return report


def scan_suspicious_root_artifacts(repo_root: Path = ROOT, untracked_paths: Iterable[str] | None = None) -> ArtifactScanReport:
    if untracked_paths is None:
        git = GitClient(repo_root)
        try:
            _, _, untracked = parse_short_status(git.output(["status", "--short", "--untracked-files=all"]))
        except Exception:
            untracked = []
    else:
        untracked = [_normalize_path(path) for path in untracked_paths]

    suspicious: list[str] = []
    for path in untracked:
        if "/" in path:
            continue
        if any(fragment.lower() in path.lower() for fragment in SUSPICIOUS_ROOT_PATTERNS):
            suspicious.append(path)
    return ArtifactScanReport(classification=SUSPICIOUS_ARTIFACT if suspicious else PASS, suspicious_paths=sorted(suspicious))


def classify_nonzero(command_type: str) -> str:
    if command_type in {"pytest", "verifier"}:
        return TEST_FAILURE
    return COMMAND_FAILURE


def run_command_gate(command: CommandSpec, cwd: Path = ROOT, default_timeout: float = 900.0) -> CommandResult:
    started_wall = time.monotonic()
    started_at = utc_now()
    timeout = command.timeout_seconds if command.timeout_seconds is not None else default_timeout
    argv = list(command.argv)
    try:
        completed = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, shell=False)
        classification = PASS if completed.returncode == 0 else classify_nonzero(command.command_type)
        exit_code: int | None = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        classification = TIMEOUT
        exit_code = None
        stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode(errors="replace")
        stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode(errors="replace")
    except KeyboardInterrupt:
        classification = INTERRUPTED
        exit_code = None
        stdout = ""
        stderr = "Interrupted by KeyboardInterrupt."
    except BaseException as exc:  # noqa: BLE001 - command launch failures must be captured, not raised.
        classification = COMMAND_FAILURE
        exit_code = None
        stdout = ""
        stderr = f"{type(exc).__name__}: {exc}"
    completed_at = utc_now()
    return CommandResult(
        gate_name=command.name,
        argv=argv,
        command_type=command.command_type,
        started_at=started_at,
        completed_at=completed_at,
        duration_seconds=round(time.monotonic() - started_wall, 3),
        exit_code=exit_code,
        classification=classification,
        stdout=stdout,
        stderr=stderr,
    )


def ensure_output_ignored(repo_root: Path = ROOT) -> bool:
    gitignore = repo_root / ".gitignore"
    if not gitignore.exists():
        return False
    return any(line.strip().rstrip("/") == "output" for line in gitignore.read_text(encoding="utf-8").splitlines())


def make_log_dir(log_root: Path, sprint: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = log_root / sprint / stamp
    candidate = base
    index = 1
    while candidate.exists():
        index += 1
        candidate = log_root / sprint / f"{stamp}_{index:02d}"
    candidate.mkdir(parents=True, exist_ok=False)
    return candidate


def write_gate_logs(log_dir: Path, gates: Sequence[CommandResult]) -> None:
    for index, gate in enumerate(gates, start=1):
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", gate.gate_name).strip("_").lower() or "gate"
        prefix = f"{index:02d}_{safe_name}"
        (log_dir / f"{prefix}.stdout.txt").write_text(gate.stdout, encoding="utf-8")
        (log_dir / f"{prefix}.stderr.txt").write_text(gate.stderr, encoding="utf-8")


def overall_result(boundary: BoundaryReport, artifact: ArtifactScanReport, gates: Sequence[CommandResult]) -> str:
    if boundary.classification != PASS:
        return boundary.classification
    if artifact.classification != PASS:
        return artifact.classification
    for gate in gates:
        if gate.classification != PASS:
            return gate.classification
    return PASS


def render_text_summary(summary: HarnessSummary) -> str:
    lines = [f"SPRINT {summary.sprint} {summary.phase.upper()} VALIDATION", ""]
    lines.append(f"Git boundary............... {summary.git_state.get('classification')}")
    lines.append(f"Artifact scan.............. {summary.artifact_scan.get('classification')}")
    for gate in summary.gates:
        lines.append(f"{gate['gate_name'][:27]:.<28} {gate['classification']}")
    lines.extend(["", f"RESULT: {summary.result}", "", f"Report:", summary.log_dir])
    return "\n".join(lines) + "\n"


def run_harness(spec: SprintSpec, phase: str, log_root: Path, dry_run: bool = False, timeout_override: float | None = None) -> HarnessSummary:
    started_wall = time.monotonic()
    started_at = utc_now()
    log_dir = make_log_dir(log_root, spec.sprint_name)

    boundary = classify_git_boundary(spec, phase)
    artifact = scan_suspicious_root_artifacts(ROOT, boundary.untracked)
    gates: list[CommandResult] = []

    if boundary.classification == PASS and artifact.classification == PASS:
        for gate in spec.validation_gates():
            effective_gate = gate
            if timeout_override is not None:
                effective_gate = CommandSpec(
                    name=gate.name,
                    argv=gate.argv,
                    command_type=gate.command_type,
                    timeout_seconds=timeout_override,
                    required=gate.required,
                    retry_on_command_failure=gate.retry_on_command_failure,
                )
            if dry_run:
                gates.append(
                    CommandResult(
                        gate_name=effective_gate.name,
                        argv=list(effective_gate.argv),
                        command_type=effective_gate.command_type,
                        started_at=utc_now(),
                        completed_at=utc_now(),
                        duration_seconds=0.0,
                        exit_code=0,
                        classification=PASS,
                        stdout="DRY RUN: command not executed.",
                        stderr="",
                    )
                )
                continue
            result = run_command_gate(effective_gate, default_timeout=spec.default_timeout_seconds)
            gates.append(result)
            if result.classification == COMMAND_FAILURE and gate.retry_on_command_failure:
                retry = run_command_gate(effective_gate, default_timeout=spec.default_timeout_seconds)
                gates.append(retry)
                result = retry
            if gate.required and result.classification != PASS:
                break

    completed_at = utc_now()
    result_text = overall_result(boundary, artifact, gates)
    try:
        display_log_dir = str(log_dir.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        display_log_dir = str(log_dir)

    summary = HarnessSummary(
        sprint=spec.sprint_name,
        phase=phase,
        started_at=started_at,
        completed_at=completed_at,
        duration=round(time.monotonic() - started_wall, 3),
        result=result_text,
        git_state=asdict(boundary),
        artifact_scan=asdict(artifact),
        gates=[asdict(gate) for gate in gates],
        log_dir=display_log_dir,
    )
    write_gate_logs(log_dir, gates)
    (log_dir / "summary.json").write_text(json.dumps(asdict(summary), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    text = render_text_summary(summary)
    (log_dir / "summary.txt").write_text(text, encoding="utf-8")
    print(text, end="")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run deterministic sprint validation without commit/push.")
    parser.add_argument("--sprint", help="Sprint spec name, e.g. 7G")
    parser.add_argument("--phase", choices=(PHASE_PRE_STAGE, PHASE_STAGED), default=PHASE_PRE_STAGE)
    parser.add_argument("--list", action="store_true", help="List available sprint specs and exit.")
    parser.add_argument("--dry-run", action="store_true", help="Validate orchestration and log writing without executing gates.")
    parser.add_argument("--log-root", default=str(ROOT / "output" / "finalization_logs"), help="Directory for finalization logs.")
    parser.add_argument("--timeout", type=float, help="Override timeout for each validation gate.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list:
        for name in list_sprints():
            print(name)
        return 0
    if not args.sprint:
        print("--sprint is required unless --list is used", file=sys.stderr)
        return 2
    try:
        spec = get_sprint_spec(args.sprint)
    except KeyError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not ensure_output_ignored(ROOT):
        print("output/ is not ignored by Git; refusing to write finalization logs.", file=sys.stderr)
        return 1
    summary = run_harness(spec, args.phase, Path(args.log_root), dry_run=args.dry_run, timeout_override=args.timeout)
    return 0 if summary.result == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
