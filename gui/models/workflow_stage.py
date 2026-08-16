"""Presentation-only workflow stage models and derivation helpers for Sprint 5V."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class WorkflowStageId(str, Enum):
    PROSPECTS = "prospects"
    RESEARCH = "research"
    OPPORTUNITIES = "opportunities"
    GENERATE = "generate"
    REVIEW = "review"
    SMARTLEAD = "smartlead"
    LAUNCH = "launch"


class WorkflowStageState(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    BLOCKED = "BLOCKED"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"


@dataclass(frozen=True)
class WorkflowStageDefinition:
    stage_id: WorkflowStageId
    label: str
    description: str


@dataclass(frozen=True)
class WorkflowStageViewModel:
    stage_id: WorkflowStageId
    label: str
    description: str
    state: WorkflowStageState
    current: bool = False
    count: int | None = None
    blocker_summary: str = ""
    recommended_action_label: str = ""


WORKFLOW_STAGE_DEFINITIONS: tuple[WorkflowStageDefinition, ...] = (
    WorkflowStageDefinition(WorkflowStageId.PROSPECTS, "Prospects", "Import and manage target businesses."),
    WorkflowStageDefinition(WorkflowStageId.RESEARCH, "Research", "Run prospect research and fill missing context."),
    WorkflowStageDefinition(WorkflowStageId.OPPORTUNITIES, "Opportunities", "Review recommended matches and sales fit."),
    WorkflowStageDefinition(WorkflowStageId.GENERATE, "Generate", "Create mockups and project assets."),
    WorkflowStageDefinition(WorkflowStageId.REVIEW, "Review", "Approve, exclude, or flag campaigns for changes."),
    WorkflowStageDefinition(WorkflowStageId.SMARTLEAD, "Smartlead", "Prepare, publish, reconcile, and validate outreach."),
    WorkflowStageDefinition(WorkflowStageId.LAUNCH, "Launch", "Review readiness and perform explicit activation controls."),
)
