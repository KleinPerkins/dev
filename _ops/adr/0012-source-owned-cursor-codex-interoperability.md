---
{"approval":{"actor":"operator","date":"2026-10-27","review_sha256":"f1ccb63a6c9a5ee983572b63dd5bcf63440ac4f93ca5860b33be090ea4b57502"},"authority":"semantic","github_repository_id":1278387789,"id":"ADR-54aec621-9236-53d2-87b7-9a60ef4ec92e-9cbb9f0e-b89b-5d64-8168-d26ded302e6b","lifecycle":"approved","mutability":"frozen_after_approval","provenance":[],"relations":[],"repository_key":"54aec621-9236-53d2-87b7-9a60ef4ec92e","schema":"doc-warden/artifact/v2","supersedes":null,"type":"adr","version":1}
---
# ADR 0012: Source-owned Cursor/Codex interoperability

Status: Accepted — 2026-10-27. Owner: KleinPerkins/dev. Canonical lifecycle and approval evidence are recorded in the generated metadata. This decision adopts the reviewed integration architecture; it does not start ecosystem retrofit.

## Context

The home ecosystem has reusable capability sources and strong component boundaries, but source-to-host projection currently depends on installed Cursor rules and MCP configuration. Several imported instructions rename Cursor concepts as Codex; native hook, model and workspace semantics differ. The 2026-10-27 audit identified reproducibility and semantic-qualification gaps, including a Codex exposure of prompt-architect that was not reproducible from owned source at audit time.

Requirements REQ-INT-001–020 are approved for planning, with mcp-builder removed from required additions. The product decision alone did not authorize implementation or profile mutation. Repository adoption and acceptance of the requirements, design and plan were subsequently applied through separately confirmed doc-warden operations. Detailed evidence is in the accepted design appendices; this ADR does not repeat AWA, MCP or downstream product contracts.

## Decision

Adopt the source-owned integration architecture described in SPEC.md, decisions DEC-01–DEC-11. Shared policy and reusable behavior remain in their existing owners. Host adapters translate supported native discovery, instructions, configuration, dispatch, role declarations, hooks and presentation. Private host overlays supply machine-specific values. Installed host files are projections and do not become authority for other hosts.

Keep existing kp-capability/v1 metadata and bootstrap destinations initially; repair only the two required skill exposures through existing fields. Extend existing MCP registrars rather than creating a competing writer. Require native evidence per advertised host operation. Preserve deliberate host-specific isolation and document material exceptions.

The dev repo owns this integration decision, its host policy and wiring, and its Git guards. AWA alone owns workspace/lifecycle/kernel semantics; its accepted identity constraints and deferred-work NO-GO gates remain in force. The orchestrator alone owns the global-to-cpp distribution edge. Component design changes are accepted in their owners before dependent implementation; this integration ADR is not a substitute for those decisions.

## Alternatives

1. Continue mirroring Cursor installations: smallest immediate diff, but retains stale authority and semantic mismatches; rejected as the target architecture.
2. Fork the ecosystem for Codex: permits local tuning but duplicates policy, safety behavior and fixes; rejected as the default.
3. Build a universal execution/security framework: expands scope into deferred governance and AWA work without evidence it is necessary; rejected.
4. Shared behavior plus qualified native adapters: selected because it reuses current architecture and makes material differences explicit.

The scoped Codex bootstrap lane in the design’s Appendix A was explicitly approved with the architecture and plan. It temporarily replaces the impossible Cursor-only entry/resolver steps for named prerequisite tasks, with fixed scope, offered-model checks and expiry. It does not claim AWA registration or inherit the audit-only exception. If that bounded lane cannot be satisfied, those tasks require a separately arranged compliant Cursor lane or a new explicit scope decision.

## Consequences and constraints

- Additional adapter contract tests and native canaries are required; support claims become narrower and more accurate during migration.
- Existing Cursor behavior and Claude compatibility must remain intact unless an explicitly accepted change says otherwise.
- Codex AWA entry/protection remains unqualified until an AWA-owned successor decision and evidence support it; missing identity cannot be fabricated.
- Native archive stays distinct from AWA Close and delivery. MCP/connector authentication and external-write authority are not broadened.
- Compatibility observations are evidence, never authorization. No new routing-enforcement hooks or admission framework are introduced.
- Installation, live activation and downstream distribution remain distinct gates. No chaos-scheduler or protected automation change is permitted.

## Acceptance and delivery

The operator approved the architecture choices, scope exceptions, acceptance budgets and execution plan on 2026-10-27. The prerequisite ADR-authoring repair and accepted planning package are delivered in [PR #374](https://github.com/KleinPerkins/dev/pull/374), merged as `bd65600e13e00ffe3f30239a157a905841201017`. Canonical acceptance of this ADR uses that merged semantic route, preserving the owner ADR directory, exact consent, freeze behavior and legacy receipts. The final rendered body and exact write operation require operator confirmation before apply.

After qualified acceptance, run applicable docs checks and deliver the ADR, engine-generated mutable index update and acceptance evidence through normal repository review/merge authority. Document acceptance and implementation authorization remain separately recorded. The zero-context retrofit prompt is drafted only after verified merge of the approved package.

## Owner references

- dev: `_ops/POLICY.md`, `_ops/doc-warden/POLICY.md`, accepted ADR 0009; deferred ADR 0010 is not implementation authority.
- AWA: `docs/adr/0002-awa-dev-overlay.md`, `0020-awa-integrity-surveillance-and-lifecycle.md`, `0024-first-prompt-native-entry-recovery.md`, and the NO-GO boundaries of `0026-durable-registration-authority-hardening.md`.
- Skills, kp-mcp, ecosystem-orchestrator and cpp: their own AGENTS, source contracts and accepted decisions. No cross-repo prose here supersedes them.

## Canonical planning references

Convenience names in this decision resolve to these accepted records:

- [PRD.md — requirements](../../.planning/artifacts/PRD-54aec621-9236-53d2-87b7-9a60ef4ec92e-47748eb9-9653-5148-96b2-80bf7b94ca63-v1.md).
- [SPEC.md — design](../../.planning/artifacts/SPEC-54aec621-9236-53d2-87b7-9a60ef4ec92e-a4c352cf-6b55-5106-b60a-3a16e18e9a55-v1.md); BOOTSTRAP.md is Appendix A, exceptions Appendix B, audit Appendix C and catalog Appendix D.
- [PLAN.md — execution and validation](../../.planning/artifacts/PLAN-54aec621-9236-53d2-87b7-9a60ef4ec92e-1e8178fc-9a09-5574-92ee-1989032fd29a-v1.md).
- [GOVERNANCE-REPAIR.md — approved prerequisite specification](../../.planning/artifacts/SPEC-54aec621-9236-53d2-87b7-9a60ef4ec92e-a3ae1cb3-af86-50bb-b183-4c72d7bd1863-v1.md).
- [Sanitized audit inventories](../interoperability/evidence/2026-10-27/).

Acceptance operation `aac1fccf-d1a7-4468-9996-f49ba1e0d0ab` records the planning package; adoption operation `e980e045-5de2-40f7-905a-0d91e387198f` records the repository profile. Their receipts remain unchanged. Historical status statements in accepted artifacts describe their acceptance-time state; this later ADR records completion of the authoring prerequisite without rewriting those artifacts.
