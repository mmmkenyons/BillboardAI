#!/usr/bin/env python
"""Sprint 5K verifier — opportunity snapshot and traceability foundation."""

from __future__ import annotations

import os
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def verify() -> int:
    root = tempfile.mkdtemp(prefix="sprint5k_verify_")
    print(f"VERIFIER ROOT: {root}")
    print("SYNTHETIC VERIFICATION DATA\n")
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

    try:
        from engine.opportunity import OpportunityEngine
        from gui.models.inventory import Location, Market, Placement, Retailer, STATUS_AVAILABLE, STATUS_SOLD
        from gui.models.inventory_store import Inventory, InventoryStore
        from gui.models.mockup_result import MockupResult
        from gui.models.opportunity_store import OpportunityStore
        from gui.models.project_store import ProjectStore
        from gui.models.prospect import Prospect
        from gui.models.prospect_generation_store import ProspectGenerationStore
        from gui.models.prospect_store import ProspectStore
        from gui.services.opportunity_service import OpportunityService
        from gui.services.prospect_generation import ProspectGenerationService
        from gui.services.prospect_opportunity_workspace import ProspectOpportunityWorkspaceService
        from gui.services.store_recommendation import StoreRecommendationService

        def build_runtime(name: str):
            scenario_root = os.path.join(root, name)
            os.makedirs(scenario_root, exist_ok=True)
            prospects = ProspectStore(path=os.path.join(scenario_root, "prospects.json"))
            jobs = ProspectGenerationStore(path=os.path.join(scenario_root, "jobs.json"))
            projects = ProjectStore(root=os.path.join(scenario_root, "projects"))
            inventory = InventoryStore(path=os.path.join(scenario_root, "inventory.json"))
            opportunities = OpportunityStore(path=os.path.join(scenario_root, "opportunities.json"))
            generate_calls: list[str] = []

            def fake_generate(request):
                generate_calls.append(request.url)
                city = ""
                if request.opportunity_context is not None:
                    city = " ".join(str(request.opportunity_context.city or "").split()).strip()
                category = ""
                if request.url.endswith("abc.com"):
                    category = "roofing"
                elif request.url.endswith("xyz.com"):
                    category = "dentist"
                if city and category == "roofing":
                    headline = f"Trusted Local Service In {city}"
                elif city and category == "dentist":
                    headline = f"Trusted Dental Care In {city}"
                else:
                    headline = "Local Experts"
                return MockupResult(
                    success=True,
                    website=request.url,
                    output_path=request.output_path,
                    preview_path=request.output_path,
                    headline=headline,
                    cta="Call Today",
                    extra={
                        "render_context": {
                            "company_name": "Verifier Prospect",
                            "headline": headline,
                            "cta": "Call Today",
                            "template": request.template,
                            "scene_template": request.opportunity_context.scene_template if request.opportunity_context else "cart_corral",
                            "opportunity_context": request.opportunity_context.to_dict() if request.opportunity_context else {},
                        }
                    },
                )

            opp_service = OpportunityService(
                prospect_store=prospects,
                project_store=projects,
                inventory_store=inventory,
                opportunity_store=opportunities,
            )
            rec_service = StoreRecommendationService(opportunity_service=opp_service, inventory_store=inventory)
            workspace = ProspectOpportunityWorkspaceService(
                prospect_store=prospects,
                project_store=projects,
                inventory_store=inventory,
                opportunity_service=opp_service,
                store_recommendation_service=rec_service,
            )
            service = ProspectGenerationService(
                prospect_store=prospects,
                job_store=jobs,
                project_store=projects,
                generation_callable=fake_generate,
                default_output_root=scenario_root,
                opportunity_workspace_service=workspace,
            )
            return {
                "root": scenario_root,
                "prospects": prospects,
                "jobs": jobs,
                "projects": projects,
                "inventory": inventory,
                "opportunities": opportunities,
                "opp_service": opp_service,
                "rec_service": rec_service,
                "workspace": workspace,
                "service": service,
                "generate_calls": generate_calls,
            }

        def seed_inventory(runtime, placements, locations, retailers=None, markets=None):
            inventory = runtime["inventory"]
            inventory.inventory.retailers.extend(retailers or [])
            inventory.inventory.markets.extend(markets or [])
            inventory.inventory.locations.extend(locations)
            inventory.inventory.placements.extend(placements)
            inventory.save()

        # A. Generic fixture
        generic_rt = build_runtime("generic")
        market = Market(market_id="m1", name="Denver Metro")
        retailer = Retailer(retailer_id="ret1", name="King Soopers")
        location = Location(location_id="loc_generic_other", retailer_id="ret1", market_id="m1", name="King Soopers #999", store_number="999", city="Denver", state="CO")
        placement = Placement(placement_id="pl_generic_other", location_id="loc_generic_other", name="Other Cart Corral", placement_type="cart_corral", scene_template="cart_corral", exclusive_category="roofing")
        seed_inventory(generic_rt, [placement], [location], [retailer], [market])
        generic_prospect = Prospect(prospect_id="g", company_name="Generic Prospect", website="https://generic.com", category="dentist", city="Aurora", state="CO")
        generic_rt["prospects"].create(generic_prospect)
        generic_rt["prospects"].save()
        generic_rt["opp_service"].recommend_for_prospect("g")
        generic = generic_rt["service"].create_job("g", template="dentist")
        check("generic eligible without recommendation", generic.job is not None and generic.job.opportunity_id == "" and generic.job.location_id == "" and generic.job.placement_id == "" and generic.job.opportunity_context is None)
        generic_run = generic_rt["service"].run_job(generic.job.id) if generic.job is not None else None
        if generic_run is not None:
            generic_project = generic_rt["projects"].load(generic_run.project_id)
            check("generic project metadata", generic_project.metadata.get("prospect_id") == "g" and generic_project.metadata.get("generation_job_id") == generic_run.id and "opportunity_id" not in generic_project.metadata and "location_id" not in generic_project.metadata and "placement_id" not in generic_project.metadata)
            generic_concept = generic_project.concepts[-1] if generic_project.concepts else None
            check("generic creative unchanged", generic_concept is not None and generic_concept.headline == "Local Experts" and generic_concept.cta == "Call Today")

        # B. Wrong-prospect rejection fixture
        wrong_rt = build_runtime("wrong_prospect")
        market = Market(market_id="m1", name="Denver Metro")
        retailer_a = Retailer(retailer_id="ret1", name="King Soopers")
        retailer_b = Retailer(retailer_id="ret2", name="Safeway")
        location_a = Location(location_id="loc_a", retailer_id="ret1", market_id="m1", name="King Soopers #123", store_number="123", city="Castle Rock", state="CO")
        location_b = Location(location_id="loc_b", retailer_id="ret2", market_id="m1", name="Safeway #200", store_number="200", city="Parker", state="CO")
        placement_a = Placement(placement_id="pl_a", location_id="loc_a", name="Front Cart Corral A", placement_type="cart_corral", scene_template="cart_corral", exclusive_category="roofing")
        placement_b = Placement(placement_id="pl_b", location_id="loc_b", name="Front Cart Corral B", placement_type="cart_corral", scene_template="cart_corral_b", exclusive_category="dentist")
        seed_inventory(wrong_rt, [placement_a, placement_b], [location_a, location_b], [retailer_a, retailer_b], [market])
        prospect_a = Prospect(prospect_id="a", company_name="ABC Roofing", website="https://abc.com", category="roofing", city="Castle Rock", state="CO")
        prospect_b = Prospect(prospect_id="b", company_name="XYZ Dental", website="https://xyz.com", category="dentist", city="Parker", state="CO")
        wrong_rt["prospects"].create(prospect_a)
        wrong_rt["prospects"].create(prospect_b)
        wrong_rt["prospects"].save()
        opps_a = wrong_rt["opp_service"].recommend_for_prospect(prospect_a.prospect_id)
        opps_b = wrong_rt["opp_service"].recommend_for_prospect(prospect_b.prospect_id)
        opportunity_a = opps_a[0]
        opportunity_b = opps_b[0]
        prospect_a_id = prospect_a.prospect_id
        prospect_b_id = prospect_b.prospect_id
        opportunity_a_id = opportunity_a.opportunity_id
        opportunity_b_id = opportunity_b.opportunity_id
        check("wrong-prospect canonical setup A", opportunity_a.prospect_id == prospect_a_id)
        check("wrong-prospect canonical setup B", opportunity_b.prospect_id == prospect_b_id and opportunity_b.prospect_id != prospect_a_id)
        before_jobs = len(wrong_rt["service"].list_jobs())
        before_projects = len(wrong_rt["projects"].list())
        wrong = wrong_rt["service"].create_job(prospect_id=prospect_a_id, opportunity_id=opportunity_b_id)
        reason = wrong.reasons[0] if wrong.reasons else ""
        check("wrong-prospect rejection", wrong.job is None and "does not belong to prospect" in reason.lower(), reason)
        check("wrong-prospect no job side effect", len(wrong_rt["service"].list_jobs()) == before_jobs)
        check("wrong-prospect no project side effect", len(wrong_rt["projects"].list()) == before_projects)
        check("wrong-prospect no generation side effect", wrong_rt["generate_calls"] == [])

        # C/D/E/F. Recommendation flip, immutability, restart, traceability
        flip_rt = build_runtime("recommendation_flip")
        market = Market(market_id="m1", name="Denver Metro")
        retailer = Retailer(retailer_id="ret1", name="King Soopers")
        location_a = Location(location_id="loc1", retailer_id="ret1", market_id="m1", name="King Soopers #123", store_number="123", city="Castle Rock", state="CO")
        location_b = Location(location_id="loc2", retailer_id="ret1", market_id="m1", name="King Soopers #456", store_number="456", city="Parker", state="CO")
        placement_a = Placement(placement_id="pl1", location_id="loc1", name="Front Cart Corral A", placement_type="cart_corral", scene_template="cart_corral", exclusive_category="roofing")
        placement_b = Placement(placement_id="pl2", location_id="loc2", name="Front Cart Corral B", placement_type="cart_corral", scene_template="cart_corral_alt", exclusive_category="roofing")
        seed_inventory(flip_rt, [placement_a, placement_b], [location_a, location_b], [retailer], [market])
        prospect = Prospect(prospect_id="a", company_name="ABC Roofing", website="https://abc.com", category="roofing", city="Castle Rock", state="CO")
        flip_rt["prospects"].create(prospect)
        flip_rt["prospects"].save()
        engine = OpportunityEngine()
        initial_ranked = flip_rt["opp_service"].recommend_for_prospect("a")
        best_before = flip_rt["rec_service"].recommend("a", limit=1)
        check("best before is Store A", bool(best_before) and best_before[0].location_id == "loc1", best_before[0].location_id if best_before else "none")
        check("flip fixture initial eligible set", len([opp for opp in initial_ranked if opp.eligible]) == 2)
        managed_pl1 = flip_rt["inventory"].inventory.get_placement("pl1")
        before_map = {(opp.location_id, opp.placement_id): opp for opp in flip_rt["opp_service"].by_prospect("a")}
        opp_a_before = before_map.get(("loc1", "pl1"))
        opp_b_before = before_map.get(("loc2", "pl2"))
        print("BEFORE opportunity map:", [(opp.opportunity_id, opp.location_id, opp.placement_id, opp.eligible, opp.score) for opp in sorted(before_map.values(), key=lambda item: (item.location_id, item.placement_id))])
        print("OBJECT identity:", {"placement_a_id": placement_a.placement_id, "managed_pl1_id": managed_pl1.placement_id if managed_pl1 else None, "id_placement_a": id(placement_a), "id_managed_pl1": id(managed_pl1) if managed_pl1 else None, "same_object": placement_a is managed_pl1, "same_dict": placement_a.to_dict() == managed_pl1.to_dict() if managed_pl1 else False})
        print("BEFORE placement_a:", placement_a.placement_id, placement_a.status, repr(placement_a.status), type(placement_a.status))
        print("BEFORE managed_pl1:", managed_pl1.placement_id if managed_pl1 else None, managed_pl1.status if managed_pl1 else None, repr(managed_pl1.status) if managed_pl1 else None, type(managed_pl1.status) if managed_pl1 else None)
        direct_before = engine.evaluate(prospect, placement_a, location_a)
        print("DIRECT before evaluate:", {"status": placement_a.status, "eligible": direct_before.eligible, "score": direct_before.score, "reasons": list(direct_before.reasons)})
        check("flip direct before eligible", direct_before.eligible is True, f"status={placement_a.status!r}; score={direct_before.score}; reasons={direct_before.reasons}")
        check("canonical opp ids distinct before", opp_a_before is not None and opp_b_before is not None and opp_a_before.opportunity_id != opp_b_before.opportunity_id, f"opp_a_id={opp_a_before.opportunity_id if opp_a_before else 'none'}; opp_b_id={opp_b_before.opportunity_id if opp_b_before else 'none'}")
        placement_direct_roundtrip = Placement.from_dict(Placement(placement_id="roundtrip_pl", location_id="roundtrip_loc", status=STATUS_SOLD).to_dict())
        print("PLACEMENT direct roundtrip:", placement_direct_roundtrip.status)
        standalone_inventory = Inventory(
            retailers=[Retailer(retailer_id="rt_round", name="Round Retailer")],
            markets=[Market(market_id="mk_round", name="Round Market")],
            locations=[Location(location_id="loc_round", retailer_id="rt_round", market_id="mk_round", name="Round Location")],
            placements=[Placement(placement_id="pl_round", location_id="loc_round", name="Round Placement", status=STATUS_SOLD)],
        )
        standalone_data = standalone_inventory.to_dict()
        standalone_serialized_status = next((p.get("status") for p in standalone_data.get("placements", []) if p.get("placement_id") == "pl_round"), None)
        restored_inventory = Inventory.from_dict(standalone_data)
        restored_roundtrip_pl = restored_inventory.get_placement("pl_round")
        print("NESTED inventory roundtrip:", {"serialized_status": standalone_serialized_status, "restored_status": restored_roundtrip_pl.status if restored_roundtrip_pl else None})
        standalone_store_path = os.path.join(flip_rt["root"], "standalone_inventory.json")
        standalone_store = InventoryStore(path=standalone_store_path)
        standalone_store.set_inventory(standalone_inventory)
        standalone_store.save()
        with open(standalone_store_path, "r", encoding="utf-8") as handle:
            standalone_disk = handle.read()
        standalone_loaded = standalone_store.load()
        standalone_loaded_pl = standalone_loaded.get_placement("pl_round")
        print("STORE roundtrip:", {"disk_contains_sold": '"status": "SOLD"' in standalone_disk, "reloaded_status": standalone_loaded_pl.status if standalone_loaded_pl else None})
        automatic = flip_rt["service"].create_job("a")
        check("job1 snapshots Store A", automatic.job is not None and automatic.job.location_id == "loc1" and automatic.job.opportunity_context is not None and automatic.job.opportunity_context.scene_template == "cart_corral")
        check("job1 snapshots city", automatic.job is not None and automatic.job.opportunity_context is not None and automatic.job.opportunity_context.city == "Castle Rock")
        job1 = automatic.job
        assert job1 is not None
        job1_id = job1.id
        job1_opportunity_id = job1.opportunity_id
        job1_location_id = job1.location_id
        job1_placement_id = job1.placement_id
        placement_a.status = STATUS_SOLD
        print("DETACHED mutation before managed fix:", placement_a.status, repr(placement_a.status), type(placement_a.status))
        check("flip status constant semantics", isinstance(placement_a.status, str) and isinstance(STATUS_AVAILABLE, str) and isinstance(STATUS_SOLD, str) and STATUS_AVAILABLE == "AVAILABLE" and STATUS_SOLD == "SOLD", f"placement_status_type={type(placement_a.status)}; available={STATUS_AVAILABLE!r}/{type(STATUS_AVAILABLE)}; sold={STATUS_SOLD!r}/{type(STATUS_SOLD)}")
        direct_after_mutation = engine.evaluate(prospect, placement_a, location_a)
        print("DIRECT after detached mutation evaluate:", {"status": placement_a.status, "eligible": direct_after_mutation.eligible, "score": direct_after_mutation.score, "reasons": list(direct_after_mutation.reasons)})
        check("flip direct after sold ineligible", direct_after_mutation.eligible is False, f"status={placement_a.status!r}; score={direct_after_mutation.score}; reasons={direct_after_mutation.reasons}")
        managed_pl1 = flip_rt["inventory"].inventory.get_placement("pl1")
        print("MANAGED before mutation:", managed_pl1.status if managed_pl1 else None)
        if managed_pl1 is not None:
            managed_pl1.status = STATUS_SOLD
        print("MANAGED after mutation before save:", managed_pl1.status if managed_pl1 else None, repr(managed_pl1.status) if managed_pl1 else None, type(managed_pl1.status) if managed_pl1 else None)
        check("managed pl1 sold before save", managed_pl1 is not None and managed_pl1.status == STATUS_SOLD, f"managed_status={managed_pl1.status if managed_pl1 else 'missing'}")
        in_memory_pl1 = flip_rt["inventory"].inventory.get_placement("pl1")
        check("inventory snapshot sees sold before save", in_memory_pl1 is not None and in_memory_pl1.status == STATUS_SOLD, f"snapshot_status={in_memory_pl1.status if in_memory_pl1 else 'missing'}")
        direct_after_managed_mutation = engine.evaluate(prospect, managed_pl1, location_a) if managed_pl1 is not None else None
        print("DIRECT after managed mutation evaluate:", {"status": getattr(managed_pl1, 'status', None), "eligible": getattr(direct_after_managed_mutation, 'eligible', None), "score": getattr(direct_after_managed_mutation, 'score', None), "reasons": list(getattr(direct_after_managed_mutation, 'reasons', []) or [])})
        flip_rt["inventory"].save()
        inventory_dict_after_save = flip_rt["inventory"].inventory.to_dict()
        serialized_pl1_status = next((p.get("status") for p in inventory_dict_after_save.get("placements", []) if p.get("placement_id") == "pl1"), None)
        inventory_file_path = os.path.join(flip_rt["root"], "inventory.json")
        with open(inventory_file_path, "r", encoding="utf-8") as handle:
            inventory_json_text = handle.read()
        persisted_status_snippet = '"status": "SOLD"' if '"placement_id": "pl1"' in inventory_json_text and '"status": "SOLD"' in inventory_json_text else inventory_json_text
        reloaded_inventory = flip_rt["inventory"].load()
        reloaded_pl1 = next((p for p in reloaded_inventory.placements if p.location_id == "loc1" and p.placement_id == "pl1"), None)
        print("RELOADED placement pl1:", reloaded_pl1.status if reloaded_pl1 else None, repr(reloaded_pl1.status) if reloaded_pl1 else None, type(reloaded_pl1.status) if reloaded_pl1 else None)
        print("SERIALIZATION trace:", {"managed_before_save": managed_pl1.status if managed_pl1 else None, "inventory_to_dict_status": serialized_pl1_status, "disk_has_sold": '"status": "SOLD"' in inventory_json_text, "from_dict_status": reloaded_pl1.status if reloaded_pl1 else None})
        check("flip sold survives save load", reloaded_pl1 is not None and reloaded_pl1.status == STATUS_SOLD, f"reloaded_status={reloaded_pl1.status if reloaded_pl1 else 'missing'}")
        recomputed_count = flip_rt["opp_service"].recompute(prospect_id="a")
        resolved_inventory = flip_rt["inventory"]._inventory
        resolved_pl1 = next((p for p in resolved_inventory.placements if p.location_id == "loc1" and p.placement_id == "pl1"), None)
        resolved_loc1 = next((loc for loc in resolved_inventory.locations if loc.location_id == "loc1"), None)
        print("RECOMPUTE resolved placement pl1:", resolved_pl1.status if resolved_pl1 else None, repr(resolved_pl1.status) if resolved_pl1 else None, type(resolved_pl1.status) if resolved_pl1 else None)
        direct_after_recompute = engine.evaluate(prospect, resolved_pl1, resolved_loc1) if resolved_pl1 is not None else None
        print("DIRECT after reload/recompute evaluate:", {"status": getattr(resolved_pl1, "status", None), "eligible": getattr(direct_after_recompute, "eligible", None), "score": getattr(direct_after_recompute, "score", None), "reasons": list(getattr(direct_after_recompute, "reasons", []) or [])})
        refreshed_ranked = flip_rt["opp_service"].recommend_for_prospect("a")
        best_after = flip_rt["rec_service"].recommend("a", limit=1)
        after_map = {(opp.location_id, opp.placement_id): opp for opp in flip_rt["opp_service"].by_prospect("a")}
        opp_a_after = after_map.get(("loc1", "pl1"))
        opp_b_after = after_map.get(("loc2", "pl2"))
        print("AFTER opportunity map:", [(opp.opportunity_id, opp.location_id, opp.placement_id, opp.eligible, opp.score) for opp in sorted(after_map.values(), key=lambda item: (item.location_id, item.placement_id))])
        print("CANONICAL ids:", {"opp_a_before": getattr(opp_a_before, "opportunity_id", None), "opp_b_before": getattr(opp_b_before, "opportunity_id", None), "opp_a_after": getattr(opp_a_after, "opportunity_id", None), "opp_b_after": getattr(opp_b_after, "opportunity_id", None), "expected_b_opportunity_id": getattr(opp_b_after, "opportunity_id", None), "expected_b_location_id": getattr(opp_b_after, "location_id", None), "expected_b_placement_id": getattr(opp_b_after, "placement_id", None)})
        eligible_after = [opp for opp in refreshed_ranked if opp.eligible]
        best_after_message = (
            f"best={best_after[0].location_id if best_after else 'none'}; "
            f"eligible={[ (opp.location_id, opp.placement_id, opp.eligibility_reasons) for opp in eligible_after ]}; "
            f"recomputed={recomputed_count}; "
            f"store_ids={(id(flip_rt['inventory']), id(flip_rt['rec_service']._inventory_store), id(flip_rt['opp_service'].inventory_store), id(flip_rt['workspace']._rec_svc._inventory_store))}"
        )
        check("best after is Store B", bool(best_after) and best_after[0].location_id == "loc2", best_after_message)
        restarted = ProspectGenerationService(
            prospect_store=flip_rt["prospects"],
            job_store=ProspectGenerationStore(path=flip_rt["jobs"].path),
            project_store=flip_rt["projects"],
            generation_callable=flip_rt["service"]._generate,
            default_output_root=flip_rt["root"],
            opportunity_workspace_service=flip_rt["workspace"],
        )
        reloaded_job1 = restarted.job_store.get(job1_id)
        check("job1 immutability before run", reloaded_job1 is not None and reloaded_job1.opportunity_id == job1_opportunity_id and reloaded_job1.location_id == job1_location_id and reloaded_job1.placement_id == job1_placement_id and reloaded_job1.opportunity_context is not None and reloaded_job1.opportunity_context.placement_id == job1_placement_id and reloaded_job1.opportunity_context.scene_template == "cart_corral")
        completed_job1 = restarted.run_job(job1_id)
        check("job1 succeeded", completed_job1.status == "SUCCEEDED")
        if completed_job1.project_id:
            completed_project1 = flip_rt["projects"].load(completed_job1.project_id)
            concept1 = completed_project1.concepts[-1] if completed_project1.concepts else None
            rc1 = completed_project1.render_context
            headline1 = concept1.headline if concept1 is not None else ""
            check("job1 creative uses snapshotted city", "Castle Rock" in headline1, headline1)
            check("job1 render context carries city", rc1.get("opportunity_context", {}).get("city") == "Castle Rock")
            combined_copy = f"{headline1} {concept1.cta if concept1 is not None else ''}".lower()
            check("no retailer leaked into creative", "king soopers" not in combined_copy, combined_copy)
            check("no store number leaked into creative", "#123" not in combined_copy and "123" not in combined_copy, combined_copy)
            check("no sales metadata leaked into creative", all(token not in combined_copy for token in ("12000", "score", "distance", "opportunity_", "location_id", "placement_id")), combined_copy)
        job2 = restarted.create_job("a")
        best_after_opp_id = opp_b_after.opportunity_id if opp_b_after is not None else ""
        check("job2 uses new best", job2.job is not None and job2.job.location_id == "loc2" and job2.job.opportunity_id == best_after_opp_id and job2.job.id != job1_id, f"job2_location={job2.job.location_id if job2.job else 'none'}; job2_opp={job2.job.opportunity_id if job2.job else 'none'}; expected={best_after_opp_id}")
        check("job2 snapshots new city", job2.job is not None and job2.job.opportunity_context is not None and job2.job.opportunity_context.city == "Parker")
        reloaded_job1_after = restarted.job_store.get(job1_id)
        reloaded_job2_after = restarted.job_store.get(job2.job.id) if job2.job is not None else None
        check("job1 remains A after job2", reloaded_job1_after is not None and reloaded_job1_after.location_id == "loc1" and reloaded_job1_after.opportunity_id == job1_opportunity_id)
        check("job2 persists as B", reloaded_job2_after is not None and reloaded_job2_after.location_id == "loc2" and reloaded_job2_after.opportunity_id == best_after_opp_id, f"reloaded_job2_location={reloaded_job2_after.location_id if reloaded_job2_after else 'none'}; reloaded_job2_opp={reloaded_job2_after.opportunity_id if reloaded_job2_after else 'none'}; expected={best_after_opp_id}")
        check("project traceability job1", bool(completed_job1.project_id) and flip_rt["projects"].load(completed_job1.project_id).metadata.get("prospect_id") == "a" and flip_rt["projects"].load(completed_job1.project_id).metadata.get("opportunity_id") == job1_opportunity_id and flip_rt["projects"].load(completed_job1.project_id).metadata.get("location_id") == "loc1" and flip_rt["projects"].load(completed_job1.project_id).metadata.get("placement_id") == "pl1")
        legacy_path = os.path.join(flip_rt["root"], "legacy_jobs.json")
        with open(legacy_path, "w", encoding="utf-8") as handle:
            handle.write('{\n  "schema_version": 1,\n  "jobs": [{\n    "id": "legacy",\n    "prospect_id": "b",\n    "website": "https://xyz.com",\n    "template": "dentist",\n    "status": "QUEUED",\n    "created_at": "2026-01-01T00:00:00"\n  }]\n}')
        legacy_store = ProspectGenerationStore(path=legacy_path)
        legacy = legacy_store.get("legacy")
        check("old-5J backward compatibility", legacy is not None and legacy.opportunity_context is None and legacy.opportunity_id == "")

        # G. Cross-prospect isolation fixture
        cross_rt = build_runtime("cross_prospect")
        market = Market(market_id="m1", name="Denver Metro")
        retailer_a = Retailer(retailer_id="ret1", name="King Soopers")
        retailer_b = Retailer(retailer_id="ret2", name="Safeway")
        location_a = Location(location_id="loc_a", retailer_id="ret1", market_id="m1", name="King Soopers #123", store_number="123", city="Castle Rock", state="CO")
        location_b = Location(location_id="loc_b", retailer_id="ret2", market_id="m1", name="Safeway #200", store_number="200", city="Parker", state="CO")
        placement_a = Placement(placement_id="pl_a", location_id="loc_a", name="Front Cart Corral A", placement_type="cart_corral", scene_template="cart_corral", exclusive_category="roofing")
        placement_b = Placement(placement_id="pl_b", location_id="loc_b", name="Front Cart Corral B", placement_type="cart_corral", scene_template="cart_corral_b", exclusive_category="dentist")
        seed_inventory(cross_rt, [placement_a, placement_b], [location_a, location_b], [retailer_a, retailer_b], [market])
        prospect_a = Prospect(prospect_id="a", company_name="ABC Roofing", website="https://abc.com", category="roofing", city="Castle Rock", state="CO")
        prospect_b = Prospect(prospect_id="b", company_name="XYZ Dental", website="https://xyz.com", category="dentist", city="Parker", state="CO")
        cross_rt["prospects"].create(prospect_a)
        cross_rt["prospects"].create(prospect_b)
        cross_rt["prospects"].save()
        opportunity_a = cross_rt["opp_service"].recommend_for_prospect("a")[0]
        opportunity_b = cross_rt["opp_service"].recommend_for_prospect("b")[0]
        job_a = cross_rt["service"].create_job("a", opportunity_id=opportunity_a.opportunity_id)
        job_b = cross_rt["service"].create_job("b", opportunity_id=opportunity_b.opportunity_id)
        check("cross-prospect canonical jobs", job_a.job is not None and job_b.job is not None and job_a.job.opportunity_id == opportunity_a.opportunity_id and job_b.job.opportunity_id == opportunity_b.opportunity_id and job_a.job.location_id == "loc_a" and job_b.job.location_id == "loc_b" and job_a.job.placement_id == "pl_a" and job_b.job.placement_id == "pl_b")
        run_a = cross_rt["service"].run_job(job_a.job.id) if job_a.job is not None else None
        run_b = cross_rt["service"].run_job(job_b.job.id) if job_b.job is not None else None
        if run_a is not None and run_b is not None:
            project_a = cross_rt["projects"].load(run_a.project_id)
            project_b = cross_rt["projects"].load(run_b.project_id)
            check("cross-prospect project A metadata", project_a.metadata.get("prospect_id") == "a" and project_a.metadata.get("opportunity_id") == opportunity_a.opportunity_id and project_a.metadata.get("location_id") == "loc_a" and project_a.metadata.get("placement_id") == "pl_a" and project_a.metadata.get("opportunity_id") != project_b.metadata.get("opportunity_id"))
            check("cross-prospect project B metadata", project_b.metadata.get("prospect_id") == "b" and project_b.metadata.get("opportunity_id") == opportunity_b.opportunity_id and project_b.metadata.get("location_id") == "loc_b" and project_b.metadata.get("placement_id") == "pl_b" and project_b.metadata.get("opportunity_id") != project_a.metadata.get("opportunity_id"))
            concept_a = project_a.concepts[-1] if project_a.concepts else None
            concept_b = project_b.concepts[-1] if project_b.concepts else None
            check("cross-prospect roofing localization", concept_a is not None and "Castle Rock" in concept_a.headline and "Dental" not in concept_a.headline, concept_a.headline if concept_a else "")
            check("cross-prospect dentist localization", concept_b is not None and "Parker" in concept_b.headline and "Dental" in concept_b.headline, concept_b.headline if concept_b else "")

        print()
        print("=" * 60)
        print("SPRINT 5K VERIFICATION COMPLETE")
        print("=" * 60)
    except Exception:
        traceback.print_exc()
        failed += 1

    print(f"Temp data at: {root}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(verify())