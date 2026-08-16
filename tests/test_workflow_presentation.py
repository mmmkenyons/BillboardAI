from __future__ import annotations

import json

from gui.models.workflow_stage import WorkflowStageId, WorkflowStageState
from gui.services.workflow_presentation import (
    WorkflowSnapshot,
    derive_stage_models,
    format_blocker,
    format_status,
    package_matches_scope,
    recommended_next_action,
)


def test_status_formatting_examples() -> None:
    assert format_status("READY_FOR_RESEARCH") == "Ready for research"
    assert format_status("NEEDS_REVIEW") == "Needs review"
    assert format_status("RECONCILIATION_REQUIRED") == "Reconciliation required"
    assert format_status("DUPLICATE_REMOTE") == "Duplicate in Smartlead"
    assert format_status("SUCCEEDED") == "Complete"


def test_blocker_formatting_examples() -> None:
    assert "email address" in format_blocker("Missing email").lower()
    assert "mockup" in format_blocker("Missing mockup").lower()
    assert "reconciled" in format_blocker("Reconciliation required before launch").lower()


def test_recommended_next_action_derivation() -> None:
    assert recommended_next_action(WorkflowSnapshot()) == "Add or import prospects"
    assert recommended_next_action(WorkflowSnapshot(prospect_count=2, ready_for_research_count=1)) == "Research prospects"
    assert recommended_next_action(WorkflowSnapshot(prospect_count=2, researched_count=2, opportunity_count=0)) == "Review opportunities"
    assert recommended_next_action(WorkflowSnapshot(prospect_count=2, researched_count=2, opportunity_count=2, generated_count=0)) == "Generate mockups"
    assert recommended_next_action(WorkflowSnapshot(prospect_count=2, researched_count=2, opportunity_count=2, generated_count=2, review_total=0)) == "Review campaign"


def test_workflow_stage_derivation() -> None:
    stages = derive_stage_models(
        WorkflowSnapshot(
            prospect_count=2,
            ready_for_research_count=1,
            researched_count=1,
            opportunity_count=1,
            generated_count=1,
            review_total=1,
            approved_count=1,
            package_ready_count=1,
        ),
        WorkflowStageId.REVIEW,
    )
    by_id = {stage.stage_id: stage for stage in stages}
    assert by_id[WorkflowStageId.REVIEW].current is True
    assert by_id[WorkflowStageId.PROSPECTS].state == WorkflowStageState.COMPLETE
    assert by_id[WorkflowStageId.RESEARCH].state in {WorkflowStageState.READY, WorkflowStageState.COMPLETE}
    assert by_id[WorkflowStageId.SMARTLEAD].state == WorkflowStageState.READY


def test_package_scope_matching(tmp_path) -> None:
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    manifest_path = package_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "prospects": [
                    {"prospect_id": "a", "status": "READY"},
                    {"prospect_id": "b", "status": "WARNING"},
                ]
            }
        ),
        encoding="utf-8",
    )
    assert package_matches_scope(str(package_dir), ["a", "b"]) is True
    assert package_matches_scope(str(package_dir), ["a"]) is False
