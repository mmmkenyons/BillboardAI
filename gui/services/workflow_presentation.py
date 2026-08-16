"""Presentation-only status, blocker, recommendation, and workflow derivation helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass

from gui.models.campaign_review import CAMPAIGN_REVIEW_STATUS_APPROVED, CAMPAIGN_REVIEW_STATUS_EXCLUDED, CAMPAIGN_REVIEW_STATUS_NEEDS_REVIEW
from gui.models.smartlead_handoff import SMARTLEAD_PREFLIGHT_BLOCKED, SMARTLEAD_PREFLIGHT_CONFLICT
from gui.models.smartlead_launch import SMARTLEAD_LAUNCH_STATUS_READY
from gui.models.workflow_stage import (
    WORKFLOW_STAGE_DEFINITIONS,
    WorkflowStageId,
    WorkflowStageState,
    WorkflowStageViewModel,
)
from gui.services.campaign_export import EXPORT_STATUS_BLOCKED, EXPORT_STATUS_READY, EXPORT_STATUS_WARNING


def format_status(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return "Unknown"
    aliases = {
        "SUCCEEDED": "Complete",
        "DUPLICATE_REMOTE": "Duplicate in Smartlead",
        "RECONCILIATION_REQUIRED": "Reconciliation required",
        "NEEDS_REVIEW": "Needs review",
        "READY_FOR_RESEARCH": "Ready for research",
    }
    if text in aliases:
        return aliases[text]
    words = text.replace("_", " ").strip().lower().split()
    return " ".join(word.capitalize() for word in words) if words else "Unknown"


def format_blocker(reason: object) -> str:
    text = str(reason or "").strip()
    normalized = text.lower()
    mappings = {
        "missing email": "Add an email address before this prospect can be included in outreach.",
        "missing mockup": "Generate a mockup before adding this prospect to the campaign.",
        "missing hosted asset": "Host the mockup before publishing this lead to Smartlead.",
        "sequence incomplete": "Finish the Smartlead sequence before launch.",
        "reconciliation required": "Smartlead state needs to be reconciled before launch.",
        "multiple remote smartlead leads matched this local publication.": "Smartlead found duplicate remote leads. Reconcile before launch.",
    }
    for key, value in mappings.items():
        if key in normalized:
            return value
    if "does not have an email" in normalized or "missing email" in normalized:
        return "Cannot continue: This prospect does not have an email address."
    if "source mockup file no longer exists" in normalized:
        return "Generate or restore the mockup before continuing with this campaign."
    return text or "Action required before continuing."


@dataclass(frozen=True)
class WorkflowSnapshot:
    prospect_count: int = 0
    ready_for_research_count: int = 0
    researched_count: int = 0
    research_in_progress_count: int = 0
    opportunity_count: int = 0
    generated_count: int = 0
    review_total: int = 0
    approved_count: int = 0
    excluded_count: int = 0
    needs_review_count: int = 0
    review_blocked_count: int = 0
    package_ready_count: int = 0
    handoff_ready_count: int = 0
    published_count: int = 0
    smartlead_attention_count: int = 0
    campaign_active: bool = False
    launch_ready: bool = False
    launch_blocker: str = ""


def recommended_next_action(snapshot: WorkflowSnapshot) -> str:
    if snapshot.prospect_count == 0:
        return "Add or import prospects"
    if snapshot.ready_for_research_count > 0:
        return "Research prospects"
    if snapshot.research_in_progress_count > 0:
        return "Monitor research progress"
    if snapshot.researched_count > 0 and snapshot.opportunity_count == 0:
        return "Review opportunities"
    if snapshot.opportunity_count > 0 and snapshot.generated_count == 0:
        return "Generate mockups"
    if snapshot.generated_count > 0 and snapshot.review_total == 0:
        return "Review campaign"
    if snapshot.approved_count > 0 and snapshot.package_ready_count == 0:
        return "Build campaign package"
    if snapshot.package_ready_count > 0 and snapshot.handoff_ready_count == 0:
        return "Prepare Smartlead"
    if snapshot.smartlead_attention_count > 0:
        return "Reconcile Smartlead"
    if snapshot.campaign_active:
        return "Monitor campaign"
    if snapshot.launch_ready:
        return "Review launch readiness"
    if snapshot.launch_blocker:
        return format_blocker(snapshot.launch_blocker)
    return "Campaign active"


def derive_stage_models(snapshot: WorkflowSnapshot, current_stage: WorkflowStageId) -> list[WorkflowStageViewModel]:
    stage_map: dict[WorkflowStageId, WorkflowStageViewModel] = {
        WorkflowStageId.PROSPECTS: WorkflowStageViewModel(
            stage_id=WorkflowStageId.PROSPECTS,
            label="Prospects",
            description="Import and manage target businesses.",
            state=WorkflowStageState.COMPLETE if snapshot.prospect_count > 0 else WorkflowStageState.NOT_STARTED,
            current=current_stage == WorkflowStageId.PROSPECTS,
            count=snapshot.prospect_count,
            recommended_action_label="Import prospects" if snapshot.prospect_count == 0 else "Manage prospects",
        ),
        WorkflowStageId.RESEARCH: WorkflowStageViewModel(
            stage_id=WorkflowStageId.RESEARCH,
            label="Research",
            description="Run prospect research.",
            state=(
                WorkflowStageState.BLOCKED if snapshot.prospect_count == 0 else
                WorkflowStageState.IN_PROGRESS if snapshot.research_in_progress_count > 0 else
                WorkflowStageState.READY if snapshot.ready_for_research_count > 0 else
                WorkflowStageState.COMPLETE if snapshot.researched_count > 0 else
                WorkflowStageState.NOT_STARTED
            ),
            current=current_stage == WorkflowStageId.RESEARCH,
            count=snapshot.research_in_progress_count or snapshot.ready_for_research_count or snapshot.researched_count or None,
            blocker_summary="Add prospects before starting research." if snapshot.prospect_count == 0 else "",
            recommended_action_label="Research prospects" if snapshot.ready_for_research_count > 0 else "",
        ),
        WorkflowStageId.OPPORTUNITIES: WorkflowStageViewModel(
            stage_id=WorkflowStageId.OPPORTUNITIES,
            label="Opportunities",
            description="Inspect recommended matches.",
            state=(
                WorkflowStageState.BLOCKED if snapshot.prospect_count == 0 else
                WorkflowStageState.COMPLETE if snapshot.opportunity_count > 0 else
                WorkflowStageState.READY if snapshot.researched_count > 0 else
                WorkflowStageState.NOT_STARTED
            ),
            current=current_stage == WorkflowStageId.OPPORTUNITIES,
            count=snapshot.opportunity_count or None,
            blocker_summary="No opportunities have been identified yet." if snapshot.researched_count > 0 and snapshot.opportunity_count == 0 else "",
            recommended_action_label="Review opportunities" if snapshot.opportunity_count > 0 else "",
        ),
        WorkflowStageId.GENERATE: WorkflowStageViewModel(
            stage_id=WorkflowStageId.GENERATE,
            label="Generate",
            description="Create mockups and project assets.",
            state=(
                WorkflowStageState.COMPLETE if snapshot.generated_count > 0 else
                WorkflowStageState.READY if snapshot.opportunity_count > 0 else
                WorkflowStageState.NOT_STARTED
            ),
            current=current_stage == WorkflowStageId.GENERATE,
            count=snapshot.generated_count or None,
            recommended_action_label="Generate mockup" if snapshot.opportunity_count > 0 and snapshot.generated_count == 0 else "",
        ),
        WorkflowStageId.REVIEW: WorkflowStageViewModel(
            stage_id=WorkflowStageId.REVIEW,
            label="Review",
            description="Approve campaigns and build package context.",
            state=(
                WorkflowStageState.COMPLETE if snapshot.review_total > 0 and (snapshot.approved_count + snapshot.excluded_count) >= snapshot.review_total and snapshot.needs_review_count == 0 else
                WorkflowStageState.NEEDS_ATTENTION if snapshot.review_total > 0 else
                WorkflowStageState.READY if snapshot.generated_count > 0 else
                WorkflowStageState.NOT_STARTED
            ),
            current=current_stage == WorkflowStageId.REVIEW,
            count=snapshot.review_total or None,
            blocker_summary="Some campaigns are blocked." if snapshot.review_blocked_count > 0 else "",
            recommended_action_label="Review campaign" if snapshot.generated_count > 0 else "",
        ),
        WorkflowStageId.SMARTLEAD: WorkflowStageViewModel(
            stage_id=WorkflowStageId.SMARTLEAD,
            label="Smartlead",
            description="Prepare and reconcile Smartlead handoff.",
            state=(
                WorkflowStageState.NEEDS_ATTENTION if snapshot.smartlead_attention_count > 0 else
                WorkflowStageState.COMPLETE if snapshot.handoff_ready_count > 0 or snapshot.published_count > 0 else
                WorkflowStageState.READY if snapshot.package_ready_count > 0 else
                WorkflowStageState.NOT_STARTED
            ),
            current=current_stage == WorkflowStageId.SMARTLEAD,
            count=snapshot.handoff_ready_count or snapshot.package_ready_count or None,
            blocker_summary="Smartlead status needs attention." if snapshot.smartlead_attention_count > 0 else "",
            recommended_action_label="Prepare Smartlead" if snapshot.package_ready_count > 0 else "",
        ),
        WorkflowStageId.LAUNCH: WorkflowStageViewModel(
            stage_id=WorkflowStageId.LAUNCH,
            label="Launch",
            description="Review launch readiness and activation safeguards.",
            state=(
                WorkflowStageState.COMPLETE if snapshot.campaign_active else
                WorkflowStageState.READY if snapshot.launch_ready else
                WorkflowStageState.BLOCKED if snapshot.launch_blocker else
                WorkflowStageState.NOT_STARTED
            ),
            current=current_stage == WorkflowStageId.LAUNCH,
            blocker_summary=format_blocker(snapshot.launch_blocker) if snapshot.launch_blocker else "",
            recommended_action_label="Review launch readiness" if snapshot.handoff_ready_count > 0 else "",
        ),
    }
    return [stage_map[definition.stage_id] for definition in WORKFLOW_STAGE_DEFINITIONS]


def derive_review_snapshot(rows: list[dict], summary: object | None = None, handoff_result: object | None = None, launch_result: object | None = None) -> WorkflowSnapshot:
    review_rows = list(rows or [])
    approved = sum(1 for row in review_rows if str(row.get("review_status") or "") == CAMPAIGN_REVIEW_STATUS_APPROVED)
    excluded = sum(1 for row in review_rows if str(row.get("review_status") or "") == CAMPAIGN_REVIEW_STATUS_EXCLUDED)
    needs_review = sum(1 for row in review_rows if str(row.get("review_status") or "") == CAMPAIGN_REVIEW_STATUS_NEEDS_REVIEW)
    blocked = sum(1 for row in review_rows if str(row.get("technical_status") or "") == EXPORT_STATUS_BLOCKED)
    package_ready_count = approved if approved else 0
    handoff_ready_count = 0
    attention = 0
    if handoff_result is not None:
        handoff_ready_count = sum(1 for row in getattr(handoff_result, "rows", ()) if getattr(row, "status", "") not in {SMARTLEAD_PREFLIGHT_BLOCKED, SMARTLEAD_PREFLIGHT_CONFLICT})
        attention = sum(1 for row in getattr(handoff_result, "rows", ()) if getattr(row, "status", "") in {SMARTLEAD_PREFLIGHT_BLOCKED, SMARTLEAD_PREFLIGHT_CONFLICT})
    launch_ready = bool(getattr(launch_result, "status", "") == SMARTLEAD_LAUNCH_STATUS_READY)
    launch_blocker = "; ".join(list(getattr(launch_result, "reasons", ()) or ())) if launch_result is not None and not launch_ready else ""
    return WorkflowSnapshot(
        review_total=len(review_rows),
        approved_count=approved,
        excluded_count=excluded,
        needs_review_count=needs_review,
        review_blocked_count=blocked,
        package_ready_count=package_ready_count,
        handoff_ready_count=handoff_ready_count,
        smartlead_attention_count=attention,
        launch_ready=launch_ready,
        launch_blocker=launch_blocker,
    )


def package_matches_scope(package_directory: str, expected_prospect_ids: list[str] | None) -> bool:
    manifest_path = os.path.join(os.path.abspath(package_directory), "manifest.json")
    if not os.path.isfile(manifest_path):
        return False
    if not expected_prospect_ids:
        return True
    import json

    with open(manifest_path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    manifest_ids = {
        str(item.get("prospect_id") or "")
        for item in list(manifest.get("prospects") or [])
        if str(item.get("status") or "").upper() in {EXPORT_STATUS_READY, EXPORT_STATUS_WARNING}
    }
    expected = {str(item or "") for item in expected_prospect_ids if str(item or "").strip()}
    return bool(expected) and manifest_ids == expected
