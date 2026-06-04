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

New ADRs use the next number and the [template](template.md).
