# Agent Instructions

## Language

- All authored repository content must be in English. 

## Django development

- Before writing or changing Django code, read and apply `.agents/skills/django-expert/SKILL.md` and its relevant references. If the skill is unavailable, report the missing prerequisite.
- Preserve the prepared toolchain and use `uv run` for project commands.

## Architecture

- Design for maintainability and extension within Django, with clear responsibilities and dependencies.
- Keep catalog rules and queries independent of HTTP handling, response formats, and frontend technology so that different interfaces can reuse them. Do not build an API or another frontend until required by the approved scope.
- Justify architectural layers by the responsibilities they own and the changes they isolate, rather than prescribing or banning particular patterns in advance.
- Apply SOLID pragmatically alongside Django conventions: use clear responsibilities, cohesive components, and explicit dependencies. Introduce abstractions when they isolate concrete variation or complexity, not merely to satisfy a pattern.

## Workflow

- Follow `workflow-guide` and use Orca's `orchestration` skill for supervised sessions. Keep reviews independent.
- Use `Task.md` and approved design/plan artifacts as the source of requirements. Product decisions and final acceptance belong to the user.
- Do not stage, commit, push, deploy, or publish without a separate explicit user request.