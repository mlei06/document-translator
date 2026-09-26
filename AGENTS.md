# Agent Instructions

Read this file first in any agent session working in this repository. It is a router, not a manual - the documents and prompts it points to hold the actual content.

## Project

Read `README.md` first for the project's problem, goals, non-goals, and constraints.

## Documentation Authority

When sources disagree, resolve in this order, and say explicitly which you are following:

1. The user's current, explicit instruction
2. Accepted architecture decisions (`docs/decisions/`)
3. Architecture documentation (`docs/Architecture.md`, `docs/architecture/`)
4. The current implementation plan (`docs/IMPLEMENTATION_PLAN.md`)
5. The detailed task plan for the work at hand (`docs/plans/`)
6. Existing code

If documented architecture and existing code disagree, do not assume either is correct. Surface both explicitly - "documented architecture says X, the implementation actually does Y, this task requires Z" - and resolve it intentionally rather than silently picking one.

## Canonical Documentation

- Architecture: `docs/Architecture.md`, `docs/architecture/components/`, `docs/architecture/diagrams/`
- Repository structure: `docs/Structure.md`
- Implementation roadmap: `docs/IMPLEMENTATION_PLAN.md`
- Detailed task plans: `docs/plans/`
- Architecture decisions: `docs/decisions/`

## Core Rules

1. Read the relevant documentation before modifying code.
2. Do not silently deviate from documented architecture. If the plan or task requires it, stop and escalate to the architect role instead of improvising.
3. Keep documentation synchronized with meaningful structural changes, in the same change that makes them.
4. Prefer small, testable changes over large speculative ones.
5. Do not implement functionality outside the current plan's scope.
6. Run the relevant lint/typecheck/tests after implementation, and do not mark a task complete until its completion criteria are satisfied.
7. Inspect the existing code and docs before proposing architecture - never design as if the repository were empty when it isn't.

## Checks

Install and run from the repository root. All six must pass before a task is complete; CI runs the same commands.

```text
uv sync --all-packages
uv run ruff format --check
uv run ruff check
uv run pyright
uv run lint-imports
uv run pytest
```

An import contract failure means code is in the wrong place (see `docs/decisions/ADR-003-source-structure.md`). Fix it by moving the code, not by editing `.importlinter`.

## Agent Roles

- **Architect** - `.agents/prompts/architect.md` - designs and documents; does not write production code.
- **Orchestrator** - `.agents/prompts/orchestrator.md` - breaks an approved plan into tasks and coordinates coders and the reviewer.
- **Coder** - `.agents/prompts/coder.md` - implements one approved plan/task; narrow authority.
- **Reviewer** - `.agents/prompts/reviewer.md` - reviews plan compliance, architecture compliance, correctness, security, maintainability, and tests.

For a small task, one agent can play architect, then coder, then reviewer in sequence. For a larger phase, use the orchestrator to fan out to multiple coders.

## Skills

Reusable domain knowledge (backend, frontend, database design, testing, security review, API design, migrations, ...) lives in `.agents/skills/`. Any role can load a skill relevant to the task at hand; skills are knowledge, not authority.
