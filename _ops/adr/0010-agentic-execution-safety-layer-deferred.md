# ADR 0010: The agentic-execution safety layer is deferred and re-chartered as its own initiative

Status: PROPOSED — 2026-08-26 (Splits the autonomous GSD-driven "agentic-execution safety
layer" out of `doc-warden` v2 — [ADR 0009](0009-doc-warden-v2-gsd-aligned-governance.md) and
[`doc-warden-execution-plan-v2.md`](../plans/doc-warden-execution-plan-v2.md) — and re-charters it
as a separate future initiative. Three rounds of independent security/data-integrity/testing/
governance review converged on one root cause: a **same-user, in-repo, no-runners local tool
cannot truly enforce these guarantees against the very agent it is trying to constrain**, because
every control runs inside the same OS and privilege domain as that agent. This ADR records the
deferral, the root-cause design decision, the two framing options for the future initiative, and
**every** deferred finding so nothing is silently lost. It is not accepted and authorizes no
implementation; a real external enforcement boundary — or an explicit advisory re-framing with the
hard claims dropped — must be decided first.)

**Decider:** Laurence Duggan
**Owning repository:** `KleinPerkins/dev` (`~/dev`)
**Related plan:** [`agentic-execution-safety-layer-deferred-v1.md`](../plans/agentic-execution-safety-layer-deferred-v1.md) (DRAFT — not for implementation)
**Relates-to:** [`ADR 0009`](0009-doc-warden-v2-gsd-aligned-governance.md) (retained in-boundary governance) and [`doc-warden-execution-plan-v2.md`](../plans/doc-warden-execution-plan-v2.md) (slimmed to in-boundary scope)
**Supersedes:** nothing. This ADR removes scope from the still-PROPOSED ADR 0009; it does not alter any accepted decision.

## Context

`doc-warden` v2 (ADR 0009 / plan v2) proposed two separable things:

1. **In-boundary governance** — the artifact schema (UX requirements/designs/prototypes/execution
   plans/roadmap/defect-backlog), referential integrity and code anchors, dynamic documentation
   rigor, the canonical nontechnical PRD, migration of existing repositories, new-repository
   instantiation, NLP-first operator verbs, and Save-Game/continuity **for authoring**. Independent
   review explicitly **cleared** this layer as sound and in-boundary. It stays in the (now slimmed)
   ADR 0009 / plan v2.

2. **An agentic-execution safety layer** — autonomous, GSD-driven execution of work across a
   repository, wrapped in a set of **hard-enforcement** guarantees: network-egress quarantine before
   delivery, unforgeable single-use operator consent, closure over nested sub-agent/skill/capability
   dispatch, an exclusive credential-owning delivery chokepoint, and a tamper-evident event chain.
   Three successive independent swarms (a critical-band probe-blind swarm on rev 3; a Deep-band
   `plan-refine` swarm on rev 4; and two genuine top-level isolated re-verification swarms — four
   specialist reviewers plus one gated verifier each — that FAILED clearance on rev 4 and rev 5)
   found the *architecture and plan↔ADR consistency* sound, but the *hard-enforcement claims*
   unachievable in the stated execution model. The findings were 1 P0 + 13 P1, all reducing to one
   root cause.

### The root cause (the central design decision of this ADR)

The layer claims to constrain an autonomous agent using controls — a consent signer, a command
allow-list, a network-egress quarantine, a delivery permit, a tamper-evident event chain — that all
execute **as the same OS user, inside the same repository, with no runners and no external
process**. An agent (or a compromised/over-eager sub-agent) with that same identity can read the
signer's key material, edit the "append-only" event log and its head pointer, disable or re-point a
"fail-closed" hook, reach the network before any local quarantine predicate runs, and open a PR
through any credential it can already see. **You cannot sandbox yourself from yourself without an
external enforcement boundary.** Every one of the reviewer findings below is a specific instance of
that single truth. This is why the guarantees cannot be truthfully labeled "hard enforcement" in a
same-user/in-repo/no-runners tool — no matter how many schemas, predicates, and negative tests are
added, they all live on the wrong side of the boundary.

