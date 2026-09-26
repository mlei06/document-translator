# Repository Structure

<!-- Update this whenever a change alters the repository's conceptual structure, in the same change. This starts generic; make it describe the real layout as the project grows. -->

This describes the layout that exists today. The approved target layout for source code (`packages/core`, `apps/cli`, `apps/server`, `apps/web`) is defined in [ADR-003](decisions/ADR-003-source-structure.md); update this file as those directories are created.

```text
src/
tests/
scripts/
docs/
.agents/
```

## `/src`

Placeholder from the scaffold. Not used; source code goes in `packages/` and `apps/` per ADR-003.

## `/tests`

Automated tests. Per ADR-003, package-level tests live inside each package; this directory holds cross-surface end-to-end tests (`e2e/`) and shared sample documents (`fixtures/`).

## `/scripts`

Development, migration, deployment, and maintenance scripts.

## `/docs`

Project documentation. See `docs/Architecture.md` for what each document is for.

### `/docs/architecture`

System architecture documentation: `components/` (per-component detail) and `diagrams/` (Mermaid diagrams).

### `/docs/plans`

Detailed implementation plans, one per phase or subphase of `docs/IMPLEMENTATION_PLAN.md`.

### `/docs/decisions`

Architecture Decision Records (ADRs).

## `/.agents`

Agent role prompts (`prompts/`) and reusable skills (`skills/`). See `AGENTS.md`.

`skills/azure-devops/SKILL.md` covers Azure DevOps CLI access, publishing a local Git codebase to a repository in an existing project, and managing board work items that track the implementation plan.
