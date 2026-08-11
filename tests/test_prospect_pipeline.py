"""Sprint 5I Prospect Pipeline service tests."""

from __future__ import annotations

import os
from datetime import date
from unittest.mock import patch

import pytest

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


_TODAY = date(2026, 8, 15)


def _store(tmp_path, prospects):
    store = ProspectStore(path=os.path.join(str(tmp_path), "prospects.json"))
    for prospect in prospects:
        store.create(prospect)
    store.save()
    return store


class TestPipelineSummary:
    def test_empty_store_summary(self, tmp_path) -> None:
        svc = ProspectPipelineService(ProspectStore(path=os.path.join(str(tmp_path), "prospects.json")))
        summary = svc.summary(today=_TODAY)
        assert summary.total_prospects == 0
        assert summary.active_prospects == 0
        assert summary.closed_prospects == 0
        assert all(summary.stage_counts[status] == 0 for status in PIPELINE_WORKFLOW_ORDER)

    def test_summary_counts_and_stage_breakdown(self, tmp_path) -> None:
        prospects = [
            Prospect(prospect_id="new", company_name="New Co", workflow_status=WORKFLOW_STATUS_NEW),
            Prospect(prospect_id="research", company_name="Research Co", workflow_status=WORKFLOW_STATUS_RESEARCHING),
            Prospect(prospect_id="ready", company_name="Ready Co", workflow_status=WORKFLOW_STATUS_READY_TO_CONTACT),
            Prospect(prospect_id="contacted", company_name="Contacted Co", workflow_status=WORKFLOW_STATUS_CONTACTED),
            Prospect(prospect_id="follow", company_name="Follow Co", workflow_status=WORKFLOW_STATUS_FOLLOW_UP),
            Prospect(prospect_id="qualified", company_name="Qualified Co", workflow_status=WORKFLOW_STATUS_QUALIFIED),
            Prospect(prospect_id="won", company_name="Won Co", workflow_status=WORKFLOW_STATUS_WON),
            Prospect(prospect_id="lost", company_name="Lost Co", workflow_status=WORKFLOW_STATUS_LOST),
            Prospect(prospect_id="nope", company_name="Nope Co", workflow_status=WORKFLOW_STATUS_NOT_INTERESTED),
        ]
        summary = ProspectPipelineService(_store(tmp_path, prospects)).summary(today=_TODAY)
        assert summary.total_prospects == 9
        assert summary.active_prospects == 6
        assert summary.closed_prospects == 3
        assert summary.won_prospects == 1
        assert summary.lost_prospects == 1
        assert summary.not_interested_prospects == 1
        for status in PIPELINE_WORKFLOW_ORDER:
            assert summary.stage_counts[status] == 1

    def test_needs_attention_metrics_exclude_terminal(self, tmp_path) -> None:
        prospects = [
            Prospect(prospect_id="over", workflow_status=WORKFLOW_STATUS_FOLLOW_UP, next_action_date="2026-08-14"),
            Prospect(prospect_id="today", workflow_status=WORKFLOW_STATUS_CONTACTED, next_action_date="2026-08-15"),
            Prospect(prospect_id="urgent", workflow_status=WORKFLOW_STATUS_NEW, priority=PRIORITY_URGENT, next_action_date="2026-08-20"),
            Prospect(prospect_id="closed_urgent", workflow_status=WORKFLOW_STATUS_WON, priority=PRIORITY_URGENT, next_action_date="2026-08-14"),
            Prospect(prospect_id="closed_over", workflow_status=WORKFLOW_STATUS_LOST, next_action_date="2026-08-14"),
        ]
        summary = ProspectPipelineService(_store(tmp_path, prospects)).summary(today=_TODAY)
        assert summary.overdue_prospects == 1
        assert summary.due_today_prospects == 1
        assert summary.urgent_prospects == 1
        assert summary.needs_attention_prospects == 3

    def test_injected_today_and_no_mutation(self, tmp_path) -> None:
        prospects = [
            Prospect(prospect_id="a", company_name="Alpha", workflow_status=WORKFLOW_STATUS_FOLLOW_UP, priority=PRIORITY_HIGH, next_action_date="2026-08-16"),
        ]
        store = _store(tmp_path, prospects)
        before = store.get("a").to_dict()
        summary = ProspectPipelineService(store).summary(today=date(2026, 8, 17))
        after = store.get("a").to_dict()
        assert summary.overdue_prospects == 1
        assert before == after

    def test_metric_relationships_and_terminal_exclusion(self, tmp_path) -> None:
        prospects = [
            Prospect(prospect_id="new", workflow_status=WORKFLOW_STATUS_NEW, company_name="New", next_action_date=None),
            Prospect(prospect_id="rtc", workflow_status=WORKFLOW_STATUS_READY_TO_CONTACT, company_name="RTC", priority=PRIORITY_URGENT, next_action_date=None),
            Prospect(prospect_id="fu_over", workflow_status=WORKFLOW_STATUS_FOLLOW_UP, company_name="FU Over", next_action_date="2026-08-14"),
            Prospect(prospect_id="fu_today", workflow_status=WORKFLOW_STATUS_FOLLOW_UP, company_name="FU Today", next_action_date="2026-08-15"),
            Prospect(prospect_id="qual", workflow_status=WORKFLOW_STATUS_QUALIFIED, company_name="Qual", next_action_date="2026-08-20"),
            Prospect(prospect_id="won", workflow_status=WORKFLOW_STATUS_WON, company_name="Won", priority=PRIORITY_URGENT, next_action_date="2026-08-14"),
            Prospect(prospect_id="lost", workflow_status=WORKFLOW_STATUS_LOST, company_name="Lost", next_action_date="2026-08-15"),
            Prospect(prospect_id="ni", workflow_status=WORKFLOW_STATUS_NOT_INTERESTED, company_name="NI", next_action_date=None),
        ]
        svc = ProspectPipelineService(_store(tmp_path, prospects))
        summary = svc.summary(today=_TODAY)
        assert summary.total_prospects == summary.active_prospects + summary.closed_prospects
        assert sum(summary.stage_counts.values()) == summary.total_prospects
        assert (
            summary.won_prospects + summary.lost_prospects + summary.not_interested_prospects
            == summary.closed_prospects
        )
        assert summary.needs_attention_prospects == 3
        assert summary.overdue_prospects == 1
        assert summary.due_today_prospects == 1
        assert summary.urgent_prospects == 1

    def test_summary_and_stage_detail_use_small_repeated_load_pattern(self, tmp_path) -> None:
        store = _store(tmp_path, [
            Prospect(prospect_id="a", company_name="Alpha", workflow_status=WORKFLOW_STATUS_FOLLOW_UP, next_action_date="2026-08-14"),
        ])
        svc = ProspectPipelineService(store)
        with patch.object(store, "load_or_empty", wraps=store.load_or_empty) as wrapped:
            svc.summary(today=_TODAY)
            svc.list_stage(WORKFLOW_STATUS_FOLLOW_UP, today=_TODAY)
        assert wrapped.call_count == 2