## Decision

1. **Defer and re-charter.** The agentic-execution safety layer is removed from doc-warden v2's
   in-boundary scope and re-chartered as its own future initiative, governed by this ADR and its
   companion deferred plan stub. doc-warden v2 ships the reviewer-cleared in-boundary governance
   now; the execution layer does not ship with it and is not implied by it.

2. **Name the root cause as the gating decision.** No future revision of this layer may claim hard
   enforcement while it remains a same-user, in-repo, no-runners tool. The prerequisite for any hard
   claim is a **real external enforcement boundary** — a trust root and/or execution domain the
   in-repo agent provably cannot read, drive, or forge.

3. **Two framing options for the future initiative.** The initiative must pick one before it may be
   implemented:

   - **Option B — build a real external boundary (required for any "hard" claim).** Introduce
     genuine out-of-band enforcement: run GSD sub-agents as a **separate, low-privilege, no-network
     OS user** (or an OS sandbox / container) that the primary agent cannot impersonate; hold the
     consent **trust root in a separate signer process** whose key material the in-repo agent cannot
     read or drive; and route delivery through a **credential-owning delivery broker** that is the
     only holder of the PR/push credential and only acts on a verified, non-quarantined permit. Only
     with such a boundary can egress-quarantine, unforgeable consent, dispatch closure, an exclusive
     delivery chokepoint, and a tamper-evident chain be truthfully enforced. This is a materially
     larger, cross-process build with its own operational cost.

   - **Option A — keep it explicitly advisory / best-effort + tamper-evident-by-convention.** Drop
     every "hard-enforcement" claim. Describe the controls honestly as **advisory** (they catch
     mistakes and honest drift, not a determined same-user adversary), make the event chain
     **tamper-evident by convention** (detectable-after-the-fact, not tamper-proof), and never
     promise egress quarantine, unforgeable consent, or an exclusive delivery chokepoint. This is
     cheap, honest, and shippable inside the current model — but it is not a security boundary.

4. **Recommendation: advisory until a real boundary exists.** Until Option B's external boundary is
   actually built and qualified, this layer stays **advisory-only (Option A wording)**, with the
   hard claims explicitly withdrawn. Reintroducing any hard-enforcement language requires Option B
   to be in place and independently verified against a same-OS in-repo adversary. This keeps operator
   copy honest (no "protected"/"quarantined"/"unforgeable" promise the tool cannot keep) and matches
   the ecosystem's kernel-first, honest-copy doctrine.

