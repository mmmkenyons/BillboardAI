from __future__ import annotations

import os

from gui.models.inventory import Location, Market, Placement, Retailer
from gui.models.inventory_store import InventoryStore
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


def _build_service(tmp_path, fake_generate=None):
    root = str(tmp_path)
    prospect_store = ProspectStore(path=os.path.join(root, "prospects.json"))
    job_store = ProspectGenerationStore(path=os.path.join(root, "jobs.json"))
    project_store = ProjectStore(root=os.path.join(root, "projects"))
    inventory_store = InventoryStore(path=os.path.join(root, "inventory.json"))
    opportunity_store = OpportunityStore(path=os.path.join(root, "opportunities.json"))

    retailer = Retailer(retailer_id="ret1", name="King Soopers")
    retailer_b = Retailer(retailer_id="ret2", name="Safeway")
    market = Market(market_id="m1", name="Denver Metro")
    location = Location(
        location_id="loc1",
        retailer_id="ret1",
        market_id="m1",
        name="King Soopers #123",
        store_number="123",
        city="Castle Rock",
        state="CO",
    )
    placement = Placement(
        placement_id="pl1",
        location_id="loc1",
        name="Front Cart Corral A",
        placement_type="cart_corral",
        scene_template="cart_corral",
        exclusive_category="roofing",
    )
    location_b = Location(
        location_id="loc_b1",
        retailer_id="ret2",
        market_id="m1",
        name="Safeway #200",
        store_number="200",
        city="Parker",
        state="CO",
    )
    placement_b = Placement(
        placement_id="pl_b1",
        location_id="loc_b1",
        name="Front Cart Corral B",
        placement_type="cart_corral",
        scene_template="cart_corral_b",
        exclusive_category="dentist",
    )
    inventory_store.inventory.retailers.extend([retailer, retailer_b])
    inventory_store.inventory.markets.append(market)
    inventory_store.inventory.locations.append(location)
    inventory_store.inventory.locations.append(location_b)
    inventory_store.inventory.placements.append(placement)
    inventory_store.inventory.placements.append(placement_b)
    inventory_store.save()

    a = Prospect(prospect_id="a", company_name="ABC Roofing", website="https://abc.com", category="roofing", city="Castle Rock", state="CO")
    b = Prospect(prospect_id="b", company_name="XYZ Dental", website="https://xyz.com", category="dentist", city="Parker", state="CO")
    g = Prospect(prospect_id="g", company_name="Generic Dental", website="https://generic.example.com", category="dentist", city="Aurora", state="CO")
    prospect_store.create(a)
    prospect_store.create(b)
    prospect_store.create(g)
    prospect_store.save()

    opp_service = OpportunityService(
        prospect_store=prospect_store,
        project_store=project_store,
        inventory_store=inventory_store,
        opportunity_store=opportunity_store,
    )
    opp_service.recommend_for_prospect("a")
    opp_service.recommend_for_prospect("b")
    rec_service = StoreRecommendationService(opportunity_service=opp_service, inventory_store=inventory_store)
    workspace = ProspectOpportunityWorkspaceService(
        prospect_store=prospect_store,
        project_store=project_store,
        inventory_store=inventory_store,
        opportunity_service=opp_service,
        store_recommendation_service=rec_service,
    )
    service = ProspectGenerationService(
        prospect_store=prospect_store,
        job_store=job_store,
        generation_callable=fake_generate or (lambda request: MockupResult(success=True, website=request.url, output_path=request.output_path, preview_path=request.output_path, headline="Generic Headline", cta="Call Today", extra={"render_context": {"headline": "Generic Headline", "cta": "Call Today", "template": request.template, "scene_template": request.opportunity_context.scene_template if request.opportunity_context else "cart_corral"}})),
        default_output_root=root,
        project_store=project_store,
        opportunity_workspace_service=workspace,
    )
    return service, opp_service, prospect_store, project_store, inventory_store, job_store


