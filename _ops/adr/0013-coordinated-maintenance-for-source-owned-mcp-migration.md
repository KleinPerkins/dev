---
{"approval":{"actor":"KleinPerkins","date":"2026-11-01","review_sha256":"17292fd79f79e8a8efc8f7b5a3e3955163f4e440760f79e2d85896f7ceb2b4f8"},"authority":"semantic","github_repository_id":1278387789,"id":"ADR-54aec621-9236-53d2-87b7-9a60ef4ec92e-06cdd37a-84b0-5cde-af3b-d9092d5d33da","lifecycle":"approved","mutability":"frozen_after_approval","provenance":[],"relations":[],"repository_key":"54aec621-9236-53d2-87b7-9a60ef4ec92e","schema":"doc-warden/artifact/v2","supersedes":"ADR-54aec621-9236-53d2-87b7-9a60ef4ec92e-9cbb9f0e-b89b-5d64-8168-d26ded302e6b","type":"adr","version":1}
---
# Proposed dev amendment: coordinated maintenance for source-owned MCP migration

Status: proposed integration amendment; not accepted, applied or implementation authority. Owner: KleinPerkins/dev. Prepared 2026-11-01.

## Scope and existing authority

This narrowly amends ADR0012's integration adoption of the accepted interoperability SPEC and PLAN for INT-013/014, and only for explicitly selected file-backed MCP operations using the accepted coordinated-maintenance mode. It incorporates all other normative requirements of ADR0012 and the accepted PRD/SPEC/PLAN at dev revision 14fa5f95fe86178f32e966cb747ab9c884f4b92b unchanged. Those original semantic records, their appendices and governance sidecar remain frozen. This amendment is not a replacement requirements project or a mutable-ledger waiver.

Canonical component authority is KleinPerkins/kp-mcp ADR0002, delivered by PR94 at afce7c7a50e9cae7ccbb915adf3503556c0fa8f8. Its canonical file SHA-256 is fbfe1bb4f64029fdcf27c734cbbd900d34a0df065f0aaa90d3bce5561bb1ff5a; unchanged approved body SHA-256 is bb0c2417ae274b5f60717939f9286b8c7acd3d5ff712394d80a8b920e833a7c8. Its canonical approved metadata and acceptance receipt govern despite retained historical draft wording in the body. The owner retains its exact maintenance schemas, lifecycle, admission, durable replay and field-ownership contracts; this amendment references rather than duplicates them.

The human accepted the narrower maintenance risk and subsequently accepted the execution-plan body SHA-256 87429022048f3b291ca4f0385e9d312efade3236a17a577d717e86fe4e64e9f9, with conditional D1/D2 synthetic implementation authority after this matching dev amendment is accepted and merged. The plan's canonical acceptance/publication remains a separate governed operation. This proposed amendment grants neither gate prematurely.

## Exact integration qualification

Strict native exclusion remains the default. No implementation may downgrade automatically, treat fixture isolation as live authority, or relabel coordination as provider-enforced exclusion.

For an explicitly opted-in and qualified coordinated-maintenance operation only, the accepted PLAN's Phase-3 statement “no competing writer remains for an adopted entry” means that the known designated source writers have completed the verified handoff and are not concurrently active during that operation. Successful adoption keeps the legacy writers suspended for that target. It does not assert that an unknown or noncooperating writer cannot exist or interleave.

For this same bounded mode, the SPEC's reconciliation transaction rule to refuse overwriting divergent targets applies to divergence observed by exact preimage/postimage and current-state checks. An unexpected write between the last check and replacement may be overwritten; a later write may invalidate the result. This is the explicitly accepted residual lost-update risk, not a guarantee of detecting every concurrent change. Observed divergence, known active or uncoordinatable writers, stale evidence, unsupported host conditions or unresolved recovery still refuse new writes.

The SPEC's safety/acceptance reference to writer exclusion is qualified only for these selected maintenance operations: verify the exact accepted coordination claim and report its residual limitation. Native exclusion, workspace writer isolation, other adapters and all unrelated hard gates retain their original meaning. No performance result compensates for failing the applicable claim. Record strict and coordinated evidence separately; do not convert historical unsupported observations into passes or rewrite frozen workload inputs/rubrics. Add focused maintenance cases as separately versioned evidence bound to this amendment and the component ADR.

