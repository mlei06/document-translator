# Component Architecture

One file per major component, named after the component (e.g. `api.md`, `frontend.md`, `database.md`, `auth.md`). Start each new one from [`_TEMPLATE.md`](_TEMPLATE.md).

The most important section in every component doc is **Boundaries** - what it owns and, just as importantly, what it does not own. That's what stops agents from putting business logic wherever is locally convenient.

Link each component from `docs/Architecture.md#major-components`.