def test_automatic_best_opportunity_snapshotted(tmp_path):
    service, opp_service, prospect_store, project_store, inventory_store, job_store = _build_service(tmp_path)
    created = service.create_job("a")
    assert created.job is not None
    assert created.job.opportunity_id
    assert created.job.location_id == "loc1"
    assert created.job.placement_id == "pl1"
    assert created.job.metadata["opportunity_label"] == "King Soopers #123 — Castle Rock"
    job = service.run_job(created.job.id)
    project = project_store.load(job.project_id)
    assert project.metadata["prospect_id"] == "a"
    assert project.metadata["generation_job_id"] == job.id
    assert project.metadata["opportunity_id"] == job.opportunity_id
    assert project.metadata["location_id"] == "loc1"
    assert project.metadata["placement_id"] == "pl1"
    reloaded_store = ProspectGenerationStore(path=job_store.path)
    reloaded = reloaded_store.get(job.id)
    assert reloaded is not None
    assert reloaded.opportunity_context is not None
    assert reloaded.opportunity_context.location_id == "loc1"
    assert reloaded.opportunity_context.placement_id == "pl1"
    assert reloaded.opportunity_context.scene_template == "cart_corral"
    assert reloaded.opportunity_context.retailer_name == "King Soopers"
    assert reloaded.opportunity_context.location_name == "King Soopers #123"
    assert reloaded.opportunity_context.store_number == "123"
    assert reloaded.opportunity_context.city == "Castle Rock"
    assert reloaded.opportunity_context.state == "CO"
    assert reloaded.opportunity_context.placement_name == "Front Cart Corral A"
    assert reloaded.opportunity_context.placement_type == "cart_corral"


def test_wrong_prospect_opportunity_rejected(tmp_path):
    calls: list[str] = []

    def fake_generate(request):
        calls.append(request.url)
        return MockupResult(success=True, website=request.url, output_path=request.output_path, preview_path=request.output_path)

    service, opp_service, prospect_store, project_store, inventory_store, job_store = _build_service(tmp_path, fake_generate=fake_generate)
    opportunity_id = opp_service.by_prospect("a")[0].opportunity_id
    created = service.create_job("b", opportunity_id=opportunity_id)
    assert created.job is None
    assert created.eligible is False
    assert "does not belong to prospect" in created.reasons[0]
    assert service.list_jobs() == []
    assert project_store.list() == []
    assert calls == []


def test_explicit_valid_opportunity_allowed(tmp_path):
    service, opp_service, prospect_store, project_store, inventory_store, job_store = _build_service(tmp_path)
    opportunity_id = opp_service.by_prospect("a")[0].opportunity_id
    created = service.create_job("a", opportunity_id=opportunity_id)
    assert created.job is not None
    assert created.job.opportunity_id == opportunity_id


def test_old_5j_generic_job_loads_without_context(tmp_path):
    _, _, _, _, _, job_store = _build_service(tmp_path)
    legacy_path = job_store.path
    os.makedirs(os.path.dirname(legacy_path), exist_ok=True)
    with open(legacy_path, "w", encoding="utf-8") as handle:
        handle.write(
            '{\n'
            '  "schema_version": 1,\n'
            '  "jobs": [{\n'
            '    "id": "legacy-job",\n'
            '    "prospect_id": "a",\n'
            '    "website": "https://abc.com",\n'
            '    "template": "contractor",\n'
            '    "status": "QUEUED",\n'
            '    "created_at": "2026-01-01T00:00:00"\n'
            '  }]\n'
            '}'
        )
    reloaded = ProspectGenerationStore(path=legacy_path)
    job = reloaded.get("legacy-job")
    assert job is not None
    assert job.opportunity_id == ""
    assert job.location_id == ""
    assert job.placement_id == ""
    assert job.opportunity_context is None


def test_restart_and_recommendation_change_do_not_mutate_queued_job(tmp_path):
    service, opp_service, prospect_store, project_store, inventory_store, job_store = _build_service(tmp_path)
    created = service.create_job("a")
    assert created.job is not None
    first_job_id = created.job.id
    first_opportunity_id = created.job.opportunity_id
    first_location_id = created.job.location_id
    first_placement_id = created.job.placement_id

    placement_one = inventory_store.inventory.get_placement("pl1")
    placement_two = Placement(
        placement_id="pl2b",
        location_id="loc1",
        name="Front Cart Corral B",
        placement_type="cart_corral",
        scene_template="cart_corral_alt",
        exclusive_category="roofing",
    )
    inventory_store.inventory.placements.append(placement_two)
    if placement_one is not None:
        placement_one.exclusive_category = "dentist"
    inventory_store.save()
    opp_service.recommend_for_prospect("a")

    restarted = ProspectGenerationService(
        prospect_store=prospect_store,
        job_store=ProspectGenerationStore(path=job_store.path),
        project_store=project_store,
        default_output_root=str(tmp_path),
        opportunity_workspace_service=service._opportunity_workspace_service,
    )
    queued = restarted.job_store.get(first_job_id)
    assert queued is not None
    assert queued.opportunity_id == first_opportunity_id
    assert queued.location_id == first_location_id
    assert queued.placement_id == first_placement_id
    assert queued.opportunity_context is not None
    assert queued.opportunity_context.placement_id == first_placement_id
    run_one = restarted.run_job(first_job_id)
    assert run_one.status == "SUCCEEDED"
    next_job = restarted.create_job("a")
    assert next_job.job is not None
    assert next_job.job.placement_id != first_placement_id
    assert next_job.job.id != first_job_id
    reloaded_after = ProspectGenerationStore(path=job_store.path).get(first_job_id)
    assert reloaded_after is not None
    assert reloaded_after.placement_id == first_placement_id


