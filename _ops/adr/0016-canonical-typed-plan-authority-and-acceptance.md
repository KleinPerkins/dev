---
{"approval":{"actor":"KleinPerkins","date":"2026-11-05","review_sha256":"ae8a44b3e684ed56a4f78884a931087de23773aba52fb62451f1e8c84a93c95c"},"authority":"semantic","github_repository_id":1278387789,"id":"ADR-54aec621-9236-53d2-87b7-9a60ef4ec92e-08c0734b-1e22-516f-8417-76345c0920da","lifecycle":"approved","mutability":"frozen_after_approval","provenance":[],"relations":[],"repository_key":"54aec621-9236-53d2-87b7-9a60ef4ec92e","schema":"doc-warden/artifact/v2","supersedes":null,"type":"adr","version":1}
---
# ADR 0016: Canonical typed plan authority and acceptance

## Context

Accepted ADR0009 §4 and doc-warden execution plan v2 §2.6/§3.3 describe native phase PLAN locations and a native checker for execution-plan acceptance. The delivered typed artifact publisher instead freezes a versioned PLAN and governance sidecar in `.planning/artifacts`; native authoring import remains `draft_update`. This decision prospectively resolves that mismatch. It does not retroactively validate a prior receipt or claim native acceptance or execution qualification.

The unchanged legacy authorities are `_ops/adr/0009-doc-warden-v2-gsd-aligned-governance.md` and `_ops/plans/doc-warden-execution-plan-v2.md`, as recorded at dev main `1fb60d5828368c7b4da53302f86d4b6ed0121da5`. This new canonical ADR carries a prose-scoped amendment to those legacy records. It does not invent a canonical predecessor ID or freeze receipt for them.

## Decision

C1. For new plans intentionally published through doc-warden's typed artifact interface after this amendment is accepted and merged, the immutable PLAN record and version-matched governance sidecar in `.planning/artifacts` jointly hold the semantic authority. The sidecar is complementary metadata, not a second plan. Exact accepted bytes, approval metadata, stable identity, dependency bindings and ordinary successor rules remain mandatory.

C2. Native phase PLAN paths remain the location for native authoring outputs. A draft import is still a draft. If a generated native execution view is later produced under a separately qualified supported workflow, it must reference the exact canonical plan ID/version/digest and must not become an independently editable semantic authority. This amendment neither implements nor qualifies such a generator, native acceptance, autonomous execution, scheduling or the deferred ADR0010 safety layer. It creates no new supported native workflow.

C2a. A typed plan can be accepted only after (a) the existing closed artifact/plan-sidecar schema and plan input validation, including applicable requirement/design/ADR/dependency relations and exact parent bindings, pass; (b) the applicable repository policy and documentation checks pass; (c) a fresh-context independent technical review checks requirement coverage, task/dependency order, explicit preconditions, verifiable acceptance and rollback/consequence gates; and (d) actual owner approval of the exact semantic body plus exact operation-bound apply consent is obtained. These are operational governance gates, not a new security boundary or newly implemented automatic enforcement. For this typed route only, they replace the matrix's native-plan-checker requirement when no native phase PLAN is produced. A native phase PLAN still requires the pinned native checker whenever it is produced/imported, and draft import still cannot freeze acceptance. If any named check is unavailable or fails, acceptance stops; do not assert the native checker ran or infer native execution readiness.

C3. Existing frozen plans, ADRs, sidecars, receipts and event histories remain byte-identical at their current paths. No migration, relabeling, retrospective acceptance, historical qualification or repair of previous receipts is implied. Any future semantic change uses an ordinary governed successor. Existing native/legacy frozen authorities retain their historical identity; the prospective typed-publication rule does not duplicate them.

C4. This amendment narrowly supersedes ADR0009's new-plan location rule and the accepted plan §2.6 layout/§3.3 execution-plan location and native-checker acceptance entries only for the typed publication route described in C1 and C2a. This is a deliberate prospective replacement of that checker gate, not a location-only clarification. All other requirements, native checker obligations for native phase PLAN outputs/imports, exact acceptance gates, in-boundary product limits and repository-owned conventions remain unchanged. A consumer with a conflicting local convention requires its own bounded disposition before using this route.

C5. Source delivery consists of a new dev ADR carrying this scoped legacy amendment and governed index/audit records, plus the minimum policy/README projections needed to point to that accepted location rule. No engine schema, arbitrary path override, import allowlist, runtime writer, installer or live activation change is proposed. If validation shows that source behavior cannot satisfy C1–C4 without a runtime change, stop that dependent implementation and present the exact gap; do not silently expand this amendment.


## Why

The typed route provides a single versioned semantic plan and complementary governance metadata through an existing supported accepted-freeze interface. Native phase files remain honestly classified as drafts or separately qualified generated views. Adding native-path accepted-freeze support is a separate implementation and qualification project. Parallel accepted copies, arbitrary-path overrides and generic transaction workarounds would obscure authority and are rejected.

The named typed checks are an explicit replacement for the native checker on this route, not proof of equivalent native checking. The owner must accept that precise limitation. No automatic runtime enforcement of independent review or new execution-safety guarantee is introduced.

## Consequences and delivery

This amendment takes effect for new typed plan publications only after its canonical acceptance and verified source merge. Existing frozen source bytes, paths and historical outcomes are preserved. Consumer owners retain their local convention decisions; central acceptance alone cannot override a consumer's plan-location rule.

Source delivery uses the supported new approved-ADR creation route, with exact body approval and operation-bound consent, followed by required checks, independent technical review, ready PR and verified merge. Only the minimum policy/README/index/audit projections of this decision are included; no source schema, runtime writer, installer, installed settings or native workflow is changed by this decision. A discovered implementation gap requires a separately scoped decision before such work.

For the controller ADR0054 correction, the controller owner must separately accept its bounded convention exception and checkpoint prerequisite sequencing. Its original timeout implementation remains conditional on full accepted controller publication merging; deployment and live recovery remain separate. Neither this ADR nor a read-only preview grants those authorities.
