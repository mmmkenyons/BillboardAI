# BillboardAI — Development Workflow Rules

## Before Editing
Before implementing substantial work:
1. Inspect Git state.
2. Read relevant production code.
3. Search for existing patterns.
4. Identify the smallest coherent implementation boundary.
5. Do not modify unrelated files.

If an expected starting checkpoint does not match the repository, STOP and report it.

## Editing
Make focused incremental edits.
Prefer one logical editor operation at a time.
After important edits, re-read the affected file and verify the change actually exists.

Do not trust conversational narration as proof that an edit succeeded.

## Model / Session Changes
Different Cline models may be used during the same sprint.

After every model/session change:
1. git status --short
2. inspect current diff
3. read relevant files
4. determine completed requirements
5. preserve valid work
6. continue from first incomplete requirement

## Tool Failure Safety
If raw internal markup appears, including DSML, tool_calls, <|...|>, or similar:
STOP repeated tool attempts.

Never paste internal tool markup into source files.
Never mark a task complete because a tool invocation failed.

Instead:
1. Inspect whether the intended edit actually occurred.
2. Retry as one small editor operation if appropriate.
3. Re-read the file.
4. If tool execution continues failing, report the failure and stop.

## Scope
Do not perform unrelated refactors, dependency upgrades, redesigns, or cleanup.
Do not expand scope without a concrete requirement.

## Qt / Windows
BillboardAI runs on Windows with PySide6.
Long-running/network operations must not block the GUI thread.
Reuse established QThread/worker patterns.
Do not manipulate GUI widgets from worker threads.

## User-Facing Features
A service existing does not prove a user-facing feature is complete.
For user-facing work verify:
UI -> controller -> worker/service -> persistence -> displayed result.
