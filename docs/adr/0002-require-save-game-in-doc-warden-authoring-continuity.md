---
{"approval":{"actor":"KleinPerkins","date":"2026-11-20","review_sha256":"3fa1db1c164ee67b561b0f421926405be8e8c28070de25b619f00d2ebf61462a"},"authority":"semantic","github_repository_id":1459458379,"id":"ADR-47f7e608-ce5f-50ae-be86-10d7e95265f9-732a4dbf-05ee-52fa-84ac-77421e3a4d03","lifecycle":"approved","mutability":"frozen_after_approval","provenance":[],"relations":[],"repository_key":"47f7e608-ce5f-50ae-be86-10d7e95265f9","schema":"doc-warden/artifact/v2","supersedes":null,"type":"adr","version":1}
---
# ADR 0002: Require Save-Game in Doc-Warden authoring continuity

## Context

The accepted predecessor Doc-Warden v2 scope remains the repository-local governance product defined in `_ops/adr/0009-doc-warden-v2-gsd-aligned-governance.md` and `_ops/plans/doc-warden-execution-plan-v2.md`. Autonomous implementation and security-grade execution enforcement remain deferred under predecessor ADR0010.

The owner has selected mandatory Save-Game integration for current Doc-Warden v2 authoring continuity. Predecessor ADR0009 section 9 and plan section 3.12 described optional integration and safe degradation. Current source also implements an optional adapter. Those frozen historical records and implementation facts must remain distinguishable from this prospective requirement.

## Decision

1. New Doc-Warden v2 requirements and continuation plans bind to current `KleinPerkins/dev`, GitHub repository ID `1459458379`, repository key `47f7e608-ce5f-50ae-be86-10d7e95265f9`. Historical records retain their original identities, bytes and evidentiary limits.
2. Save-Game integration is required for governed authoring checkpoint, handoff, pause-with-continuity and resume flows. A checkpoint-producing flow uses Save-Game's supported save/index contract; resume uses its read-only reconciliation contract and rechecks live canonical authorities. The implementation must define and test precisely which authoring events require a checkpoint. This document does not authorize unsolicited capture, compaction or checkpointing of unrelated activity.
3. Such a flow cannot report successful durable continuity when the capability is absent, unadopted where adoption is required, failed, malformed, stale or associated with the wrong repository/workstream. It reports the specific incomplete or blocked operation and preserves the prior valid state. There is no silent optional fallback that completes the same continuity operation without Save-Game. Independent read-only views and ordinary drafting remain available.
4. Save-Game remains independently owned and private. Doc-Warden stores only its closed pointer projection and permitted authority references, never checkpoint payloads, transcripts, prompts, source, diffs, logs, secrets or customer data. Live repository policy, accepted artifacts and observed Git state outrank checkpoint assertions on resume. Unknowns and conflicts require explicit resolution before dependent continuation.
5. This prospectively replaces only the optionality and successful-degradation clauses for the continuity flows above in predecessor ADR0009 section 9, plan section 3.12 and the corresponding retained Save-Game acceptance requirements. It preserves the capability ownership, privacy, pointer-schema, frozen-history and authoring-only boundaries. Other retained v2 product requirements remain unchanged. No canonical predecessor ID or retrospective acceptance receipt is invented.
6. Current source delivery uses the repository-owned CI, independent originating-account review and App-controlled ordinary delivery procedure. Retired-controller receipts and predecessor runnerless/draft-only rules are historical provenance. Doc-Warden itself does not own source delivery, merge, installation or product release.

## Consequences and verification

The first unit prepares current PRD and continuation-plan authority. Subsequent source work must assess the existing optional adapter against the required integration, identify the smallest exact implementation gap and satisfy current implementation authority before changing code. A requirements decision is not an assertion that required integration already works.

Acceptance must cover successful checkpoint/index and read-only reconciliation, absent capability, required adoption, failed invocation, invalid pointer or digest, wrong identity, stale/conflicting live state, interrupted/repeated requests, preservation of the last valid checkpoint, and a privacy-negative fixture. Source fixtures, installed CLI qualification and actual client discovery/invocation are separate evidence. No previously unverified Codex client behavior is deemed qualified by this ADR.

Save-Game's own missing forward-rollback or schema-downgrade operations are not promised or introduced here. Installation, adoption, client qualification, scheduled jobs, runtime changes and real private checkpoint writes retain their respective owner scope and operation gates.

The current typed PLAN and matching governance sidecar use the existing prospective route adopted by `_ops/doc-warden/POLICY.md` from predecessor ADR0016 C1-C4, including C2a. Actual parent authority, exact-body owner acceptance, independent review, validation and exact operation consent remain prerequisites. Acceptance alone does not populate the successor's intentionally unbound central authoring-plan binding or enable native GSD execution.
