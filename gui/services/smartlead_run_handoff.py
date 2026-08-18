"""Run-scoped Smartlead handoff orchestration for Sprint 5X."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field

from gui.models.smartlead_launch import SMARTLEAD_LAUNCH_STATUS_NOT_READY
from gui.models.smartlead_run_package import (
    SmartleadRunPackageEntry,
    SmartleadRunPackageRecord,
    SmartleadRunPackageStore,
)
from gui.models.smartlead_handoff import SMARTLEAD_PREFLIGHT_BLOCKED, SMARTLEAD_PREFLIGHT_CONFLICT
from gui.services.campaign_run import ACTION_BUILD_PACKAGE, ACTION_PREPARE_SMARTLEAD, ACTION_READY, CampaignRunService


@dataclass(frozen=True)
class SmartleadRunRow:
    prospect_id: str
    company: str = ""
    email: str = ""
    website: str = ""
    project_id: str = ""
    generation_job_id: str = ""
    review_status: str = ""
    outreach_status: str = ""
    asset_status: str = ""
    smartlead_status: str = ""
    launch_status: str = "NOT_READY"
    blockers: tuple[str, ...] = ()
    next_action: str = ""
    packaged: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "prospect_id": self.prospect_id,
            "company": self.company,
            "email": self.email,
            "website": self.website,
            "project_id": self.project_id,
            "generation_job_id": self.generation_job_id,
            "review_status": self.review_status,
            "outreach_status": self.outreach_status,
            "asset_status": self.asset_status,
            "smartlead_status": self.smartlead_status,
            "launch_status": self.launch_status,
            "blockers": list(self.blockers),
            "next_action": self.next_action,
            "packaged": self.packaged,
        }


@dataclass(frozen=True)
class SmartleadRunSummary:
    campaign_run_id: str = ""
    campaign_name: str = ""
    total_members: int = 0
    ready: int = 0
    blocked: int = 0
    packaged: int = 0
    packageable: int = 0
    launch_ready: int = 0
    package_ready: int = 0
    external_ready: int = 0
    status: str = "NOT_STARTED"
    recommended_next_action: str = ""
    package_directory: str = ""
    handoff_directory: str = ""

    def to_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class SmartleadRunContext:
    campaign_run_id: str
    campaign_name: str
    rows: tuple[SmartleadRunRow, ...] = field(default_factory=tuple)
    summary: SmartleadRunSummary = field(default_factory=SmartleadRunSummary)
    package_record: SmartleadRunPackageRecord | None = None


class SmartleadRunHandoffService:
    def __init__(
        self,
        *,
        run_service: CampaignRunService,
        package_store: SmartleadRunPackageStore | None = None,
        package_root: str | None = None,
    ) -> None:
        self._run_service = run_service
        self._package_store = package_store or SmartleadRunPackageStore()
        self._package_root = os.path.abspath(
            package_root
            or os.path.join(os.path.dirname(self._package_store.path), "run_artifacts")
        )

    @property
    def package_store(self) -> SmartleadRunPackageStore:
        return self._package_store

    def context_for_run(self, campaign_run_id: str) -> SmartleadRunContext:
        run = self._run_service.get_run(campaign_run_id)
        if run is None:
            return SmartleadRunContext(campaign_run_id=str(campaign_run_id or ""), campaign_name="")
        record = self._valid_record(run.id)
        snapshot = self._run_service.snapshot(run.id, package_directory=getattr(record, "package_directory", None) if record else None)
        packaged_ids = {entry.prospect_id for entry in getattr(record, "entries", ()) if str(entry.status or "").upper() in {"READY", "WARNING"}}
        rows = tuple(self._map_row(row, packaged_ids) for row in snapshot.rows)
        ready = sum(1 for row in rows if row.packaged)
        blocked = sum(1 for row in rows if row.blockers)
        packaged = sum(1 for row in rows if row.packaged)
        packageable = sum(1 for item in snapshot.rows if getattr(item, "package_status", "") == "READY")
        package_ready = packaged
        external_ready = 0
        launch_ready = 0
        status = "NOT_STARTED"
        if packaged:
            status = "PACKAGED"
        elif ready:
            status = "READY"
        elif blocked and len(rows):
            status = "NEEDS_ATTENTION"
        recommendation = ACTION_BUILD_PACKAGE if ready and not packaged else (ACTION_PREPARE_SMARTLEAD if packaged else snapshot.summary.recommended_next_action)
        summary = SmartleadRunSummary(
            campaign_run_id=run.id,
            campaign_name=run.name,
            total_members=len(rows),
            ready=ready,
            blocked=blocked,
            packaged=packaged,
            packageable=packageable,
            launch_ready=launch_ready,
            package_ready=package_ready,
            external_ready=external_ready,
            status=status,
            recommended_next_action=recommendation,
            package_directory=getattr(record, "package_directory", "") if record else "",
            handoff_directory=getattr(record, "handoff_directory", "") if record else "",
        )
        return SmartleadRunContext(campaign_run_id=run.id, campaign_name=run.name, rows=rows, summary=summary, package_record=record)

    def prepare_package_for_run(self, campaign_run_id: str) -> SmartleadRunContext:
        run = self._run_service.get_run(campaign_run_id)
        if run is None:
            return self.context_for_run(campaign_run_id)
        run_dir = os.path.join(self._package_root, run.id)
        os.makedirs(run_dir, exist_ok=True)
        package_result = self._run_service.review_service.build_approved_package(run.prospect_ids, run_dir, campaign_name=run.name)
        handoff_result = self._run_service._handoff_service.prepare_handoff(package_result.package_directory) if getattr(package_result, "success", False) else None
        package_hash = self._fingerprint(run.prospect_ids, package_result, handoff_result)
        previous = self._package_store.get(run.id)
        created_at = getattr(previous, "created_at", "") or getattr(package_result.manifest, "created_at", "")
        entries = []
        row_map = {row.prospect_id: row for row in self._run_service.snapshot(run.id, package_directory=package_result.package_directory).rows}
        for prospect_id in run.prospect_ids:
            derived = row_map.get(prospect_id)
            blocker = "; ".join(getattr(derived, "blockers", ()) or ()) if derived is not None else ""
            entries.append(
                SmartleadRunPackageEntry(
                    prospect_id=prospect_id,
                    status="READY" if prospect_id in {item.prospect_id for item in getattr(package_result.manifest, "prospects", ()) if item.status in {"READY", "WARNING"}} else "BLOCKED",
                    project_id=getattr(derived, "project_id", "") if derived is not None else "",
                    generation_job_id=getattr(derived, "generation_job_id", "") if derived is not None else "",
                    email=getattr(derived, "email", "") if derived is not None else "",
                    blocker=blocker,
                )
            )
        record = SmartleadRunPackageRecord(
            campaign_run_id=run.id,
            package_id=str(getattr(getattr(package_result, "manifest", None), "package_id", "") or ""),
            package_directory=str(getattr(package_result, "package_directory", "") or ""),
            package_manifest_path=str(getattr(package_result, "manifest_path", "") or ""),
            handoff_directory=str(getattr(handoff_result, "handoff_directory", "") or "") if handoff_result is not None else "",
            handoff_manifest_path=str(getattr(handoff_result, "manifest_path", "") or "") if handoff_result is not None else "",
            smartlead_csv_path=str(getattr(handoff_result, "smartlead_csv_path", "") or "") if handoff_result is not None else "",
            created_at=created_at,
            updated_at=getattr(getattr(package_result, "manifest", None), "created_at", "") or created_at,
            status="PACKAGED" if getattr(package_result, "success", False) else "BLOCKED",
            package_hash=package_hash,
            total_members=len(run.prospect_ids),
            ready_count=sum(1 for entry in entries if entry.status == "READY"),
            blocked_count=sum(1 for entry in entries if entry.status != "READY"),
            packaged_count=getattr(package_result, "included_count", 0),
            entries=tuple(entries),
        )
        self._package_store.upsert(record)
        self._package_store.save()
        return self.context_for_run(run.id)

    def _valid_record(self, campaign_run_id: str) -> SmartleadRunPackageRecord | None:
        record = self._package_store.get(campaign_run_id)
        if record is None:
            return None
        if not record.package_directory or not os.path.isdir(record.package_directory):
            return None
        if record.package_manifest_path and not os.path.isfile(record.package_manifest_path):
            return None
        return record

    def _map_row(self, row: object, packaged_ids: set[str]) -> SmartleadRunRow:
        blockers = tuple(getattr(row, "blockers", ()) or ())
        raw_smartlead = str(getattr(row, "smartlead_status", "") or "")
        smartlead_status = "READY" if raw_smartlead == "READY" or getattr(row, "prospect_id", "") in packaged_ids else raw_smartlead or "BLOCKED"
        next_action = getattr(row, "next_action", "")
        if smartlead_status == "READY" and next_action == ACTION_READY:
            next_action = ACTION_BUILD_PACKAGE
        return SmartleadRunRow(
            prospect_id=getattr(row, "prospect_id", ""),
            company=getattr(row, "company_name", ""),
            email=getattr(row, "email", ""),
            website=getattr(row, "website", ""),
            project_id=getattr(row, "project_id", ""),
            generation_job_id=getattr(row, "generation_job_id", ""),
            review_status=getattr(row, "review_status", ""),
            outreach_status=getattr(row, "outreach_status", ""),
            asset_status=getattr(row, "package_status", ""),
            smartlead_status=smartlead_status,
            launch_status=SMARTLEAD_LAUNCH_STATUS_NOT_READY,
            blockers=blockers,
            next_action=next_action,
            packaged=getattr(row, "prospect_id", "") in packaged_ids,
        )

    def _fingerprint(self, prospect_ids: list[str], package_result: object, handoff_result: object | None) -> str:
        parts = ["|".join(str(item) for item in prospect_ids)]
        parts.append(str(getattr(package_result, "included_count", 0)))
        parts.append(str(getattr(package_result, "blocked_count", 0)))
        parts.append(str(getattr(handoff_result, "smartlead_csv_path", "") if handoff_result is not None else ""))
        return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()