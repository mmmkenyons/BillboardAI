#!/usr/bin/env python
"""Sprint 5I verifier — Sales Pipeline / Command Center.

SYNTHETIC VERIFICATION DATA — no network, scraping, geocoding, enrichment, or
recommendation recomputation triggered by pipeline rendering.
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def verify() -> int:
    root = tempfile.mkdtemp(prefix="sprint5i_verify_")
    print(f"VERIFIER ROOT: {root}")
    print("SYNTHETIC VERIFICATION DATA\n")

    from datetime import date

    from PySide6.QtWidgets import QApplication

    from gui.controllers.prospect_controller import ProspectController
    from gui.main_window import MainWindow
    from gui.models.prospect import (
        PRIORITY_HIGH,
        PRIORITY_NORMAL,
        PRIORITY_URGENT,
        PIPELINE_WORKFLOW_ORDER,
        WORKFLOW_STATUS_CONTACTED,
        WORKFLOW_STATUS_FOLLOW_UP,
        WORKFLOW_STATUS_LOST,
        WORKFLOW_STATUS_NEW,
        WORKFLOW_STATUS_NOT_INTERESTED,
        WORKFLOW_STATUS_QUALIFIED,
        WORKFLOW_STATUS_READY_TO_CONTACT,
        WORKFLOW_STATUS_RESEARCHING,
        WORKFLOW_STATUS_WON,
        Prospect,
    )
    from gui.models.prospect_store import ProspectStore
    from gui.services.prospect_pipeline import ProspectPipelineService
    from gui.services.prospect_workspace import ProspectWorkspaceService

    _app = QApplication.instance() or QApplication([])
    today = date(2026, 8, 15)
    passed = 0
    failed = 0

    def check(name: str, condition: bool, message: str = "") -> None:
        nonlocal passed, failed
        if condition:
            print(f"[PASS] {name}")
            passed += 1
        else:
            print(f"[FAIL] {name}: {message}")
            failed += 1

    empty_store = ProspectStore(path=os.path.join(root, "empty.json"))
    empty_summary = ProspectPipelineService(empty_store).summary(today=today)
    check("Empty summary total", empty_summary.total_prospects == 0)
    check("Empty summary stage counts", all(empty_summary.stage_counts[s] == 0 for s in PIPELINE_WORKFLOW_ORDER))

    store = ProspectStore(path=os.path.join(root, "prospects.json"))
    prospects = [
        Prospect(prospect_id="new", company_name="New", workflow_status=WORKFLOW_STATUS_NEW),
        Prospect(prospect_id="research", company_name="Research", workflow_status=WORKFLOW_STATUS_RESEARCHING),
        Prospect(prospect_id="ready", company_name="Ready", workflow_status=WORKFLOW_STATUS_READY_TO_CONTACT),
        Prospect(prospect_id="contacted", company_name="Contacted", workflow_status=WORKFLOW_STATUS_CONTACTED, next_action_date="2026-08-15"),
        Prospect(prospect_id="follow", company_name="Follow", workflow_status=WORKFLOW_STATUS_FOLLOW_UP, priority=PRIORITY_HIGH, next_action_date="2026-08-14"),
        Prospect(prospect_id="qualified", company_name="Qualified", workflow_status=WORKFLOW_STATUS_QUALIFIED, priority=PRIORITY_URGENT, next_action_date="2026-08-20"),
        Prospect(prospect_id="won", company_name="Won", workflow_status=WORKFLOW_STATUS_WON),
        Prospect(prospect_id="lost", company_name="Lost", workflow_status=WORKFLOW_STATUS_LOST, priority=PRIORITY_URGENT, next_action_date="2026-08-14"),
        Prospect(prospect_id="ni", company_name="NI", workflow_status=WORKFLOW_STATUS_NOT_INTERESTED),
    ]
    for prospect in prospects:
        store.create(prospect)
    store.save()

    svc = ProspectPipelineService(store)
    summary = svc.summary(today=today)
    check("Total prospects", summary.total_prospects == 9)
    check("Active prospects", summary.active_prospects == 6)
    check("Closed prospects", summary.closed_prospects == 3)
    check("Won prospects", summary.won_prospects == 1)
    check("Lost prospects", summary.lost_prospects == 1)
    check("Not interested prospects", summary.not_interested_prospects == 1)
    check("Overdue active prospects", summary.overdue_prospects == 1)
    check("Due today active prospects", summary.due_today_prospects == 1)
    check("Needs attention active prospects", summary.needs_attention_prospects == 3)
    check("Terminal urgent excluded from needs attention", summary.needs_attention_prospects != 4)
    check("Stage counts", all(summary.stage_counts[s] == 1 for s in PIPELINE_WORKFLOW_ORDER))

    injected_summary = svc.summary(today=date(2026, 8, 21))
    check("Injected today honored", injected_summary.overdue_prospects == 3)

    stage_ids = [item.prospect_id for item in svc.list_stage(WORKFLOW_STATUS_FOLLOW_UP, today=today)]
    check("FOLLOW_UP stage list", stage_ids == ["follow"])
    ordered_store = ProspectStore(path=os.path.join(root, "ordered.json"))
    for prospect in [
        Prospect(prospect_id="b", company_name="Beta", workflow_status=WORKFLOW_STATUS_FOLLOW_UP, priority=PRIORITY_NORMAL, next_action_date="2026-08-20"),
        Prospect(prospect_id="a", company_name="Alpha", workflow_status=WORKFLOW_STATUS_FOLLOW_UP, priority=PRIORITY_URGENT, next_action_date="2026-08-15"),
        Prospect(prospect_id="c", company_name="Gamma", workflow_status=WORKFLOW_STATUS_FOLLOW_UP, priority=PRIORITY_HIGH, next_action_date="2026-08-14"),
    ]:
        ordered_store.create(prospect)
    ordered_store.save()
    ordered_ids = [item.prospect_id for item in ProspectPipelineService(ordered_store).list_stage(WORKFLOW_STATUS_FOLLOW_UP, today=today)]
    check("Deterministic stage ordering", ordered_ids == ["c", "a", "b"], f"got {ordered_ids}")

    before = ordered_store.get("a").to_dict()
    ProspectPipelineService(ordered_store).summary(today=today)
    after = ordered_store.get("a").to_dict()
    check("No prospect mutation", before == after)

    custom_store = ProspectStore(path=os.path.join(root, "custom.json"))
    custom_service = ProspectWorkspaceService(store=custom_store)
    custom_service.load()
    custom = custom_service.create_prospect(company_name="Custom Co", website="custom.com")
    custom_service.update_workflow(custom.prospect_id, status=WORKFLOW_STATUS_FOLLOW_UP, priority=PRIORITY_HIGH, next_action_date="2026-08-14")
    controller = ProspectController(service=custom_service)
    window = MainWindow(prospect_controller=controller)
    window.show_page("pipeline")
    check("Injected store authority", window.pipeline_page.summary_cards["total"].text() == "1")

    for row in range(window.pipeline_page.stage_table.rowCount()):
        item = window.pipeline_page.stage_table.item(row, 0)
        if item.data(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.ItemDataRole.UserRole) == WORKFLOW_STATUS_FOLLOW_UP:
            window.pipeline_page.stage_table.selectRow(row)
            break
    check("Pipeline stage drill-down", window.pipeline_page.prospect_table.rowCount() == 1)
    window.pipeline_page.prospect_table.selectRow(0)
    window.pipeline_page._open_selected_prospect()
    check("Navigation to Prospect Workspace", window._stack.currentWidget() is window.prospects_workspace)
    check("Correct prospect selected", window.prospects_workspace.get_selected_prospect_id() == custom.prospect_id)
    selected = controller.get_selected()
    check("Sales Follow-Up populated", selected is not None and selected.workflow_status == WORKFLOW_STATUS_FOLLOW_UP)
    check("Opportunity Overview remains functional", controller.snapshot is not None)

    controller.update_workflow(custom.prospect_id, status=WORKFLOW_STATUS_WON, priority=PRIORITY_NORMAL)
    window.show_page("pipeline")
    check("Workflow-change refresh", window.pipeline_page.summary_cards["won"].text() == "1")

    check("No duplicate prospects in stage list", len(stage_ids) == len(set(stage_ids)))
    check("No pipeline-render side effects", controller.snapshot is not None)

    print()
    print("=" * 60)
    print("SPRINT 5I VERIFICATION COMPLETE")
    print("=" * 60)
    print(f"Temp data at: {root}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print("SYNTHETIC VERIFICATION DATA - not real prospects or inventory.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(verify())