"""Regression tests for the Sprint 5F DI shrink of ``load_or_empty``.

The DI patch changed the missing-file semantics of three stores
(ProspectStore, OpportunityStore, ResearchQueueStore) from
"missing file => reset the in-memory snapshot to empty" to
"missing file => keep whatever in-memory snapshot exists".

Contract under test:
  A. backing file exists        -> load persisted state
  B. missing file + empty store -> return empty collection
  C. missing file + prepopulated in-memory store -> preserve that memory

Explicit ``load()`` on a missing file must still raise FileNotFoundError.
"""

from __future__ import annotations

import os

import pytest

from engine.opportunity import Opportunity
from gui.models.opportunity_store import OpportunityStore
from gui.models.prospect import Prospect
from gui.models.prospect_store import ProspectStore
from gui.models.research_job import ResearchJob
from gui.models.research_job_store import ResearchQueueStore


def _p(pid: str, name: str) -> Prospect:
    return Prospect(prospect_id=pid, company_name=name, category="roofing")


def _o(prospect_id: str, placement_id: str) -> Opportunity:
    return Opportunity(
        prospect_id=prospect_id, placement_id=placement_id, location_id="loc1"
    )


def _j(prospect_id: str) -> ResearchJob:
    return ResearchJob(prospect_id=prospect_id)


class TestProspectStoreLoadOrEmpty:
    def test_fresh_missing_file_returns_empty(self, tmp_path):
        store = ProspectStore(path=os.path.join(str(tmp_path), "p.json"))
        assert store.load_or_empty().prospects == []

    def test_missing_file_preserves_prepopulated_memory(self, tmp_path):
        store = ProspectStore(path=os.path.join(str(tmp_path), "p.json"))
        store.collection.prospects.append(_p("p_a", "Alpha"))
        coll = store.load_or_empty()
        assert [p.company_name for p in coll.prospects] == ["Alpha"]

    def test_existing_file_loads_over_memory(self, tmp_path):
        path = os.path.join(str(tmp_path), "p.json")
        store = ProspectStore(path=path)
        store.collection.prospects.append(_p("disk", "Persisted Co"))
        store.save()
        # Prepopulate a different in-memory snapshot, then load_or_empty.
        store2 = ProspectStore(path=path)
        store2.collection.prospects.append(_p("mem", "Memory Co"))
        coll = store2.load_or_empty()
        names = [p.company_name for p in coll.prospects]
        assert names == ["Persisted Co"], names

    def test_explicit_load_missing_raises(self, tmp_path):
        store = ProspectStore(path=os.path.join(str(tmp_path), "nope.json"))
        with pytest.raises(FileNotFoundError):
            store.load()


class TestOpportunityStoreLoadOrEmpty:
    def test_fresh_missing_file_returns_empty(self, tmp_path):
        store = OpportunityStore(path=os.path.join(str(tmp_path), "o.json"))
        assert store.load_or_empty().opportunities == []

    def test_missing_file_preserves_prepopulated_memory(self, tmp_path):
        store = OpportunityStore(path=os.path.join(str(tmp_path), "o.json"))
        store.collection.opportunities.append(_o("p1", "pl1"))
        coll = store.load_or_empty()
        assert [o.placement_id for o in coll.opportunities] == ["pl1"]

    def test_existing_file_loads_over_memory(self, tmp_path):
        path = os.path.join(str(tmp_path), "o.json")
        store = OpportunityStore(path=path)
        store.collection.opportunities.append(_o("p_disk", "pl_disk"))
        store.save()
        store2 = OpportunityStore(path=path)
        store2.collection.opportunities.append(_o("p_mem", "pl_mem"))
        coll = store2.load_or_empty()
        assert [
            (o.prospect_id, o.placement_id) for o in coll.opportunities
        ] == [("p_disk", "pl_disk")]


class TestResearchQueueStoreLoadOrEmpty:
    def test_fresh_missing_file_returns_empty(self, tmp_path):
        store = ResearchQueueStore(path=os.path.join(str(tmp_path), "q.json"))
        assert store.load_or_empty().jobs == []

    def test_missing_file_preserves_prepopulated_memory(self, tmp_path):
        store = ResearchQueueStore(path=os.path.join(str(tmp_path), "q.json"))
        store.collection.jobs.append(_j("p1"))
        coll = store.load_or_empty()
        assert [j.prospect_id for j in coll.jobs] == ["p1"]

    def test_existing_file_loads_over_memory(self, tmp_path):
        path = os.path.join(str(tmp_path), "q.json")
        store = ResearchQueueStore(path=path)
        store.collection.jobs.append(_j("p_disk"))
        store.save()
        store2 = ResearchQueueStore(path=path)
        store2.collection.jobs.append(_j("p_mem"))
        coll = store2.load_or_empty()
        assert [j.prospect_id for j in coll.jobs] == ["p_disk"]

    def test_explicit_load_missing_raises(self, tmp_path):
        store = ResearchQueueStore(path=os.path.join(str(tmp_path), "nope.json"))
        with pytest.raises(FileNotFoundError):
            store.load()