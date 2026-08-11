"""Sprint 5C OpportunityStore persistence tests.

Covers save/load, atomic writes, corruption handling, deterministic ordering,
filters, archiving, and the critical idempotent upsert behavior
((prospect_id, placement_id) -> ONE durable Opportunity).
"""

from __future__ import annotations

import json
import os

import pytest

from engine.opportunity import (
    STATUS_ARCHIVED,
    STATUS_NEW,
    STATUS_RECOMMENDED,
    STATUS_SELECTED,
    Opportunity,
)
from gui.models.opportunity_store import (
    OpportunityCollection,
    OpportunityCorruptionError,
    OpportunityStore,
)


def make_opp(
    prospect_id: str = "p1",
    placement_id: str = "pl1",
    score: int = 0,
    eligible: bool = False,
    market_id: str = "",
    location_id: str = "",
    **kw,
) -> Opportunity:
    return Opportunity(
        prospect_id=prospect_id,
        placement_id=placement_id,
        location_id=location_id or "loc1",
        market_id=market_id,
        eligible=eligible,
        score=score,
        score_components={"category_fit": score},
        reasons=["Roofing category allowed"] if eligible else [],
        **kw,
    )


class TestStorePersistence:
    def test_save_load(self, tmp_path):
        path = os.path.join(str(tmp_path), "opps.json")
        store = OpportunityStore(path=path)
        a = make_opp("p1", "pl1", score=90, eligible=True)
        b = make_opp("p2", "pl1", score=50, eligible=True)
        store.create(a)
        store.create(b)
        store.save()

        reloaded = OpportunityStore(path=path).load()
        reloader = OpportunityStore(path=path)
        reloader.load()
        assert len(reloader.list()) == 2
        assert reloader.get(a.opportunity_id).score == 90

    def test_atomic_save_no_leftover_tmp(self, tmp_path):
        path = os.path.join(str(tmp_path), "opps.json")
        store = OpportunityStore(path=path)
        store.create(make_opp(score=10))
        store.save()
        assert os.path.isfile(path)
        assert not os.path.isfile(path + ".tmp")

    def test_corrupted_json(self, tmp_path):
        path = os.path.join(str(tmp_path), "opps.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{ this is not json !!!")
        with pytest.raises(OpportunityCorruptionError):
            OpportunityStore(path=path).load()

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            OpportunityStore(path=os.path.join(str(tmp_path), "nope.json")).load()

    def test_deterministic_list(self, tmp_path):
        store = OpportunityStore(path=os.path.join(str(tmp_path), "o.json"))
        store.create(make_opp("p1", "pl1"))
        store.create(make_opp("p2", "pl1"))
        ids = [o.opportunity_id for o in store.list()]
        assert ids == sorted(ids)

    def test_filter_by_prospect(self, tmp_path):
        store = OpportunityStore(path=os.path.join(str(tmp_path), "o.json"))
        store.create(make_opp("p1", "pl1"))
        store.create(make_opp("p2", "pl1"))
        assert {o.prospect_id for o in store.by_prospect("p1")} == {"p1"}

    def test_filter_by_placement(self, tmp_path):
        store = OpportunityStore(path=os.path.join(str(tmp_path), "o.json"))
        store.create(make_opp("p1", "pl1"))
        store.create(make_opp("p1", "pl2", market_id="m9"))
        assert {o.placement_id for o in store.by_placement("pl2")} == {"pl2"}

    def test_filter_by_market(self, tmp_path):
        store = OpportunityStore(path=os.path.join(str(tmp_path), "o.json"))
        store.create(make_opp("p1", "pl1", market_id="m1"))
        store.create(make_opp("p2", "pl1", market_id="m2"))
        assert {o.prospect_id for o in store.by_market("m1")} == {"p1"}

    def test_filter_by_location(self, tmp_path):
        store = OpportunityStore(path=os.path.join(str(tmp_path), "o.json"))
        store.create(make_opp("p1", "pl1", market_id="m1", location_id="l1"))
        store.create(make_opp("p2", "pl1", market_id="m2", location_id="l2"))
        assert {o.prospect_id for o in store.by_location("l2")} == {"p2"}

    def test_filter_eligible(self, tmp_path):
        store = OpportunityStore(path=os.path.join(str(tmp_path), "o.json"))
        store.create(make_opp("p1", "pl1", eligible=True))
        store.create(make_opp("p2", "pl1", eligible=False))
        assert {o.prospect_id for o in store.eligible_only()} == {"p1"}

    def test_filter_by_status(self, tmp_path):
        store = OpportunityStore(path=os.path.join(str(tmp_path), "o.json"))
        store.create(make_opp("p1", "pl1", status=STATUS_RECOMMENDED))
        store.create(make_opp("p2", "pl1", status=STATUS_NEW))
        assert {o.prospect_id for o in store.by_status(STATUS_RECOMMENDED)} == {"p1"}

    def test_archive(self, tmp_path):
        store = OpportunityStore(path=os.path.join(str(tmp_path), "o.json"))
        store.create(make_opp("p1", "pl1", eligible=True))
        oid = store.list()[0].opportunity_id
        archived = store.archive(oid)
        assert archived.status == STATUS_ARCHIVED