5. **Carry every deferred finding forward (no silent drops).** The open problems below travel with
   this initiative. Each is stated as an open design problem against the root cause, not as a solved
   mechanism. They are the acceptance surface a future Option-B design must actually close.

   **Security / enforcement boundary (the P0 + P1 core):**
   - **P0 — network egress precedes quarantine.** A delegated GSD phase (and its sub-agents) can
     reach the network *before* any local "quarantine" predicate runs, because nothing external gates
     egress. A local predicate cannot un-send a request. Requires a no-network execution domain
     (Option B), not a predicate.
   - **Consent signer is not bound to an unforgeable trust root (V4).** The signer that mints the
     "single-use, digest-bound" consent envelope runs as the same user; the in-repo agent can read or
     drive its key material, so consent is forgeable. Requires an out-of-band signer.
   - **Nested-dispatch closure is not interposed (V3).** The command allow-list closes only top-level
     command IDs; an allowed phase can transitively auto-invoke unlisted, code-mutating, or
     network-reaching sub-skills/agents/capabilities. Nothing actually interposes at each nested
     dispatch edge in a same-user model.
   - **The delivery permit has no exclusive credential-owning entrypoint (V6).** The "fail-closed
     delivery-permit chokepoint" is a predicate the agent may simply not call; delivery can occur
     through any credential the agent already holds. A real chokepoint requires a broker that
     exclusively owns the credential.
   - **The event-chain head anchor is not independently trusted (V5).** A same-user writer can delete
     the newest event together with its receipt and rewrite the "independently-protected" head
     anchor, so tail-truncation is undetectable without an out-of-band anchor. Tamper-*evidence*
     needs an external witness; in-repo it is at best convention.

   **State / lifecycle integrity:**
   - **Rollback vs. monotonic immutability conflict.** The design simultaneously promises an
     append-only, monotonic, immutable event chain and a program/rollback capability that must undo
     state. The two are not reconciled; a rollback that mutates or truncates the "immutable" chain
     violates the immutability claim. The future initiative must define compensation-forward vs.
     truncation semantics explicitly.
   - **Recovery / continuity state is under-specified and not crash-atomic.** WAL-ordered durability,
     startup reconcile, and the Save-Game/HANDOFF continuity seam are described but not proven
     crash-atomic; a crash inside the native window can leave partially-applied state with no defined
     recovery invariant.
   - **Gateway lease reclaim matrix (V1/V7).** The repository-scoped exclusive lease is not durably
     recorded at preflight and can be stranded by a crash inside the native window; the full
     acquire/hold/expire/reclaim/steal matrix (including a no-longer-live holder) is unspecified.
   - **`repository-key-rebind-invalidates-preview` (V8, transactional form).** A preview computed
     against one `repository_key` must be invalidated if the key rebinds before apply, and a
     present-but-malformed/unparseable config must fail closed (`repository_key_unreadable`) rather
     than re-mint a split identity. **Judgment call (stated):** the `repository_key` *identity*
     (mint-once, adopt-persisted) is foundational to migration/identity and is **retained** in
     slimmed plan v2's migration scope; but the **transactional preview→apply rebind guard and the
     malformed-config fail-closed re-mint refusal are enforcement-grade guards of the deferred
     transactional-apply/consent layer and are deferred here** with the rest of the enforcement
     surface. The retained migration rule is "never split one repository across two keys"; the
     enforced fail-closed transactional form is Option-B scope.

   **Dispatch / command scope:**
   - **GSD command allow-list.** The closed default-deny native-GSD command allow-list (admit only
     `gsd:discuss-phase`/`gsd:ui-phase`/`gsd:plan-phase`/`gsd:execute-phase`/`gsd:verify-work` plus
     within-phase `gsd:pause-work`; deny the phase-chaining drivers `gsd:autonomous`/`gsd:next`/
     `gsd:phase`/`gsd:manager`/`gsd:progress`/`gsd:resume-work`/`gsd:ship`, the `gsd:ns-*` routers,
     and every unknown/future command) is an **execution-layer control** and moves here in full.
     Canonical phase order is **discuss, ui, plan, execute, verify**; `pause` is a within-phase
     checkpoint, not a sixth phase, and is compared separately in command-set equality.
     Auto-advance/chain toggles
     (`workflow.auto_advance`, `workflow._auto_chain_active`, `--auto`/`--chain`) must be pinned as
     defense-in-depth (V2). In a same-user model none of this is enforceable against a determined
     agent; it is advisory until Option B.
   - **Retained live-install baseline (CG-new-1; not deferred here).** Installing v2's runtime touches
     global Cursor surfaces (hooks, skills, Canvas). ADR 0009 therefore retains the bounded/reversible
     install and requires every doc-warden-owned global hook to set `failClosed: false`; v2 must ship
     that baseline independently of this future initiative. Only any security-grade external signer
     qualification or execution containment layered onto installation belongs here.
   - **Delegated-phase egress default-deny (CG-new-2).** A GSD sub-agent can reach the network/
     external services via toggleable capabilities inside a delegated phase; default-deny is only
     real with an external no-network domain (see P0).

   **Compatibility / evidence:**
   - **Catalog-downgrade event compatibility.** Downgrading or changing the capability/trigger
     catalog must remain forward/backward compatible with previously-emitted events; the
     compatibility matrix and migration for catalog-version skew is unspecified.
   - **One-shot local resume handoff (V9) and stale cross-references (V10).** Locally-reconstructed
     resume needs an explicit one-shot handoff event so a resume cannot double-execute; and resume
     reconstruction must not point at a moved/renamed section (the rev-5 pointer at §3.10 was stale).
   - **Testing gaps.** The prior negatives stopped at envelopes/mocks/predicates rather than
     traversing the real enforcement surface: consent tests asserted envelope shape instead of
     **signer-bound trust-root evidence** the in-repo agent cannot produce; delivery tests called a
     **predicate** instead of the **concrete PR-delivery entrypoint**; egress/quarantine tests never
     attempted real egress. A future Option-B design must prove each guarantee with a negative test
     that exercises the actual boundary and fails if the boundary is absent or bypassed.

