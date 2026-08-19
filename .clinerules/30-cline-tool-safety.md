# BillboardAI — Cline Agent Safety Rules

## Completion
Do not declare COMPLETE merely because:
- one edit succeeded
- one test passed
- a tool call failed
- conversational output was produced
- context is getting long

Completion requires the requested implementation and required validation.

## Evidence
Repository files, Git state, and actual command output are authoritative.
Previous-model narration is not.

Do not invent command results.

Reports must distinguish:
- VERIFIED
- FAILED
- NOT RUN
- BLOCKED
- INFERRED

Never describe skipped validation as passing.

## Tool Usage
Prefer small editor operations.
Verify important edits by re-reading files.

If an editor/tool operation fails, inspect actual file state before retrying.
Do not enter repeated tool-call narration loops.

## Large Sprint Workflow
Use this order:
1. establish repository state
2. inspect architecture
3. implement core
4. implement integration
5. focused tests
6. durable verifiers
7. full regression
8. Git boundary audit
9. report
10. commit/push only when authorized

## Model Switching
When a new model takes over, it must reconstruct state from the repository rather than assuming previous conversational context is accurate.
