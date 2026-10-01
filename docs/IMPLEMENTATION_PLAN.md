# Implementation roadmap

The [unified specification](plans/unified-translator-design.md) defines current behavior. The [execution checklist](plans/unified-execution.md) and [verification reports](verification/README.md) distinguish implemented source from tested deployment. This index reorganizes existing work; it does not change external board states or close release gates.

## Current implementation

| Area | State and reference |
| --- | --- |
| Core and CLI | Five document formats, target-only inference and standard fitting implemented; [core evidence](verification/core.md) |
| Shared service | Automatic routing, shared website results/private History, bounded storage, cancellation and recovery implemented; [architecture](Architecture.md) |
| Website | Immediate target-pinned batches, original Lenny/orb interactions, saved target preference and compact History implemented; [website evidence](verification/web.md) |
| Desktop | Native shell, local runtime, Explorer integration and managed offline support implemented; [desktop evidence](verification/desktop.md) |
| Desktop UI and exports | File/folder selection, compact activity and explicit export folder defaulting to Downloads implemented in source; updated installed-app verification remains pending; [design](plans/desktop-ui-design.md) |

## Remaining delivery gates

- Rebuild both desktop shell and frozen Python runtime for the latest UI/export changes, then verify installed native drag/drop, folder pickers, export and Open file behavior. Older installer evidence does not certify these later changes.
- Complete signed Windows installer/Explorer identity checks and clean-machine online/offline acceptance with the required certificate and hardware.
- Resolve distribution approvals for bundled models, runtimes, fonts and redistributables before distributing installers.
- Keep native document layout limitations and model-quality evidence explicit. The [quality baseline study](plans/quality-baselines.md) remains deferred under the recorded owner exceptions.
- Preserve the [required checks](../AGENTS.md#checks), frontend tests and task-specific acceptance evidence with each implementation change.

MCP/visual editing and enterprise platform integration remain future work, not dependencies of the current desktop or website delivery. They need new scoped decisions before implementation.

## Historical planning

The [September phase roadmap](archive/IMPLEMENTATION_PLAN-2026-09.md) preserves P0-P8, D0-D2 and I1 board references and their historical completion criteria. Detailed earlier phase plans are in [the archive](archive/README.md). Consult them for history; use the current documents above for implementation.
