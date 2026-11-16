# doc-warden v2 policy

**Status:** ACTIVE
**Version:** 2.0.0
**Active trigger catalog:** 2.1.0
**Governing decision:** ADR 0009
**Scoped prospective amendment:** [ADR 0016](../adr/0016-canonical-typed-plan-authority-and-acceptance.md), C1–C4 (including C2a), governs typed-plan location and acceptance. ADR 0009 otherwise remains authoritative.
**Activation:** M1-T05 atomically promoted this policy with the compatible v2 dispatcher,
schema, trigger catalog, templates, and exact GSD runtime binding. M3-T02 atomically expands
only the typed operator, advisory-hook, and read-only-maintenance trigger entry points in catalog
2.1.0. Explicit `legacy-v1` aliases retain the retired dispatch surface until M6.

## Scope

Doc-warden v2 governs repository-local project, PRD, requirement, UX, design, technical
specification, ADR, plan, roadmap, defect, verification, UAT, release, and generated projection
records. It consumes the exact GSD Core pin only for qualified authoring/context workflows. It does
not provide autonomous implementation, cross-phase scheduling, SCM delivery, worktree creation,
merge, tag, or release execution.

## Authority and identity

- Each repository has one immutable UUID `repository_key`; remote identity is a separate nullable
  `github_repository_id`.
- Semantic records have UUID-backed stable IDs and explicit versions. Approved/accepted versions
  freeze; changes require successors.
- Generated views, state, indexes, and fleet rollups are replaceable projections and never semantic
  authority.
- Relations use the closed vocabulary in `relation.schema.json`, distinguish planned from observed
  facts, and bind exact versions/revisions where meaning depends on them.

## Canonical records

All persisted v2 records validate against the closed schemas in `_ops/doc-warden/schemas/v2/`.
Canonical JSON is UTF-8, lexicographically key-sorted, compact, integer-only, and newline-terminated.
Markdown metadata is one canonical JSON object between the first `---` pair. Duplicate keys,
unknown schemas, unknown fields, floating-point values, or content before metadata are refused.

Only `accepted_freeze` freezes semantic bytes. `creation_snapshot` records creation without turning
later authoring into drift. V1 receipts remain byte-identical legacy evidence; adoption records
their observed meaning and never invent acceptance.

## Lifecycle and prerequisites

Feature technical planning requires an approved PRD with stable requirement IDs. A defect may use
the narrow exemption only when all five ADR 0009 conditions remain true; scope growth promotes it
to the feature path. UI work additionally requires UX requirements, approved design, provenance,
state/accessibility/responsive coverage, and visual UAT. Sensitive work stacks its security,
privacy, evidence-egress, rollback, review, and operator gates on the base rigor class.

Priority describes importance. Sequence, wave, and dependency describe order. Changing either never
silently changes the other. Completion requires outcome evidence.

## Mutations and receipts

Every mutation starts as a deterministic preview bound to one operation ID, repository key,
canonical root, source revision, preimages, exact output bytes, and action digest. Consequential
apply requires an exact operation-bound explicit confirmation. A reusable boolean or copied
approval is invalid. Retries with the same operation and inputs return the same receipt; changed
inputs refuse.

Writes are confined to relative paths beneath the canonical repository or declared XDG root.
Absolute/escaping paths, symlinked writable components, special files, changed roots, and changed
preimages are refused. Files are staged as same-directory regular files and atomically replaced.
Receipts bind live policy, schema, trigger, template, GSD pin, and approved-plan digests.
`delivery_commit` remains null until a later observed-delivery event can name a real commit.

This in-boundary transaction contract is operational mistake/drift hygiene, not a security boundary
against a determined same-user agent. Security-grade leases, signer isolation, tamper-evident event
chains, delivery permits, and autonomous dispatch remain deferred to ADR 0010.

## Reconciliation and egress

Reconciliation compares frozen authorities, mutable roadmap/state, code/SCM observations, and
external revisions at exact source revisions. Safe projection changes may be previewed. Semantic
ambiguity, duplicate authority, changed accepted assumptions, cycles, contradictions, and
unverifiable assets report without mutation.

Durable sinks accept only their closed projections. Credentials, secrets, customer data,
unnecessary PII, prompts, transcripts, source bodies, diffs, raw logs/environment, and arbitrary
URLs are forbidden. External assets require an immutable provider revision, canonical URL, source
repository identity, nullable source commit, export digest, timestamp, owner, and license or
internal-use classification.

## Operator proposals, triggers, hooks, and maintenance

Ordinary language, the thin skill, explicit CLI, and native-dispatch descriptions share one closed
intent map. Router output is a proposal only. It never authorizes, confirms, or executes an action.
Read-only intents do not request confirmation. Consequential intents require the same fresh
operation-ID/action-digest-bound confirmation used by the engine; ambiguity across consequence
classes writes nothing and asks the operator to choose one route.

Trigger catalog 2.1.0 preserves the six M1 engine triggers and adds only session context,
significant-file freshness, external-design refresh, repository-dependency observation, and
serialized routine-maintenance primitives. Every detector, action, template, and verifier name is
closed and has exactly one runtime handler; unknown fields, unknown names, and arbitrary shell are
refused. V1 trigger IDs remain readable through an explicit migration map whose incompatibilities
are recorded rather than silently translated.

User hooks are advisory command shims. Session start may report a short read-only view/doctor
summary; `afterFileEdit` and `stop` are observation-only and cannot block. Any global
blocking-capable registration must explicitly set `failClosed: false`. User hooks do not run in
cloud agents; only committed project command hooks can provide supported cloud behavior.

The one permitted local job is the serialized interval job `doc-warden-maintenance`. Its generated
contract resolves the source checkout to one canonical absolute root and anchors both the wrapper
and repository argument to that root. Portable command contract:

```text
/bin/bash <resolved-source-root>/_ops/bin/doc-warden.sh doctor fleet --refresh-projections --repo <resolved-source-root>
```

`<resolved-source-root>` is the canonical absolute checkout root resolved by
`maintenance_job_contract()`. Job output uses the closed egress projection. The job may inspect and
refresh generated projections only; it never repairs, applies, authors semantics, commits, pushes,
merges, or calls GitHub.

## Compatibility and activation

Bare compatible commands dispatch to v2. The explicit `legacy-v1` namespace retains the prior
classifier and repair surface during migration; compatibility never silently changes a v2 command
into a v1 mutation. Policy, schema, trigger catalog, templates, runtime binding, and dispatcher
activate and roll back as one reviewed release body.
