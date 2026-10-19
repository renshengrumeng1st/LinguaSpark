# Project Agent Policy

## Executor delegation

- The primary model decides case by case whether an execution agent is useful.
- Do not delegate small, local, low-risk changes merely because they modify executable code. The primary model should implement those changes directly.
- Consider delegation for large refactors, multiple independent workstreams, specialized investigation, or when an independent implementation/review materially reduces risk.
- If a skill or default workflow mandates delegation, this project instruction overrides only that delegation requirement. Keep the workflow's useful testing, review, safety, and verification steps.
- Never let delegation add more coordination cost than the code change itself.

## Proportionate development workflow

These working preferences were persisted at the user's request after the
2026-09-08 workflow review. They take precedence over conflicting skill
ceremony, while preserving runtime permissions and the user's task scope.

- For an explicit, bounded implementation request, inspect the relevant flow,
  state material assumptions briefly, implement, and verify. Reuse an approved
  design; do not restart approval because the turn or skill changed. Ask only
  about an unresolved choice that materially changes the result or authority.
- Work in the existing checkout for small, low-risk changes when it is safe.
  Use isolation for conflicting edits, parallel work, substantial experiments,
  or an explicit user preference. Preserve all unrelated user changes.
- Select tests by behavior and risk. Start with focused tests; add regression
  coverage for meaningful bugs and state transitions. Documentation-only edits
  need a diff/readback, not the application suite or token-presence tests.
- Reuse a successful test result for the same code, dependencies, configuration,
  and relevant environment during the task. A new skill, commit, or final reply
  is not a reason to rerun it. After a fast-forward merge, compare the tested
  tree and check for path-sensitive effects before choosing additional tests.
- Investigate reproducible baseline failures with logs before another unchanged
  rerun. Continue independent, authorized work; report uncovered verification
  honestly instead of claiming an unrelated failure proves the change is bad.
- Perform dependent Git mutations sequentially and check every exit code.
  If worktree removal fails, inspect the actual remaining files before cleanup
  or branch deletion. Untracked and ignored files are not automatically disposable.
- Follow an already-authorized integration choice without another finish menu.
  Implementation alone does not authorize packaging, publishing, or remote writes.

## LinguaSpark verification notes

- Reuse the project `.venv/Scripts/python.exe`. Run it with the intended checkout
  as the working directory; an isolated checkout can use the existing interpreter.
- Full regression: `.\.venv\Scripts\python.exe -m pytest -q` from the repository
  root. `test.bat` also sets `QT_QPA_PLATFORM=offscreen`; record which environment
  was actually used, especially for Qt WebEngine tests.
- When PDF.js times out, inspect `load_failed`, `page().loadingChanged`, renderer
  termination, console messages, and `PdfJsAssetServer.request_log` together.
  A 200 response for `viewer.html` alone does not prove the renderer started.
- On 2026-09-08 the restricted runner produced `ProcessGone` and
  `Process.Sandbox.Launch.Error 87` before subresources loaded. Treat this as a
  diagnostic clue, not the cause of every future timeout. If execution restrictions
  are implicated, use the tool's permission escalation for the affected test;
  do not disable Chromium sandboxing to bypass the restriction or persist that
  setting in the application, test configuration, or user environment.
- Autostart unit tests use an in-memory registry boundary. Report them separately
  from actual Windows registration, Task Manager state, and login validation;
  do not silently change the user's real startup registration during tests.

For the evidence and rationale behind these defaults, read
`docs/development-workflow-review.md` only when reviewing the workflow itself.
