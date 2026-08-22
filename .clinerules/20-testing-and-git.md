# BillboardAI — Testing and Git Rules

## Python
Use:
D:\BillboardAI\bb_env\Scripts\python.exe

For important validation, prefer the explicit executable path.
Never activate bb_env from Cline.
Never invoke Activate.ps1.
Never use Set-ExecutionPolicy for project Python.

## Testing
New behavior requires deterministic focused tests.
Network production code must support offline/injected test behavior.
Do not make automated tests depend on live websites or external services unless explicitly required.
Prefer tools/finalize_sprint.py for sprint validation/finalization orchestration.
Never redirect validation output into repository root.
Never launch visible foreground PowerShell, cmd, or Windows Terminal for automated validation.
Exact pytest pass counts are informational unless explicitly contractual.
Git staging does not change runtime Python semantics.

## Verifiers
Preserve existing durable verifier coverage under tools/.
Verifiers must clearly report PASS/FAIL and return non-zero on genuine failure.

## Full Suite
Before finalizing a sprint, run the full pytest suite unless explicitly instructed otherwise.
Capture the exact final result.

Never claim the full suite passed if:
- output was not observed
- execution was interrupted
- output was truncated
- only focused tests were run

Clearly distinguish warnings, environment failures, test failures, and known teardown artifacts.

## Git Safety
Never use git clean unless explicitly instructed.
Never use git clean as part of sprint finalization.
Never auto-delete unexpected artifacts.

Never reset, restore, discard, overwrite, or delete unexpected user work.

Before commit:
1. inspect git status --short
2. inspect diff boundary
3. run required tests/verifiers
4. stage only approved files
5. inspect git diff --cached --name-status
6. run git diff --cached --check
7. audit cached diff

Commit only when explicitly authorized.
Push only when explicitly authorized.
Never force push unless explicitly requested.
The validation harness makes no commit/push itself unless a future explicitly reviewed feature adds that capability.

## Commit Boundary
Do not commit unintended:
- .bak files
- repro scripts
- generated output
- screenshots
- test dumps
- temporary files
- virtual environments

## Security
Audit changes for:
- secrets
- API keys
- passwords
- tokens
- Authorization/Bearer values
- developer-local absolute paths
- debug prints
- pdb
- breakpoint()
- merge markers
- temporary instrumentation
- raw model/tool markup
