from __future__ import annotations

import csv
import os

from gui.models.mockup_concept import MockupConcept
from gui.models.project_store import ProjectStore
from gui.models.prospect import Prospect
from gui.models.prospect_generation import OpportunityGenerationContext, ProspectGenerationJob
from gui.models.prospect_generation_store import ProspectGenerationStore
from gui.models.prospect_store import ProspectStore
from gui.services.campaign_export import CampaignExportService
from gui.services.outreach_generation import OutreachGenerationService, OutreachPersonalizationContext


def test_opportunity_aware_message():
    service = OutreachGenerationService()
    message = service.generate_message(
        OutreachPersonalizationContext(
            first_name="Alice",
            company_name="ABC Roofing",
            category="roofing",
            personalization_location="Castle Rock",
            placement_type="cart_corral",
        )
    )
    assert message.subject == "Quick idea for ABC Roofing"
    assert "Alice —" in message.body
    assert "Castle Rock" in message.body
    assert "cart-corral placement" in message.body
    assert message.body.endswith("Worth sending it over?")


def test_generic_message_missing_city_and_contact():
    service = OutreachGenerationService()
    message = service.generate_message(
        OutreachPersonalizationContext(
            company_name="ABC Roofing",
            category="roofing",
        )
    )
    assert message.body.startswith("Hi —")
    assert "Castle Rock" not in message.body
    assert "might want to see it" in message.body


def test_category_aware_wording_and_placement_formatting():
    service = OutreachGenerationService()
    dentist = service.generate_message(
        OutreachPersonalizationContext(
            first_name="Dana",
            company_name="Bright Smile Dental",
            category="dentist",
            personalization_location="Austin",
            placement_type="storefront",
        )
    )
    assert "your practice" in dentist.body
    assert "storefront placement" in dentist.body


def test_no_internal_metadata_leakage():
    service = OutreachGenerationService()
    message = service.generate_message(
        OutreachPersonalizationContext(
            first_name="Alice",
            company_name="ABC Roofing",
            category="roofing",
            personalization_location="Castle Rock",
        )
    )
    forbidden = [
        "94",
        "STRONG MATCH",
        "FOLLOW_UP",
        "loc-secret-123",
        "project-secret-456",
        "job-secret-789",
    ]
    for token in forbidden:
        assert token not in message.subject
        assert token not in message.body
        assert token not in message.personalization_basis


