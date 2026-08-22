# BillboardAI — Project Core Rules

## Project
Repository: D:\BillboardAI
Platform: Windows
GUI: PySide6
Authoritative environment: D:\BillboardAI\bb_env
Authoritative Python: D:\BillboardAI\bb_env\Scripts\python.exe

Always use the authoritative bb_env Python for application commands, pytest, and verifiers.
Never activate bb_env from Cline.
Never invoke Activate.ps1 for project Python.
Never use Set-ExecutionPolicy for project Python.
Always invoke D:\BillboardAI\bb_env\Scripts\python.exe directly.
Before diagnosing missing dependencies, verify:
D:\BillboardAI\bb_env\Scripts\python.exe -c "import sys; print(sys.executable)"

## Repository Is Authoritative
Before substantial work:
1. Inspect git status --short.
2. Inspect current branch and HEAD when relevant.
3. Read relevant production files.
4. Inspect the current diff if work is already in progress.

Files and Git state are authoritative. Previous Cline conversations and model narration are not.

When resuming after a model/session change:
1. Inspect current working tree.
2. Determine what is actually implemented.
3. Preserve valid existing work.
4. Resume from the first incomplete requirement.
5. Never restart a sprint merely because model context changed.

## Architecture
Prefer extending existing BillboardAI architecture over creating parallel systems.
Search for existing models, stores, services, controllers, workers, views, tests, and verifiers before adding new ones.
Avoid unrelated refactors and speculative abstractions.

## Prospect Website Semantics
Prospect.website is the parent/business/organization website.
Never overwrite it with an individual profile URL.

Profile resolution is additive using:
- resolved_profile_url
- manual_profile_url
- resolution_status
- resolution_confidence

New generation jobs use the authoritative effective scrape URL:
manual profile URL -> confident resolved profile URL -> Prospect.website fallback.

Existing jobs retain their snapshotted URL.

Wrong-person profile resolution is worse than NOT_FOUND or AMBIGUOUS.

Campaign and Smartlead workflows continue using Prospect.website as business identity unless an explicit sprint changes that contract.
