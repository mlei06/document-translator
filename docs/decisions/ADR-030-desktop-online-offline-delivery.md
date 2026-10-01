# ADR-030 - Automatic desktop delivery

Status: Owner-requested design, amended 2026-09-30; implementation pending. The [unified specification](../plans/unified-translator-design.md) is the current delivery contract.

## Decision and authority

The latest owner instruction supersedes earlier Online/Offline/Automatic controls and individual-credential provisioning. Installation offers Online only or Online and offline (recommended), which chooses whether the single offline bundle is installed. After installation users press Translate; no model or routing-mode selector remains.

Desktop calls Davy directly, independently of the website translation service, using the same Davy inference API key as the website deployment, injected into release packaging. No user key entry or website login is needed. Do not copy the secret into repository files, documentation, diagnostics or command-line arguments. This explicitly distributes a recoverable shared credential: signing/obfuscation/Windows protection cannot make it secret from installer recipients. Rotation/revocation affects both website and desktop; signed replacement configuration/application delivery must work independently of the website service.

Both products use Gemma, Nemotron 3 Ultra, Nemotron 3 Super, GPT-OSS Thinking, GPT-OSS and Laguna, then available HY-MT Q8_0. Website local inference is server-side; desktop local inference is on the device if installed/ready. Whole-document fallback, bounded attempts, no mixed producers and truthful provenance apply. Direct Davy/shared-key access still requires network reachability and a valid endpoint credential.

Desktop parses, fits and exports locally, sending only inference content to Davy. Neither route uses website shared cache/History. Local recent activity is bounded metadata; explicit desktop runs produce fresh exports. User originals/exports are never app-GC'd. Active temporary inputs are removed after completion/recovery. Advanced personal settings remain desktop-only but cannot override the mandatory ladder or restore removed previews/thorough fit.

Explorer translation is a release requirement, sharing the per-user queue with drag/drop. Two installers/download choices, one verified offline bundle, add/remove/repair support, authenticated local host, child-process lifecycle and safe numbered exports are specified in the unified contract. No visible Checking layout stage; standard fit remains inside Translating. Signed packaging, managed model/hardware acceptance and cold-start Davy translation with the website stopped remain release gates.

## Consequences

Turnkey shared-key installation removes individual provisioning work at the cost of shared credential exposure and coordinated rotation. The website alone owns shared translation reuse and private account History. Desktop remains independent and works locally after offline support is installed. This amendment does not change legacy explicit CLI/internal API authentication or automatically distribute their credentials.