def test_campaign_export_outreach_snapshot_and_round_trip(tmp_path):
    prospect_store = ProspectStore(path=os.path.join(str(tmp_path), "prospects.json"))
    job_store = ProspectGenerationStore(path=os.path.join(str(tmp_path), "jobs.json"))
    project_store = ProjectStore(root=os.path.join(str(tmp_path), "projects"))
    export = CampaignExportService(prospect_store=prospect_store, job_store=job_store, project_store=project_store)

    prospect = Prospect(
        prospect_id="p1",
        company_name="ABC, Roofing",
        website="https://abc.com",
        email="owner@abc.com",
        contact_name="Alice Owner",
        category="roofing",
        city="Castle Rock",
        state="CO",
        metadata={"secret": "project-secret-456"},
        workflow_status="FOLLOW_UP",
    )
    prospect_store.create(prospect)
    prospect_store.save()

    project = project_store.create(company_name=prospect.company_name, website=prospect.website, name=prospect.prospect_id)
    image_path = os.path.join(project.image_path, "mockup.png")
    with open(image_path, "w", encoding="utf-8") as handle:
        handle.write("synthetic")
    concept = MockupConcept.create(
        image_path=image_path,
        template="contractor",
        headline="Line 1,\nLine 2",
        cta="Call Today",
        quality_score=91.5,
        company_name=prospect.company_name,
    )
    project.add_concept(concept)
    project_store.save(project)

    job = ProspectGenerationJob(
        id="job-1",
        prospect_id="p1",
        website=prospect.website,
        template="contractor",
        status="SUCCEEDED",
        project_id=project.id,
        result_path=concept.image_path,
        opportunity_id="opp-1",
        location_id="loc-secret-123",
        placement_id="pl-1",
        metadata={"score": 94, "label": "STRONG MATCH", "job_id": "job-secret-789"},
        opportunity_context=OpportunityGenerationContext(
            opportunity_id="opp-1",
            location_id="loc-secret-123",
            placement_id="pl-1",
            retailer_name="King Soopers",
            location_name="Castle Rock North",
            store_number="999",
            city="Castle Rock",
            state="CO",
            placement_name="Front Cart Corral",
            placement_type="cart_corral",
        ),
    )
    job_store.upsert(job)
    job_store.save()

    row = export.build_row("p1")
    assert row.email_subject == "Quick idea for ABC, Roofing"
    assert "Alice —" in row.email_body
    assert "Castle Rock" in row.email_body
    assert "cart-corral placement" in row.email_body
    assert "94" not in row.email_body
    assert "STRONG MATCH" not in row.email_body
    assert "FOLLOW_UP" not in row.email_body
    assert "loc-secret-123" not in row.email_body
    assert "project-secret-456" not in row.email_body
    assert "job-secret-789" not in row.email_body

    output = os.path.join(str(tmp_path), "campaign.csv")
    export.export_csv(["p1"], output)
    with open(output, "r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["email_subject"] == row.email_subject
    assert rows[0]["email_body"] == row.email_body


def test_cross_prospect_isolation_and_snapshot_immutability(tmp_path):
    prospect_store = ProspectStore(path=os.path.join(str(tmp_path), "prospects.json"))
    job_store = ProspectGenerationStore(path=os.path.join(str(tmp_path), "jobs.json"))
    project_store = ProjectStore(root=os.path.join(str(tmp_path), "projects"))
    export = CampaignExportService(prospect_store=prospect_store, job_store=job_store, project_store=project_store)

    prospects = [
        Prospect(prospect_id="a", company_name="A Co", website="https://a.com", email="a@example.com", contact_name="Alice A", category="roofing", city="Castle Rock", state="CO"),
        Prospect(prospect_id="b", company_name="B Co", website="https://b.com", email="b@example.com", contact_name="Bob B", category="dentist", city="Austin", state="TX"),
    ]
    for p in prospects:
        prospect_store.create(p)
    prospect_store.save()

    def seed(p: Prospect, image: str, city: str, placement_type: str, job_id: str):
        project = project_store.create(company_name=p.company_name, website=p.website, name=p.prospect_id)
        path = os.path.join(project.image_path, image)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("synthetic")
        concept = MockupConcept.create(image_path=path, template="contractor", headline=f"{p.company_name} Headline", cta="Call Today", quality_score=88, company_name=p.company_name)
        project.add_concept(concept)
        project_store.save(project)
        job_store.upsert(ProspectGenerationJob(
            id=job_id,
            prospect_id=p.prospect_id,
            website=p.website,
            template="contractor",
            status="SUCCEEDED",
            project_id=project.id,
            result_path=concept.image_path,
            opportunity_id=f"opp-{p.prospect_id}",
            location_id=f"loc-{p.prospect_id}",
            placement_id=f"pl-{p.prospect_id}",
            opportunity_context=OpportunityGenerationContext(
                opportunity_id=f"opp-{p.prospect_id}",
                location_id=f"loc-{p.prospect_id}",
                placement_id=f"pl-{p.prospect_id}",
                city=city,
                state=p.state,
                placement_name="Front",
                placement_type=placement_type,
            ),
        ))
        return project, concept

    seed(prospects[0], "a.png", "Castle Rock", "cart_corral", "job-a")
    seed(prospects[1], "b.png", "Austin", "storefront", "job-b")
    job_store.save()

    row_a = export.build_row("a")
    row_b = export.build_row("b")
    assert "A Co" in row_a.email_body and "B Co" not in row_a.email_body
    assert "B Co" in row_b.email_body and "A Co" not in row_b.email_body
    assert "Castle Rock" in row_a.email_body and "Austin" not in row_a.email_body
    assert "Austin" in row_b.email_body and "Castle Rock" not in row_b.email_body