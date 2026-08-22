"""Declarative sprint-finalization specifications.

The validation harness in :mod:`tools.finalize_sprint` consumes these specs so
future sprints can reuse the same deterministic orchestration without encoding
one-off command lists in Cline prompts.
"""

from __future__ import annotations

from dataclasses import dataclass, field


PYTHON_EXE = r"D:\BillboardAI\bb_env\Scripts\python.exe"


@dataclass(frozen=True)
class CommandSpec:
    """One validation command in a sprint spec."""

    name: str
    argv: tuple[str, ...]
    command_type: str = "verifier"
    timeout_seconds: float | None = None
    required: bool = True
    retry_on_command_failure: bool = False


@dataclass(frozen=True)
class FileBoundarySpec:
    """Expected Git boundary for a sprint."""

    modified: tuple[str, ...] = ()
    added: tuple[str, ...] = ()
    allow_staged_in_pre_stage: bool = False
    allow_untracked: tuple[str, ...] = ()

    @property
    def expected_files(self) -> tuple[str, ...]:
        return self.modified + self.added


@dataclass(frozen=True)
class SprintSpec:
    sprint_name: str
    expected_branch: str = "master"
    expected_files: FileBoundarySpec = field(default_factory=FileBoundarySpec)
    focused_tests: tuple[CommandSpec, ...] = ()
    sprint_verifier: CommandSpec | None = None
    regression_groups: tuple[CommandSpec, ...] = ()
    historical_verifiers: tuple[CommandSpec, ...] = ()
    full_pytest_required: bool = False
    default_timeout_seconds: float = 900.0

    def validation_gates(self) -> tuple[CommandSpec, ...]:
        gates: list[CommandSpec] = []
        gates.extend(self.focused_tests)
        if self.sprint_verifier is not None:
            gates.append(self.sprint_verifier)
        gates.extend(self.regression_groups)
        gates.extend(self.historical_verifiers)
        if self.full_pytest_required:
            gates.append(
                CommandSpec(
                    name="Full pytest",
                    argv=(PYTHON_EXE, "-m", "pytest", "-q"),
                    command_type="pytest",
                    timeout_seconds=max(self.default_timeout_seconds, 1800.0),
                )
            )
        return tuple(gates)


def _pytest(name: str, *paths: str, timeout_seconds: float | None = None) -> CommandSpec:
    return CommandSpec(
        name=name,
        argv=(PYTHON_EXE, "-m", "pytest", "-q", *paths),
        command_type="pytest",
        timeout_seconds=timeout_seconds,
    )


def _verifier(name: str, path: str, timeout_seconds: float | None = None) -> CommandSpec:
    return CommandSpec(
        name=name,
        argv=(PYTHON_EXE, path),
        command_type="verifier",
        timeout_seconds=timeout_seconds,
    )


SPRINT_SPECS: dict[str, SprintSpec] = {
    "7F": SprintSpec(
        sprint_name="7F",
        expected_files=FileBoundarySpec(
            modified=(
                "engine/renderer/renderer.py",
                "gui/controllers/batch_generation_controller.py",
                "gui/services/copy_quality.py",
            ),
            added=("tests/test_sprint7f_creative_quality.py", "tools/sprint7f_verify.py"),
        ),
        focused_tests=(
            _pytest("Batch controller", "tests/test_batch_generation_controller.py"),
            _pytest("Prospect + batch", "tests/test_prospect_generation.py", "tests/test_batch_generation_controller.py"),
            _pytest("Sprint 7F tests", "tests/test_sprint7f_creative_quality.py"),
        ),
        sprint_verifier=_verifier("Sprint 7F verifier", "tools/sprint7f_verify.py"),
        regression_groups=(
            _pytest(
                "Person/copy regressions",
                "tests/test_ad_concept.py",
                "tests/test_person_personalization.py",
                "tests/test_sprint6b_quality_gates.py",
                "tests/test_sprint6h_remediation.py",
            ),
            _pytest(
                "Campaign/export regressions",
                "tests/test_campaign_export.py",
                "tests/test_campaign_package.py",
                "tests/test_campaign_review.py",
                "tests/test_sprint5ad_campaign_assembly.py",
                "tests/test_sprint5w_campaign_run.py",
                "tests/test_sprint5y_smartlead_export.py",
            ),
        ),
        historical_verifiers=(
            _verifier("Sprint 7E verifier", "tools/sprint7e_verify.py"),
            _verifier("Sprint 7C verifier", "tools/sprint7c_verify.py"),
            _verifier("Sprint 7B verifier", "tools/sprint7b_verify.py"),
            _verifier("Sprint 7A verifier", "tools/sprint7a_verify.py"),
            _verifier("Sprint 6H verifier", "tools/sprint6h_verify.py"),
            _verifier("Sprint 6F verifier", "tools/sprint6f_verify.py"),
        ),
        full_pytest_required=True,
    ),
    "7G": SprintSpec(
        sprint_name="7G",
        expected_files=FileBoundarySpec(
            modified=(
                ".clinerules/00-billboardai-core.md",
                ".clinerules/20-testing-and-git.md",
                ".clinerules/30-cline-tool-safety.md",
            ),
            added=(
                "tests/test_finalize_sprint.py",
                "tools/finalization_specs.py",
                "tools/finalize_sprint.py",
                "tools/sprint7g_verify.py",
            ),
        ),
        focused_tests=(
            _pytest("Sprint 7G focused tests", "tests/test_finalize_sprint.py"),
        ),
        sprint_verifier=_verifier("Sprint 7G verifier", "tools/sprint7g_verify.py"),
        historical_verifiers=(
            _verifier("Sprint 7F verifier", "tools/sprint7f_verify.py"),
        ),
        full_pytest_required=True,
    ),
    "7I": SprintSpec(
        sprint_name="7I",
        expected_files=FileBoundarySpec(
            modified=(
                "gui/engine_bridge.py",
                "gui/models/render_context.py",
                "tools/finalization_specs.py",
            ),
            added=(
                "gui/services/generic_creative_strategy.py",
                "tests/test_sprint7i_generic_creative_quality.py",
                "tools/sprint7i_verify.py",
            ),
        ),
        focused_tests=(
            _pytest("Sprint 7I focused tests", "tests/test_sprint7i_generic_creative_quality.py"),
        ),
        sprint_verifier=_verifier("Sprint 7I verifier", "tools/sprint7i_verify.py"),
        regression_groups=(
            _pytest(
                "Generation/render/copy regressions",
                "tests/test_sprint7e_universal_generation.py",
                "tests/test_sprint7f_creative_quality.py",
                "tests/test_prospect_generation.py",
                "tests/test_ad_concept.py",
                "tests/test_message_strategy.py",
            ),
            _pytest(
                "Campaign/export regressions",
                "tests/test_campaign_export.py",
                "tests/test_campaign_package.py",
                "tests/test_campaign_review.py",
                "tests/test_sprint5ad_campaign_assembly.py",
                "tests/test_sprint5w_campaign_run.py",
                "tests/test_sprint5y_smartlead_export.py",
            ),
        ),
        historical_verifiers=(
            _verifier("Sprint 7F verifier", "tools/sprint7f_verify.py"),
            _verifier("Sprint 7E verifier", "tools/sprint7e_verify.py"),
        ),
        full_pytest_required=True,
    ),
}


def list_sprints() -> tuple[str, ...]:
    return tuple(sorted(SPRINT_SPECS))


def get_sprint_spec(name: str) -> SprintSpec:
    key = name.upper()
    if key not in SPRINT_SPECS:
        raise KeyError(f"Unknown sprint spec: {name}")
    return SPRINT_SPECS[key]
