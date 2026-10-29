# Architecture Decision Records

ADRs capture the **why** behind significant, hard-to-reverse decisions — the
context, the choice, and what it costs us. They are immutable once accepted: to
change a decision, write a new ADR that supersedes the old one rather than
editing history.

| # | Decision | Status |
|---|---|---|
| [0001](0001-jwt-auth.md) | JWT access + rotating refresh tokens | Accepted |
| [0002](0002-renderer-orchestration.md) | Unified renderer orchestration with pluggable backends | Accepted |
| [0003](0003-cast-stream-token-policy.md) | Duration-aware stream-token TTL for Cast | Accepted |
| [0004](0004-cast-dual-control-path.md) | Two Cast control paths (server-driven + device-direct) | Accepted |
| [0005](0005-scanner-two-phase.md) | Two-phase library scan (scan, then enrich) | Accepted |
| [0006](0006-renderer-capability-contract.md) | Optional renderer capabilities (queue ownership, staging, pairing, output) | Accepted |
| [0007](0007-airplay-raop.md) | AirPlay/RAOP via pyatv: evaluated on hardware, not built | Accepted |
| [0008](0008-fire-tv-matter-casting.md) | Fire TV: no Fling; Matter Casting not viable for a server today | Proposed |
| [0009](0009-dlna-server-and-bridge-roles.md) | DLNA server and renderer-bridge roles: arbitration first | Proposed |
| [0010](0010-continuous-stream-mode.md) | Continuous-stream mode for seamless Cast album playback | Proposed |
| [0011](0011-openhome-linn.md) | Native OpenHome/Linn backend: evaluated, not built | Accepted |

New ADRs use the next number and the [template](template.md).
