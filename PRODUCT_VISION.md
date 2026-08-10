# BillboardAI — Product Vision

> **Status:** Active product vision (memorialized roadmap checkpoint)
> **Owner:** Product / Strategy
> **Scope:** Strategic direction only. This document does not change the current
> Sprint 2E implementation, tests, or application code.

---

## 1. Core Product Positioning

**BillboardAI is NOT primarily an AI billboard-design application.**

BillboardAI is an **AI-powered sales enablement and advertising-inventory
monetization platform for local advertising.**

Creative generation is an important component, but its purpose is to accelerate
a larger commercial workflow:

```
Advertising Inventory
  → Identify / Import Prospects
  → Research Websites
  → Build Brand Intelligence
  → Score Prospect-to-Inventory Fit
  → Develop Message Strategy
  → Generate Creative Concepts
  → Create Personalized Mockups
  → Organize Projects
  → Generate Personalized Outreach
  → Launch Campaigns
  → Track Responses
  → Manage Sales Pipeline
  → Sell Inventory
  → Measure Results
  → Feed Outcomes Back Into Intelligence
```

---

## 2. Product North Star

The long-term objective is:

> **"Give BillboardAI unsold advertising inventory and a market. The platform
> helps identify appropriate local advertisers, researches them, creates
> personalized sales materials and mockups, supports outreach, manages
> opportunities, and helps the sales organization convert unsold inventory into
> revenue."**

The product should eventually be capable of answering:

> **"Who should we sell this available placement to?"**

and then automating or assisting much of the work required to make that sale.

---

## 3. Product Principles

1. **Optimize for selling advertising**, not merely designing advertisements.

2. **Creative quality matters, but autonomous graphic-design perfection is not
   the primary moat.** Creative should become reliably professional enough to
   create compelling personalized sales mockups and proposals.

3. **Batch operation is a core product capability**, not an end-stage
   convenience.

4. **Advertising inventory should become a first-class entity** in the system,
   alongside prospects / businesses / projects.

5. **Prospect-to-inventory matching should eventually become an intelligence
   layer** using geography, business category, availability, exclusivity,
   placement characteristics, pricing, and other relevant evidence.

6. **Personalized outreach is part of the core workflow.**

7. **BillboardAI should include a lightweight sales pipeline** while integrating
   with mature CRM / outreach systems where appropriate, rather than
   unnecessarily recreating full CRM products.

8. **Analytics should eventually connect:**
   - inventory
   - prospect characteristics
   - BrandProfile evidence
   - message strategy
   - creative concept
   - outreach messaging
   - engagement
   - replies
   - meetings / proposals
   - wins / losses
   - contract value

9. **This accumulated performance data may become an important proprietary
   asset and long-term moat.**

10. **Architecture should remain extensible** beyond grocery-cart / billboard
    advertising to additional local advertising formats after the initial
    workflow is proven.

---

## 4. Strategic Moat

The intended moat is the **combination** of:

- workflow automation
- advertising inventory intelligence
- prospect / business intelligence
- personalized creative
- prospect-to-placement matching
- outreach automation
- pipeline data
- performance / outcome data

**— not AI image generation by itself.**

---

## 5. Updated Development Priorities

Preserve completed work and the current Sprint 2E.

After the current concept-engine work, reprioritize the roadmap approximately
as follows:

1. Finish Ad Concept Engine
2. Build practical Creative Layout MVP
3. Build persistent Project Workspace
4. Introduce Advertising Inventory / Placement data model
5. Build Batch Prospect Import
6. Build Batch Research / Brand Intelligence
7. Build Batch Creative + Mockup Generation
8. Build Personalized Outreach Engine
9. Integrate campaign sending / outreach platform(s)
10. Build lightweight Sales Pipeline
11. Build retailer / physical Scene Library into the product workflow
12. Add Performance Analytics / feedback loop
13. Add cloud sync / multi-user capabilities when justified
14. Expand to additional advertising formats

Creative / layout quality may continue improving incrementally **without
blocking the broader sales workflow.**

---

## 6. Architectural Continuity

The work already completed remains valuable and directly supports this vision:

```
WebsiteScraper
  → normalized BrandAssets
  → BrandProfile
  → Business Intelligence
  → MessageStrategy
  → AdConcept
  → Creative / Layout
  → Physical Mockup
```

These become **components inside the larger sales-enablement pipeline** rather
than being discarded.