class TestStageDrillDown:
    def test_stage_lists(self, tmp_path) -> None:
        prospects = [
            Prospect(prospect_id="n", company_name="New Co", workflow_status=WORKFLOW_STATUS_NEW),
            Prospect(prospect_id="f", company_name="Follow Co", workflow_status=WORKFLOW_STATUS_FOLLOW_UP),
            Prospect(prospect_id="w", company_name="Won Co", workflow_status=WORKFLOW_STATUS_WON),
        ]
        svc = ProspectPipelineService(_store(tmp_path, prospects))
        assert [item.prospect_id for item in svc.list_stage(WORKFLOW_STATUS_NEW, today=_TODAY)] == ["n"]
        assert [item.prospect_id for item in svc.list_stage(WORKFLOW_STATUS_FOLLOW_UP, today=_TODAY)] == ["f"]
        assert [item.prospect_id for item in svc.list_stage(WORKFLOW_STATUS_WON, today=_TODAY)] == ["w"]

    def test_invalid_stage_raises(self, tmp_path) -> None:
        svc = ProspectPipelineService(_store(tmp_path, []))
        with pytest.raises(ValueError):
            svc.list_stage("INVALID", today=_TODAY)

    def test_stage_ordering_deterministic_and_no_mutation(self, tmp_path) -> None:
        prospects = [
            Prospect(prospect_id="b", company_name="Beta", workflow_status=WORKFLOW_STATUS_FOLLOW_UP, priority=PRIORITY_NORMAL, next_action_date="2026-08-20"),
            Prospect(prospect_id="a", company_name="Alpha", workflow_status=WORKFLOW_STATUS_FOLLOW_UP, priority=PRIORITY_URGENT, next_action_date="2026-08-15"),
            Prospect(prospect_id="c", company_name="Gamma", workflow_status=WORKFLOW_STATUS_FOLLOW_UP, priority=PRIORITY_HIGH, next_action_date="2026-08-14"),
        ]
        store = _store(tmp_path, prospects)
        before = {p.prospect_id: p.to_dict() for p in store.list()}
        ids = [item.prospect_id for item in ProspectPipelineService(store).list_stage(WORKFLOW_STATUS_FOLLOW_UP, today=_TODAY)]
        after = {p.prospect_id: p.to_dict() for p in store.list()}
        assert ids == ["c", "a", "b"]
        assert before == after

    def test_all_stage_lengths_match_summary_and_every_prospect_appears_once(self, tmp_path) -> None:
        prospects = [
            Prospect(prospect_id="new", workflow_status=WORKFLOW_STATUS_NEW, company_name="New"),
            Prospect(prospect_id="research", workflow_status=WORKFLOW_STATUS_RESEARCHING, company_name="Research"),
            Prospect(prospect_id="ready", workflow_status=WORKFLOW_STATUS_READY_TO_CONTACT, company_name="Ready"),
            Prospect(prospect_id="contacted", workflow_status=WORKFLOW_STATUS_CONTACTED, company_name="Contacted"),
            Prospect(prospect_id="follow", workflow_status=WORKFLOW_STATUS_FOLLOW_UP, company_name="Follow"),
            Prospect(prospect_id="qualified", workflow_status=WORKFLOW_STATUS_QUALIFIED, company_name="Qualified"),
            Prospect(prospect_id="won", workflow_status=WORKFLOW_STATUS_WON, company_name="Won"),
            Prospect(prospect_id="lost", workflow_status=WORKFLOW_STATUS_LOST, company_name="Lost"),
            Prospect(prospect_id="ni", workflow_status=WORKFLOW_STATUS_NOT_INTERESTED, company_name="NI"),
        ]
        svc = ProspectPipelineService(_store(tmp_path, prospects))
        summary = svc.summary(today=_TODAY)
        seen = []
        for status in PIPELINE_WORKFLOW_ORDER:
            items_first = svc.list_stage(status, today=_TODAY)
            items_second = svc.list_stage(status, today=_TODAY)
            assert len(items_first) == summary.stage_counts[status]
            assert [item.prospect_id for item in items_first] == [item.prospect_id for item in items_second]
            seen.extend(item.prospect_id for item in items_first)
        assert len(seen) == len(set(seen)) == summary.total_prospects