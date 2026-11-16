# `_ops/adr/` — architecture decision records

This directory holds durable architecture decisions for `KleinPerkins/dev` — the "why," not the
"how" (that's `_ops/plans/`). Convention adapted from `personal/pr-automation-controller/docs/adr/README.md`,
the fleet's clearest existing precedent, with paths adjusted for this repo's `_ops/`-based layout.

## The convention

1. **Header.** `# ADR NNNN: <title>` (4-digit, zero-padded, sequential — never reused, even if a
   later decision reverses an earlier one), then `Status: <status> — YYYY-MM-DD` on the next line.
2. **Body.** An optional short intro paragraph, then `## Decision`, `## Why`, `## Consequences`.
   Add `## Context` or a live-state verification record when the decision depends on point-in-time
   ground truth.
3. **Immutability.** An accepted ADR is never rewritten to reflect new information, not even a small
   in-scope correction — write a new, higher-numbered ADR that supersedes it (cross-link both
   directions). This is **stricter** than `pr-automation-controller/docs/adr/README.md`'s own
   convention, which permits an inline `> Update - ...` blockquote for a small in-scope correction
   (see its `0002-v2.27-operating-decisions.md` §1 for a live example) — doc-warden deliberately does
   not carry that exception forward, per the operator's byte-identical-forever decision for this
   repo's governance artifacts.
4. **ADRs vs. `_ops/plans/`.** An ADR records a durable decision and its rationale (rarely changes
   once accepted). A plan document records execution detail for carrying out work (scope,
   sequencing, acceptance tests, an owner GO/NO-GO gate) and is expected to be superseded by later
   versions as work proceeds.
5. **Discoverability.** Read this file before adding a new architecture decision or trying to find
   out why an existing one was made. `_ops/POLICY.md` §9 points here.

## Successor provenance

Frozen ADR bytes retain their original decisions and identities. The current
source delivery policy in `../POLICY.md` supersedes the retired-controller default
and narrow native-delivery exceptions. Retained ADRs do not grant current host
activation, recreate old receipts or restart paused work. The successor adoption
record binds the retained policy set separately. New successor ADRs are discovered
under `docs/adr/`, not by reassigning these frozen predecessor envelopes.

Historical status is a predecessor fact, not successor authority. The index below
projects recorded predecessor decisions; words such as Accepted, Superseded and
authoritative apply only within that historical record. Later scoped amendments
do not rewrite an earlier frozen body. New successor authority requires its own
current accepted decision and applicable execution gates.

ADR 0013 illustrates a retained wording conflict. Its metadata records predecessor
lifecycle `approved`, approval date 2026-11-01 and a supersedes relation to
ADR 0012. Its frozen title and body still say proposed/not accepted and describe
acceptance as a future gate. Those body statements are original draft-era wording,
not a reversal of the recorded historical acceptance. The exact retained file was
delivered in predecessor commit
`fa60edb8079ad2a7a8ec8f8094ab0ec6daa7ff42` (PR #402). Applied
`accepted_freeze` operation `0b51b5ba-915a-4c30-b4e2-2e9b7b5a7ef2`
records its postimage SHA-256
`a82bfb2c751c606be419ac1bba81d963cfad61b64db9668c57f3fcca9159ebb1`.
The historical receipt has file SHA-256
`a034bc08d47cd268adcc3abfe2b842c411fa7b7ed72738e578902d240c8fb14b`.
These are provenance identifiers verified from predecessor Git objects; the
receipt is not imported or replayed, and no new approval is claimed.

The ADR 0013 relation amends only the specified coordinated-maintenance scope;
its body expressly incorporates ADR 0012's other requirements unchanged. Preserve
both records' metadata and bodies byte-for-byte. Their historical acceptance and
conditional D1/D2 language do not approve a successor plan, resume implementation,
qualify an installed runtime or authorize host activation, registration or global
retirement. The successor remains limited to its separately reviewed source
baseline and ordinary artifact transactions; excluded paused work stays paused.

ADR 0017's metadata separately records exact draft-byte review. That review field
alone is not freeze consent. Historical applied `accepted_freeze` operation
`55061ba9-583d-448c-9a0a-d76c1a2365f1` at predecessor commit
`0b829258881ed43a7e7023cc988836825169130f` binds its retained postimage
`494edd63de1f9b147a58e3396a0d47a047e2aa8895d54328b1ca4238d5b7632a`.
This distinct historical operation also grants no successor authority.

## Historical index

| ADR | Status | One-line decision |
|---|---|---|
| [0001](0001-doc-warden-owning-subsystem.md) | Historically accepted — 2026-08-05; scoped amendment by [0009](0009-doc-warden-v2-gsd-aligned-governance.md) | `doc-warden` lives as a sibling `_ops/` subsystem, not a capability shelf, not folded into `baseline-lib.sh`. Historically accepted ADR 0009 supersedes only its product/runtime boundary. |
| [0002](0002-doc-warden-reconciliation-doctrine.md) | Accepted — 2026-08-05 | Shared reconciliation doctrine/contract (not shared runtime) across `doc-warden`, `server-guard`, and cpp's integrity engine — evidence-forced by existing cross-language implementations. |
| [0003](0003-doc-warden-local-only-no-cpp.md) | Accepted — 2026-08-05 | `doc-warden` is local-only; cpp is read-only comparison input only, never a delivery target. |
| [0004](0004-optimize-context-projections-without-moving-authority.md) | Superseded — 2026-08-16 | Immutable historical decision; superseded by [0005](0005-harden-context-measurement-before-e09.md). |
| [0005](0005-harden-context-measurement-before-e09.md) | Accepted — 2026-08-16 | Keep the v1 counting algorithm but require canonical ordering, closed v2 receipts, controlled exits, and exact remote coverage before E-09. |
| 0006 | Privately preserved | Work-specific draft; intentionally absent from public operating-model source. Number remains reserved. |
| 0007 | Privately preserved | Work-specific draft; intentionally absent from public operating-model source. Number remains reserved. |
| [0008](0008-chaos-scheduler-doc-warden-docs-governance.md) | Accepted — 2026-08-22 | `chaos-scheduler` is doc-warden-governed for documentation only; it stays hard-excluded from `repo-baseline`/pr-automation and the local fleet sweep, enforced on-demand via `doc-warden.sh check` and at PR time (no engine change). |
| [0009](0009-doc-warden-v2-gsd-aligned-governance.md) | Accepted — 2026-08-28 | **doc-warden v2 in-boundary governance.** Exact-pinned GSD Core via a dependency-locked `_ops` host-overlay binding for **authoring/context**, plus a local `doc-warden` governance overlay and `~/dev` fleet orchestration: per-repository authority, the typed artifact schema, referential integrity/code anchors, deterministic dynamic rigor, canonical nontechnical PRD, migration and new-repo instantiation, NLP-first operator verbs, and Save-Game **for authoring**; semantic authorities stay frozen while state/rollups are mutable projections. Supersedes ADR-0001's product/runtime boundary. The net-new **agentic-execution safety layer** (autonomous GSD execution + its hard-enforcement guarantees) is **removed and deferred to [0010](0010-agentic-execution-safety-layer-deferred.md)**. Prospectively amended by [ADR 0016](0016-canonical-typed-plan-authority-and-acceptance.md) only for typed-plan location and checker/acceptance rules; otherwise remains Accepted and authoritative. |
| [0010](0010-agentic-execution-safety-layer-deferred.md) | Proposed — 2026-08-26 | The **agentic-execution safety layer** — autonomous GSD execution + hard-enforcement guarantees (network-egress quarantine, unforgeable single-use operator consent, nested-dispatch closure, an exclusive credential-owning delivery chokepoint, a tamper-evident event chain) — is **deferred and re-chartered** out of [0009](0009-doc-warden-v2-gsd-aligned-governance.md) / plan v2. Root cause: a same-user/in-repo/no-runners tool cannot enforce these without a real **external boundary** (*you cannot sandbox yourself from yourself*). Two framing options — **(B)** build a real external boundary; **(A)** advisory/best-effort + tamper-evident-by-convention — with advisory recommended until a boundary exists. Carries the complete 1 P0 + 13 P1 finding inventory. Not accepted; authorizes no implementation. |
| [0011](0011-manifest-driven-verification-selector.md) | Accepted — 2026-09-02 | Adopt approved Option 2 as the direction: one repository-local closed manifest, sole InputRule ownership, strict additive JSON Pointer semantics only, exact linked shadow/full receipts, fixed ISO-week/calendar-month surveillance with fail-closed grace deadlines, and paired ≥3× speed proof. Checkpoint 0 (2026-09-02) recorded `accept` for D2–D5 and authorized the three-artifact documentation acceptance merge; that merge commit freezes the three whole artifacts (index files stay mutable projections), and M0 later mirrors them into ledger genesis. Only the contingent M0-T01 bootstrap is authorized; implementation GO for M1 onward stays gated by later checkpoints. |
| [0012](0012-source-owned-cursor-codex-interoperability.md) | Historically accepted — 2026-10-27; scoped amendment by [0013](0013-coordinated-maintenance-for-source-owned-mcp-migration.md) | Source-owned Cursor/Codex interoperability; ADR 0013 amends only its specified coordinated-maintenance scope and incorporates all other requirements unchanged. |
| [0013](0013-coordinated-maintenance-for-source-owned-mcp-migration.md) | Historically accepted — 2026-11-01; no successor approval | Coordinated maintenance for source-owned MCP migration. Original proposed/not-accepted wording is retained within frozen bytes; the historical applied acceptance and present authority limit are explained above. |
| [0014](0014-shadowsync-native-github-delivery-exception.md) | Accepted | ShadowSync native GitHub delivery exception |
| [0015](0015-dev-owned-shadowsync-host-policy-projection-and-atomic-binding.md) | Accepted | Dev-owned ShadowSync host-policy projection and atomic binding |
| [0016](0016-canonical-typed-plan-authority-and-acceptance.md) | Accepted | Canonical typed plan authority and acceptance |
| [0017](0017-machine-monitor-native-delivery-and-mandatory-new-repository-test-sharding.md) | Accepted | Machine Monitor native delivery and mandatory new-repository test sharding |
| [0018](0018-independent-repository-visibility-and-distribution.md) | Accepted | Independent repository visibility and distribution |