6. **Document the deferred end-state scope** so nothing is silently lost. The end state of this
   initiative (only reachable after Option B or an explicit Option-A re-charter) is: autonomous,
   cross-phase GSD execution per repository with a genuinely external trust root, an out-of-band
   consent signer, a no-network sub-agent execution domain, a credential-owning delivery broker, an
   externally-witnessed tamper-evident event chain, a fully specified lease acquire/hold/reclaim
   matrix, reconciled rollback-vs-immutability semantics, crash-atomic recovery/continuity, and a
   test suite whose negatives traverse the real enforcement surfaces. The companion deferred plan
   stub records this end state and high-level milestones without authorizing any of it.

## Why

### Alternatives considered

- **Ship v2 as-is with the hard-enforcement claims.** Rejected: three independent reviews found the
  claims unenforceable in a same-user/in-repo/no-runners tool. Shipping them would put a dishonest
  "protected/quarantined/unforgeable" promise in front of the operator — exactly the failure mode the
  ecosystem's kernel-first, copy-honesty doctrine exists to prevent.
- **Silently drop the layer.** Rejected: the deferred design work and the reviewer findings are
  valuable and must not be lost. This ADR + the deferred plan stub capture them in full.
- **Keep the layer in v2 but "soften the wording" in place.** Rejected: the layer is large,
  cross-cutting, and gated on an unbuilt external boundary; leaving it entangled in v2 would block the
  cleared in-boundary governance from shipping and keep over-claims one edit away from returning.
  A clean split with its own ADR and plan is the durable structure.
- **Build the external boundary now (Option B immediately).** Deferred, not rejected: it is a
  materially larger cross-process build (separate OS user/sandbox, out-of-band signer, delivery
  broker) with its own operational cost and no present consumer demanding it. It is the right path
  *when* autonomous execution is actually needed; until then advisory (Option A) is honest and cheap.

## Consequences

### Enables

- doc-warden v2's reviewer-cleared in-boundary governance ships now without waiting on an unbuildable
  (in this model) enforcement layer.
- Operator-facing copy stays honest: no hard-enforcement promise the tool cannot keep.
- The deferred initiative has a clear, single design gate (the external boundary) and a complete,
  carried-forward finding inventory to design against.

### Costs

- Autonomous GSD-driven execution is not available in v2. Operators author, reconcile, and govern in
  v2; they do not get one-command autonomous cross-phase execution until this initiative ships.
- A future Option-B build is non-trivial (separate low-priv user/sandbox, out-of-band signer,
  delivery broker) and must be independently re-verified against a same-OS in-repo adversary before
  any hard claim.

### Invariants

- No same-user/in-repo/no-runners revision of this layer may claim hard enforcement. Advisory wording
  only, until an external boundary exists and is verified.
- The findings in Decision §5 are the minimum acceptance surface for any future hard-enforcement
  claim; each must be closed by a negative test that traverses the real boundary.
- This ADR removes scope from the still-PROPOSED ADR 0009 only; it changes no accepted decision and
  no frozen artifact.

## Non-goals

- Implementing, or authorizing implementation of, the agentic-execution safety layer.
- Building the external enforcement boundary (Option B) as part of doc-warden v2.
- Re-introducing autonomous GSD execution or its hard-enforcement guarantees into slimmed v2.
- Changing any accepted ADR, frozen plan, or the runnerless PR-automation / AWA / Save-Game / cpp
  boundaries.
