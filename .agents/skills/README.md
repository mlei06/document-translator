# Skills

Reusable domain knowledge and methodology that any agent role can load for a task - distinct from roles (`.agents/prompts/`), which define authority. A skill never grants an agent authority it doesn't already have; it informs how the agent does what its role already allows.

Each subdirectory is one skill area, with a `SKILL.md` describing the methodology, conventions, and pitfalls specific to that domain for this project.

Starter categories (delete or rename to fit the project's actual stack):

- `backend/`
- `frontend/`
- `database-design/`
- `testing/`
- `security-review/`
- `api-design/`
- `migrations/`

Operational skills:

- `azure-devops/` - Verify CLI access, create a repository in an existing Azure DevOps project, push a local codebase, and create or update board work items that track the implementation plan.
