# Project Agent Policy

## Executor delegation

- The primary model decides case by case whether an execution agent is useful.
- Do not delegate small, local, low-risk changes merely because they modify executable code. The primary model should implement those changes directly.
- Consider delegation for large refactors, multiple independent workstreams, specialized investigation, or when an independent implementation/review materially reduces risk.
- If a skill or default workflow mandates delegation, this project instruction overrides only that delegation requirement. Keep the workflow's useful testing, review, safety, and verification steps.
- Never let delegation add more coordination cost than the code change itself.