## Owner implementation boundary

The accepted owner execution plan supplies D0-D5 sequencing. D1/D2 can begin only after its canonical acceptance and this amendment's accepted source delivery, under the human's bounded implementation authorization.

- kp-mcp owns changes to its existing registrar contracts, admission and durable replay paths, runtime validator binding, public exports and necessary consumer plumbing. Preserve strict defaults, existing v1 semantics, exact prepared operations, approval audiences and rejection of mixed fixture/live modes. No competing registrar or new connection catalog.
- dev owns the existing migration coordinator plus the bounded maintenance validator/lifecycle helper and guarded legacy entrypoints. Bootstrap step-4 refusal must prevent step 5 and later writers; direct Make/script and lifecycle registration, deletion, rollback and uninstall paths must respect the same target guard. Do not install these changes as part of synthetic source delivery. Package/release pins and consumer qualification remain explicit gates.
- Source ownership, native host/user policy, unknown fields, local opt-outs, native auth references and app-owned connectors retain their existing owners. Equal bytes do not establish adoption authority. No Cursor-installed configuration becomes another client's source definition.
- Server-guard stays an independent recovery owner using its existing supported workflow. No server-guard implementation, private reconciliation API, unconditional set-golden, discovery dependency or baseline mutation is authorized by D1/D2. Configuration, registrar state and baseline handoff are separate outcomes, not an atomic cross-owner transaction.

## Native operation, recovery and retirement gates

D3 remains a separately previewed and approved operation on one eligible client/identity with qualified installed revisions and current host evidence. Prove bounded pause/drain consequences, exact source/target/state bindings, fresh maintenance evidence and lifecycle, whole-payload non-secret storage eligibility, rollback and cleanup. Receipt-only adoption is preferred but still mutates registrar state and does not bypass those gates. A candidate identity is not an authorization to inspect or operate it. No service call, auth action or app-server discovery is part of the canary.

The accepted component contract governs every mutation and restart/recovery path. Expiry, resumed known writers or changed bindings stop new writes. Preserve unresolved journals; no automatic rearm. Exact rollback requires current full-file and ownership postimages still to match. Later unrelated edits block exact rollback; a separately approved field-preserving inverse must be labeled as such. Successful source delivery or package rollback does not establish registration or baseline rollback.

D4 global mirror retirement requires coverage of every legacy effect/client, direct and automatic/force invocation, and clean/new-host provisioning path. Each row needs verified replacement/readback/recovery evidence or an explicit accepted nonreplacement disposition. A one-entry canary permits only its scoped handoff; unknown coverage leaves global retirement open. D5/INT-015 and INT-020/021 retain separate registration, enablement, authentication, discovery, bounded-read and broader-rollout observations and gates.

## Preserved boundaries and validation

No secret-bearing config copy, auth-scope change, service-write smoke test, raw transcript/work-data persistence or memory update. The INT-008 KEEP_NO_COPY_UNQUALIFIED disposition remains unchanged. Every persisted byte needs applicable storage authority; a safe selected entry does not classify a credential-bearing sibling file.

Chaos-scheduler remains entirely excluded, including indirect runtime effects, and mcp-builder remains outside scope. Refuse an unbounded host shutdown or client-wide pause that could affect excluded runtimes; do not inspect excluded runtimes to satisfy this gate. AWA ownership, ADR0026 NO-GO, native attachment versus protection/Close, expired bootstrap exceptions, protected automation and orchestrator-owned downstream delivery are unchanged.

Before source delivery: independent technical review, applicable current owner checks, normal ready PR delivery and exact merged-tree/check verification. Maintenance validation adds synthetic ownership-preservation, version/mode separation, fresh-process durable replay, lifecycle/recovery, bootstrap refusal, baseline conflict, excluded-effect and whole-file no-copy cases specified by the accepted owner plan. Deliberately exercise a noncooperating race to demonstrate the accepted limitation, never to claim exclusion. Native qualification is subsequent evidence, not an inference from synthetic tests.

This amendment becomes authoritative only through governed owner acceptance and verified source merge. Normal authorized implementation includes technical review and PR-to-merge ownership without another operator code-review gate. Live installation, migration, retirement and broader rollout remain separately authorized consequences.