def test_scene_template_snapshotted_not_reloaded_for_existing_job(tmp_path):
    service, opp_service, prospect_store, project_store, inventory_store, job_store = _build_service(tmp_path)
    created = service.create_job("a")
    assert created.job is not None
    assert created.job.opportunity_context is not None
    assert created.job.opportunity_context.scene_template == "cart_corral"
    placement = inventory_store.inventory.get_placement("pl1")
    assert placement is not None
    placement.scene_template = "changed_scene"
    inventory_store.save()
    restarted = ProspectGenerationStore(path=job_store.path)
    queued = restarted.get(created.job.id)
    assert queued is not None
    assert queued.opportunity_context is not None
    assert queued.opportunity_context.scene_template == "cart_corral"


def test_generic_generation_allowed_without_opportunity(tmp_path):
    service, opp_service, prospect_store, project_store, inventory_store, job_store = _build_service(tmp_path)
    created = service.create_job("g", template="dentist")
    assert created.job is not None
    assert created.job.opportunity_id == ""
    assert created.job.location_id == ""
    assert created.job.placement_id == ""
    assert created.job.opportunity_context is None
    assert created.job.metadata["opportunity_label"] == "Generic"


def test_generic_project_metadata_does_not_invent_opportunity_ids(tmp_path):
    service, opp_service, prospect_store, project_store, inventory_store, job_store = _build_service(tmp_path)
    created = service.create_job("g", template="dentist")
    assert created.job is not None
    job = service.run_job(created.job.id)
    project = project_store.load(job.project_id)
    assert project.metadata["prospect_id"] == "g"
    assert project.metadata["generation_job_id"] == job.id
    assert "opportunity_id" not in project.metadata
    assert "location_id" not in project.metadata
    assert "placement_id" not in project.metadata


def test_snapshot_city_not_live_inventory_city_drives_queued_job(tmp_path):
    captured = []

    def fake_generate(request):
        captured.append(request.opportunity_context.city if request.opportunity_context else "")
        city = request.opportunity_context.city if request.opportunity_context else ""
        headline = f"Serving {city}" if city else "Generic Headline"
        return MockupResult(
            success=True,
            website=request.url,
            output_path=request.output_path,
            preview_path=request.output_path,
            headline=headline,
            cta="Call Today",
            extra={
                "render_context": {
                    "headline": headline,
                    "cta": "Call Today",
                    "template": request.template,
                    "scene_template": request.opportunity_context.scene_template if request.opportunity_context else "cart_corral",
                    "opportunity_context": request.opportunity_context.to_dict() if request.opportunity_context else {},
                }
            },
        )

    service, opp_service, prospect_store, project_store, inventory_store, job_store = _build_service(tmp_path, fake_generate=fake_generate)
    created = service.create_job("a")
    assert created.job is not None
    assert created.job.opportunity_context is not None
    assert created.job.opportunity_context.city == "Castle Rock"

    live_location = inventory_store.inventory.get_location("loc1")
    assert live_location is not None
    live_location.city = "Parker"
    inventory_store.save()

    job = service.run_job(created.job.id)
    assert job.status == "SUCCEEDED"
    assert captured == ["Castle Rock"]
    project = project_store.load(job.project_id)
    assert project.concepts[-1].headline == "Serving Castle Rock"
    assert project.render_context.get("opportunity_context", {}).get("city") == "Castle Rock"


def test_generic_job_creative_context_remains_none(tmp_path):
    captured = []

    def fake_generate(request):
        captured.append(request.opportunity_context)
        return MockupResult(
            success=True,
            website=request.url,
            output_path=request.output_path,
            preview_path=request.output_path,
            headline="Generic Headline",
            cta="Call Today",
            extra={
                "render_context": {
                    "headline": "Generic Headline",
                    "cta": "Call Today",
                    "template": request.template,
                    "scene_template": "cart_corral",
                    "opportunity_context": {},
                }
            },
        )

    service, opp_service, prospect_store, project_store, inventory_store, job_store = _build_service(tmp_path, fake_generate=fake_generate)
    created = service.create_job("g", template="dentist")
    assert created.job is not None
    job = service.run_job(created.job.id)
    assert job.status == "SUCCEEDED"
    assert captured == [None]
    project = project_store.load(job.project_id)
    normalized = project.render_context.get("opportunity_context", {})
    assert normalized.get("city") == ""
    assert normalized.get("opportunity_id") == ""
    assert normalized.get("location_id") == ""
    assert normalized.get("placement_id") == ""
