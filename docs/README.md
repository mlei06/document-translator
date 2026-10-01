# Project documentation

Start with the current documents below. Historical plans are preserved separately and do not override current product requirements.

| Need | Document |
| --- | --- |
| Product behavior and constraints | [Unified specification](plans/unified-translator-design.md) |
| Current work and remaining gates | [Roadmap](IMPLEMENTATION_PLAN.md), [execution checklist](plans/unified-execution.md) |
| Components, APIs and boundaries | [Architecture](Architecture.md) |
| Setup, operation and configuration | [Deployment](Deployment.md) |
| Source layout | [Repository structure](Structure.md) |
| Desktop interactions and export behavior | [Desktop UI design](plans/desktop-ui-design.md) |
| Tests, acceptance evidence and limitations | [Verification](verification/README.md) |
| Decisions and their amendments | [Architecture decisions](decisions/README.md) |
| Deferred quality measurement | [Quality baseline plan](plans/quality-baselines.md) |

Design references and original UI assets remain in [design](design/web-gui/README.md). Reproducible investigation scripts remain in `experiments/`; they are not production dependencies or current product contracts.

[Archived plans and the old roadmap](archive/README.md) retain historical rationale, board references and earlier evidence. Generated screenshots, documents, models, credentials and build products remain local and are not source documentation.

When requirements change, update the current specification and relevant decision rather than creating another overlapping plan. Put measured outcomes in verification reports; put superseded plans in the archive and update their inbound links.