class TestUpsert:
    def test_same_pair_reuses_id(self, tmp_path):
        store = OpportunityStore(path=os.path.join(str(tmp_path), "o.json"))
        first = store.upsert(make_opp("p1", "pl1", score=80, eligible=True))
        original_id = first.opportunity_id
        second = store.upsert(make_opp("p1", "pl1", score=95, eligible=True))
        assert len(store.list()) == 1
        assert second.opportunity_id == original_id

    def test_different_pair_distinct(self, tmp_path):
        store = OpportunityStore(path=os.path.join(str(tmp_path), "o.json"))
        a = store.upsert(make_opp("p1", "pl1"))
        b = store.upsert(make_opp("p1", "pl2"))
        assert len(store.list()) == 2
        assert a.opportunity_id != b.opportunity_id

    def test_recompute_updates_score(self, tmp_path):
        store = OpportunityStore(path=os.path.join(str(tmp_path), "o.json"))
        first = store.upsert(make_opp("p1", "pl1", score=40, eligible=True))
        second = store.upsert(make_opp("p1", "pl1", score=88, eligible=True))
        assert second.score == 88
        assert store.get(first.opportunity_id).score == 88

    def test_created_at_preserved(self, tmp_path):
        store = OpportunityStore(path=os.path.join(str(tmp_path), "o.json"))
        first = store.upsert(make_opp("p1", "pl1", score=10))
        stored = store.upsert(make_opp("p1", "pl1", score=99))
        assert stored.created_at == first.created_at

    def test_modified_at_changes(self, tmp_path):
        store = OpportunityStore(path=os.path.join(str(tmp_path), "o.json"))
        first = store.upsert(make_opp("p1", "pl1", score=10))
        # Pin a far-past modified_at, then recompute -> touch() must advance it.
        first.modified_at = "2000-01-01T00:00:00+00:00"
        stored = store.upsert(make_opp("p1", "pl1", score=99))
        assert stored.modified_at != "2000-01-01T00:00:00+00:00"

    def test_manual_notes_preserved(self, tmp_path):
        store = OpportunityStore(path=os.path.join(str(tmp_path), "o.json"))
        store.upsert(make_opp("p1", "pl1", score=50, notes="Call back Tuesday"))
        stored = store.upsert(make_opp("p1", "pl1", score=70, notes=""))
        assert stored.notes == "Call back Tuesday"

    def test_manual_status_preserved(self, tmp_path):
        store = OpportunityStore(path=os.path.join(str(tmp_path), "o.json"))
        store.upsert(make_opp("p1", "pl1", score=50, status=STATUS_SELECTED))
        stored = store.upsert(make_opp("p1", "pl1", score=70, eligible=True))
        # SELECTED is a manual status -> preserved across recompute
        assert stored.status == STATUS_SELECTED

    def test_auto_status_adopted(self, tmp_path):
        store = OpportunityStore(path=os.path.join(str(tmp_path), "o.json"))
        store.upsert(make_opp("p1", "pl1", score=50, status=STATUS_NEW))
        # a recomputed (engine-produced) opportunity carries RECOMMENDED
        stored = store.upsert(
            make_opp("p1", "pl1", score=70, eligible=True, status=STATUS_RECOMMENDED)
        )
        assert stored.status == STATUS_RECOMMENDED


class TestForwardCompat:
    def test_collection_unknown_fields_safe(self):
        coll = OpportunityCollection.from_dict(
            {"schema_version": 1, "opportunities": [{"prospect_id": "p1", "weird": 1}]}
        )
        assert len(coll.opportunities) == 1

    def test_collection_round_trip(self, tmp_path):
        store = OpportunityStore(path=os.path.join(str(tmp_path), "o.json"))
        store.create(make_opp("p1", "pl1", eligible=True, score=77))
        data = store.collection.to_dict()
        restored = OpportunityCollection.from_dict(data)
        assert restored.to_dict() == data

    def test_no_pickle(self):
        import gui.models.opportunity_store as mod
        src = open(mod.__file__, encoding="utf-8").read()
        bad = [l for l in src.splitlines() if l.lstrip().startswith("import pickle")]
        assert not bad
        assert "import json" in src
