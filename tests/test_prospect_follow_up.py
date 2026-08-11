"""Sprint 5H Prospect Follow-Up Queue service tests."""

from __future__ import annotations

import os
from datetime import date

import pytest

from gui.models.prospect import (
    PRIORITY_HIGH,
    PRIORITY_LOW,
    PRIORITY_NORMAL,
    PRIORITY_URGENT,
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
from gui.services.prospect_follow_up import (
    STATUS_FILTER_ACTIVE,
    STATUS_FILTER_ALL,
    STATUS_FILTER_CLOSED,
    TIMING_CLOSED,
    TIMING_DUE_TODAY,
    TIMING_NO_DUE_DATE,
    TIMING_OVERDUE,
    TIMING_UPCOMING,
    TIMING_FILTER_NEEDS_ATTENTION,
    derive_timing_state,
    ProspectFollowUpService,
)


_TODAY = date(2026, 8, 15)


def _store(tmp_path, prospects):
    path = os.path.join(str(tmp_path), "prospects.json")
    store = ProspectStore(path=path)
    for p in prospects:
        store.create(p)
    store.save()
    return store


def _service(tmp_path, prospects):
    return ProspectFollowUpService(_store(tmp_path, prospects))


class TestTimingClassification:
    def test_overdue_classification(self) -> None:
        p = Prospect(next_action_date="2026-08-14")
        assert derive_timing_state(p, _TODAY) == TIMING_OVERDUE

    def test_due_today_classification(self) -> None:
        p = Prospect(next_action_date="2026-08-15")
        assert derive_timing_state(p, _TODAY) == TIMING_DUE_TODAY

    def test_upcoming_classification(self) -> None:
        p = Prospect(next_action_date="2026-08-16")
        assert derive_timing_state(p, _TODAY) == TIMING_UPCOMING

    def test_no_due_date_classification(self) -> None:
        p = Prospect(next_action_date=None)
        assert derive_timing_state(p, _TODAY) == TIMING_NO_DUE_DATE

    def test_terminal_status_classifies_as_closed(self) -> None:
        for status in (
            WORKFLOW_STATUS_NOT_INTERESTED,
            WORKFLOW_STATUS_WON,
            WORKFLOW_STATUS_LOST,
        ):
            p = Prospect(workflow_status=status, next_action_date="2026-08-14")
            assert derive_timing_state(p, _TODAY) == TIMING_CLOSED

    def test_terminal_status_overrides_future_due_date(self) -> None:
        p = Prospect(
            workflow_status=WORKFLOW_STATUS_WON,
            next_action_date="2026-08-20",
        )
        assert derive_timing_state(p, _TODAY) == TIMING_CLOSED

    def test_injected_today_as_string(self) -> None:
        p = Prospect(next_action_date="2026-08-14")
        assert derive_timing_state(p, "2026-08-15") == TIMING_OVERDUE

    def test_injected_today_as_date_object(self) -> None:
        p = Prospect(next_action_date="2026-08-15")
        assert derive_timing_state(p, _TODAY) == TIMING_DUE_TODAY

    def test_malformed_date_defaults_to_no_due_date(self) -> None:
        p = Prospect(next_action_date="not-a-date")
        assert derive_timing_state(p, _TODAY) == TIMING_NO_DUE_DATE


class TestDefaultQueue:
    def test_terminal_excluded_from_default_active_queue(self, tmp_path) -> None:
        prospects = [
            Prospect(prospect_id="a", company_name="Active Co"),
            Prospect(
                prospect_id="b",
                company_name="Won Co",
                workflow_status=WORKFLOW_STATUS_WON,
            ),
        ]
        svc = _service(tmp_path, prospects)
        items = svc.list_items(today=_TODAY)
        assert len(items) == 1
        assert items[0].prospect_id == "a"

    def test_all_status_filter_includes_terminal(self, tmp_path) -> None:
        prospects = [
            Prospect(prospect_id="a", company_name="Active Co"),
            Prospect(
                prospect_id="b",
                company_name="Won Co",
                workflow_status=WORKFLOW_STATUS_WON,
            ),
        ]
        svc = _service(tmp_path, prospects)
        items = svc.list_items(today=_TODAY, status_filter=STATUS_FILTER_ALL)
        assert len(items) == 2

    def test_closed_filter_shows_only_terminal(self, tmp_path) -> None:
        prospects = [
            Prospect(prospect_id="a", company_name="Active Co"),
            Prospect(
                prospect_id="b",
                company_name="Won Co",
                workflow_status=WORKFLOW_STATUS_WON,
            ),
            Prospect(
                prospect_id="c",
                company_name="Lost Co",
                workflow_status=WORKFLOW_STATUS_LOST,
            ),
        ]
        svc = _service(tmp_path, prospects)
        items = svc.list_items(today=_TODAY, status_filter=STATUS_FILTER_CLOSED)
        assert len(items) == 2
        assert {i.prospect_id for i in items} == {"b", "c"}



class TestSorting:
    def test_urgent_sorts_ahead_of_high_normal_low(self, tmp_path) -> None:
        prospects = [
            Prospect(
                prospect_id="n",
                company_name="N",
                priority=PRIORITY_NORMAL,
                next_action_date="2026-08-20",
            ),
            Prospect(
                prospect_id="l",
                company_name="L",
                priority=PRIORITY_LOW,
                next_action_date="2026-08-20",
            ),
            Prospect(
                prospect_id="h",
                company_name="H",
                priority=PRIORITY_HIGH,
                next_action_date="2026-08-20",
            ),
            Prospect(
                prospect_id="u",
                company_name="U",
                priority=PRIORITY_URGENT,
                next_action_date="2026-08-20",
            ),
        ]
        svc = _service(tmp_path, prospects)
        items = svc.list_items(today=_TODAY)
        assert [i.prospect_id for i in items] == ["u", "h", "n", "l"]

    def test_earlier_upcoming_date_sorts_before_later(self, tmp_path) -> None:
        prospects = [
            Prospect(
                prospect_id="later",
                company_name="Later",
                next_action_date="2026-08-20",
            ),
            Prospect(
                prospect_id="earlier",
                company_name="Earlier",
                next_action_date="2026-08-16",
            ),
        ]
        svc = _service(tmp_path, prospects)
        items = svc.list_items(today=_TODAY)
        assert [i.prospect_id for i in items] == ["earlier", "later"]

    def test_overdue_bucket_sorts_by_priority_then_date(self, tmp_path) -> None:
        prospects = [
            Prospect(
                prospect_id="newer",
                company_name="Newer",
                priority=PRIORITY_HIGH,
                next_action_date="2026-08-13",
            ),
            Prospect(
                prospect_id="older",
                company_name="Older",
                priority=PRIORITY_NORMAL,
                next_action_date="2026-08-10",
            ),
        ]
        svc = _service(tmp_path, prospects)
        items = svc.list_items(today=_TODAY)
        # Higher priority wins within the overdue bucket; date is a tie-breaker.
        assert [i.prospect_id for i in items] == ["newer", "older"]

    def test_overdue_bucket_sorts_by_date_when_priority_equal(self, tmp_path) -> None:
        prospects = [
            Prospect(
                prospect_id="newer",
                company_name="Newer",
                priority=PRIORITY_NORMAL,
                next_action_date="2026-08-13",
            ),
            Prospect(
                prospect_id="older",
                company_name="Older",
                priority=PRIORITY_NORMAL,
                next_action_date="2026-08-10",
            ),
        ]
        svc = _service(tmp_path, prospects)
        items = svc.list_items(today=_TODAY)
        assert [i.prospect_id for i in items] == ["older", "newer"]

    def test_deterministic_tie_ordering(self, tmp_path) -> None:
        prospects = [
            Prospect(
                prospect_id="b",
                company_name="Same",
                priority=PRIORITY_NORMAL,
                next_action_date="2026-08-20",
            ),
            Prospect(
                prospect_id="a",
                company_name="Same",
                priority=PRIORITY_NORMAL,
                next_action_date="2026-08-20",
            ),
        ]
        svc = _service(tmp_path, prospects)
        items = svc.list_items(today=_TODAY)
        assert [i.prospect_id for i in items] == ["a", "b"]

    def test_timing_bucket_order_overrides_priority(self, tmp_path) -> None:
        prospects = [
            Prospect(
                prospect_id="up",
                company_name="Up",
                priority=PRIORITY_URGENT,
                next_action_date="2026-08-20",
            ),
            Prospect(
                prospect_id="over",
                company_name="Over",
                priority=PRIORITY_LOW,
                next_action_date="2026-08-14",
            ),
        ]
        svc = _service(tmp_path, prospects)
        items = svc.list_items(today=_TODAY)
        assert [i.prospect_id for i in items] == ["over", "up"]



class TestFiltering:
    def test_search_filters_by_company(self, tmp_path) -> None:
        prospects = [
            Prospect(prospect_id="a", company_name="Alpha Dental"),
            Prospect(prospect_id="b", company_name="Beta Roofing"),
        ]
        svc = _service(tmp_path, prospects)
        items = svc.list_items(today=_TODAY, search_text="roof")
        assert len(items) == 1
        assert items[0].company_name == "Beta Roofing"

    def test_search_filters_by_domain(self, tmp_path) -> None:
        prospects = [
            Prospect(prospect_id="a", company_name="A", website="alpha.com"),
            Prospect(prospect_id="b", company_name="B", website="beta.com"),
        ]
        svc = _service(tmp_path, prospects)
        items = svc.list_items(today=_TODAY, search_text="beta")
        assert len(items) == 1
        assert items[0].prospect_id == "b"

    def test_search_filters_by_next_action(self, tmp_path) -> None:
        prospects = [
            Prospect(prospect_id="a", company_name="A", next_action="email owner"),
            Prospect(prospect_id="b", company_name="B", next_action="call owner"),
        ]
        svc = _service(tmp_path, prospects)
        items = svc.list_items(today=_TODAY, search_text="call")
        assert len(items) == 1
        assert items[0].prospect_id == "b"

    def test_status_active_filter(self, tmp_path) -> None:
        prospects = [
            Prospect(prospect_id="a", workflow_status=WORKFLOW_STATUS_NEW),
            Prospect(prospect_id="b", workflow_status=WORKFLOW_STATUS_WON),
        ]
        svc = _service(tmp_path, prospects)
        items = svc.list_items(today=_TODAY, status_filter=STATUS_FILTER_ACTIVE)
        assert len(items) == 1
        assert items[0].prospect_id == "a"

    def test_status_individual_filter(self, tmp_path) -> None:
        prospects = [
            Prospect(prospect_id="a", workflow_status=WORKFLOW_STATUS_NEW),
            Prospect(
                prospect_id="b",
                workflow_status=WORKFLOW_STATUS_READY_TO_CONTACT,
            ),
        ]
        svc = _service(tmp_path, prospects)
        items = svc.list_items(
            today=_TODAY,
            status_filter=WORKFLOW_STATUS_READY_TO_CONTACT,
        )
        assert len(items) == 1
        assert items[0].prospect_id == "b"

    def test_priority_filter(self, tmp_path) -> None:
        prospects = [
            Prospect(prospect_id="a", priority=PRIORITY_NORMAL),
            Prospect(prospect_id="b", priority=PRIORITY_HIGH),
        ]
        svc = _service(tmp_path, prospects)
        items = svc.list_items(today=_TODAY, priority_filter=PRIORITY_HIGH)
        assert len(items) == 1
        assert items[0].prospect_id == "b"


    def test_overdue_filter(self, tmp_path) -> None:
        prospects = [
            Prospect(prospect_id="a", next_action_date="2026-08-14"),
            Prospect(prospect_id="b", next_action_date="2026-08-16"),
        ]
        svc = _service(tmp_path, prospects)
        items = svc.list_items(today=_TODAY, timing_filter=TIMING_OVERDUE)
        assert len(items) == 1
        assert items[0].prospect_id == "a"

    def test_due_today_filter(self, tmp_path) -> None:
        prospects = [
            Prospect(prospect_id="a", next_action_date="2026-08-15"),
            Prospect(prospect_id="b", next_action_date="2026-08-16"),
        ]
        svc = _service(tmp_path, prospects)
        items = svc.list_items(today=_TODAY, timing_filter=TIMING_DUE_TODAY)
        assert len(items) == 1
        assert items[0].prospect_id == "a"

    def test_upcoming_filter(self, tmp_path) -> None:
        prospects = [
            Prospect(prospect_id="a", next_action_date="2026-08-15"),
            Prospect(prospect_id="b", next_action_date="2026-08-16"),
        ]
        svc = _service(tmp_path, prospects)
        items = svc.list_items(today=_TODAY, timing_filter=TIMING_UPCOMING)
        assert len(items) == 1
        assert items[0].prospect_id == "b"

    def test_no_due_date_filter(self, tmp_path) -> None:
        prospects = [
            Prospect(prospect_id="a", next_action_date=None),
            Prospect(prospect_id="b", next_action_date="2026-08-16"),
        ]
        svc = _service(tmp_path, prospects)
        items = svc.list_items(today=_TODAY, timing_filter=TIMING_NO_DUE_DATE)
        assert len(items) == 1
        assert items[0].prospect_id == "a"

    def test_needs_attention_overdue(self, tmp_path) -> None:
        prospects = [
            Prospect(prospect_id="a", next_action_date="2026-08-14"),
            Prospect(prospect_id="b", next_action_date="2026-08-20"),
        ]
        svc = _service(tmp_path, prospects)
        items = svc.list_items(
            today=_TODAY,
            timing_filter=TIMING_FILTER_NEEDS_ATTENTION,
        )
        assert len(items) == 1
        assert items[0].prospect_id == "a"

    def test_needs_attention_due_today(self, tmp_path) -> None:
        prospects = [
            Prospect(prospect_id="a", next_action_date="2026-08-15"),
            Prospect(prospect_id="b", next_action_date="2026-08-20"),
        ]
        svc = _service(tmp_path, prospects)
        items = svc.list_items(
            today=_TODAY,
            timing_filter=TIMING_FILTER_NEEDS_ATTENTION,
        )
        assert len(items) == 1
        assert items[0].prospect_id == "a"

    def test_needs_attention_urgent_priority(self, tmp_path) -> None:
        prospects = [
            Prospect(
                prospect_id="a",
                priority=PRIORITY_URGENT,
                next_action_date="2026-08-20",
            ),
            Prospect(
                prospect_id="b",
                priority=PRIORITY_NORMAL,
                next_action_date="2026-08-20",
            ),
        ]
        svc = _service(tmp_path, prospects)
        items = svc.list_items(
            today=_TODAY,
            timing_filter=TIMING_FILTER_NEEDS_ATTENTION,
        )
        assert len(items) == 1
        assert items[0].prospect_id == "a"



class TestSideEffects:
    def test_filtering_does_not_mutate_prospect_data(self, tmp_path) -> None:
        prospects = [
            Prospect(
                prospect_id="a",
                company_name="A",
                workflow_status=WORKFLOW_STATUS_NEW,
                priority=PRIORITY_NORMAL,
                next_action_date="2026-08-20",
            ),
        ]
        store = _store(tmp_path, prospects)
        svc = ProspectFollowUpService(store)
        before = store.get("a").to_dict()
        svc.list_items(
            today=_TODAY,
            status_filter=STATUS_FILTER_ALL,
            priority_filter=PRIORITY_HIGH,
            timing_filter=TIMING_OVERDUE,
        )
        after = store.get("a").to_dict()
        assert before == after

    def test_list_items_does_not_recompute_opportunities(self, tmp_path) -> None:
        prospects = [
            Prospect(
                prospect_id="a",
                company_name="A",
                workflow_status=WORKFLOW_STATUS_FOLLOW_UP,
                next_action_date="2026-08-14",
            ),
        ]
        svc = _service(tmp_path, prospects)
        items = svc.list_items(today=_TODAY)
        assert len(items) == 1
        assert items[0].timing_state == TIMING_OVERDUE


class TestEmptyStates:
    def test_empty_store_returns_empty_list(self, tmp_path) -> None:
        svc = ProspectFollowUpService(
            ProspectStore(path=os.path.join(str(tmp_path), "prospects.json"))
        )
        assert svc.list_items(today=_TODAY) == []

    def test_no_matching_filters_returns_empty_list(self, tmp_path) -> None:
        prospects = [Prospect(prospect_id="a", workflow_status=WORKFLOW_STATUS_WON)]
        svc = _service(tmp_path, prospects)
        items = svc.list_items(today=_TODAY, status_filter=STATUS_FILTER_ACTIVE)
        assert items == []

