# Agentic-execution safety layer — deferred initiative (scope capture only)

**Status:** DRAFT — 2026-08-26. **NOT FOR IMPLEMENTATION.** This is a scope-capture stub, not an
executable plan. No operator acceptance, no implementation GO, and no work may begin from it.
**Date:** 2026-08-26
**Owning repository:** `KleinPerkins/dev` (`~/dev`)
**Plan-type:** standard
**Governing decision:** [`ADR 0010`](../adr/0010-agentic-execution-safety-layer-deferred.md) — the
agentic-execution safety layer is deferred and re-chartered as its own initiative.
**Split from:** [`doc-warden-execution-plan-v2.md`](doc-warden-execution-plan-v2.md), which now ships
only the reviewer-cleared in-boundary governance. The autonomous-execution scope moved here.

---

## Purpose and status

This stub exists so the deferred **agentic-execution safety layer** — autonomous, GSD-driven
cross-phase execution with hard-enforcement guarantees — is captured as a real, discoverable
initiative rather than silently dropped when `doc-warden` v2 shipped its in-boundary governance. It
records the end-state scope, the single design gate, and high-level milestones. It is deliberately
**not** an agentic-execution plan and carries **no** zero-context work-item contracts: nothing here
is authorized to run. Detailed rationale, the root cause, the two framing options, and the full
carried-forward finding inventory live in [ADR 0010](../adr/0010-agentic-execution-safety-layer-deferred.md).

## The single design gate

Per ADR 0010, this initiative cannot claim hard enforcement while it remains a same-user, in-repo,
no-runners local tool: every control (consent signer, command allow-list, egress quarantine, delivery
permit, tamper-evident event chain) runs in the same OS/privilege domain as the agent it tries to
constrain. **You cannot sandbox yourself from yourself without an external enforcement boundary.**
Before any implementation, the initiative must choose one framing:

- **Option B — build a real external boundary** (required for any "hard" claim): a separate,
  low-privilege, no-network OS user or sandbox for GSD sub-agents; an out-of-band signer process
  holding the consent trust root; and a credential-owning delivery broker that exclusively holds the
  push/PR credential and acts only on a verified, non-quarantined permit.
- **Option A — advisory / best-effort + tamper-evident-by-convention** with every hard-enforcement
  claim dropped.

ADR 0010 recommends **advisory (Option A) until Option B is actually built and independently
re-verified against a same-OS in-repo adversary**.

## End-state scope (only reachable after the gate)

Autonomous, cross-phase GSD execution per repository with: a genuinely external trust root; an
out-of-band consent signer; a no-network sub-agent execution domain; a credential-owning delivery
broker; an externally-witnessed tamper-evident event chain with an independently-protected head
anchor; a fully specified lease acquire/hold/expire/reclaim/steal matrix; reconciled
rollback-vs-monotonic-immutability semantics; crash-atomic recovery/continuity (WAL + startup
reconcile + Save-Game/HANDOFF seam); a closed default-deny native-GSD command allow-list with pinned
auto-advance/chain toggles; delegated-phase egress default-deny; catalog-version-skew event
compatibility; and a test
suite whose negatives traverse the real enforcement surfaces (signer-bound trust-root evidence, the
concrete PR-delivery entrypoint, and real egress attempts) rather than stopping at envelopes, mocks,
or predicates. The complete finding inventory this scope must close is enumerated in ADR 0010
Decision §5. The bounded/reversible install and `failClosed: false` global-hook baseline is already
retained under ADR 0009 and is not deferred to this initiative.

## High-level milestones (indicative only — none authorized)

1. **D0 — Framing decision.** Choose Option A (advisory, hard claims withdrawn) or Option B (external
   boundary). Record as a superseding ADR. No further milestone is authorized under a hard-claim
   framing until Option B's boundary exists.
2. **D1 — External boundary (Option B only).** Stand up the separate low-privilege/no-network
   execution domain, the out-of-band signer process, and the credential-owning delivery broker;
   prove the in-repo agent cannot read/drive/forge any of them.
3. **D2 — Enforced consent + delivery.** Bind single-use, digest-bound consent to the external
   signer; route every Draft-PR open/advance through the broker's exclusive credential; prove refusal
   on a quarantined/failed operation at the real delivery entrypoint.
4. **D3 — Dispatch closure + egress.** Interpose at every nested sub-agent/skill/capability dispatch
   edge; enforce delegated-phase egress default-deny via the no-network domain; pin auto-advance/chain
   toggles.
5. **D4 — Durable state + lease + recovery.** Durably record the preflight lease; specify the full
   reclaim matrix; reconcile rollback vs. monotonic immutability; make recovery/continuity
   crash-atomic; commit an independently-witnessed event-chain head anchor.
6. **D5 — Adversarial verification.** A fresh independent re-verification whose negatives traverse
   the real boundaries and fail if a boundary is absent or bypassed. Only then may any hard-enforcement
   claim be made, and only then may autonomous execution be enabled per repository.

## Non-goals

- Implementing any of the above, or treating this stub as an implementation authorization.
- Re-introducing autonomous GSD execution or hard-enforcement guarantees into slimmed `doc-warden`
  v2 (ADR 0009 / plan v2).
- Changing any accepted ADR, frozen plan, or the runnerless PR-automation / AWA / Save-Game / cpp
  boundaries.
