# Plans

This directory contains multi-session plans for `dev`.

**Governance:** `~/dev/_ops/doc-warden/POLICY.md` §2 (taxonomy), §9 (archival).
Plans are **byte-identical-forever** once their Status line reads `ACCEPTED` — no in-place edits
after approval. A revision is a new `{{slug}}-v2.md` with a `Supersedes:` pointer; the prior
version is never modified.

## Successor provenance

Retained accepted plans preserve predecessor bytes and historical decisions. They
do not supply new-ID runtime qualification or restart authority. The master
migration freeze and explicit WIP restart gates take precedence; paused Doc-Warden,
PAC, AWA, Intent-Router and Scheduler work remains paused. Work-specific proposals
are privately preserved outside operating-model source. See
[successor adoption](../../docs/runbooks/dev-successor-adoption.md).

## Index

| Plan | Status | Date | Notes |
|---|---|---|---|
| [`doc-warden-execution-plan-v1.md`](doc-warden-execution-plan-v1.md) | ACCEPTED | 2026-08-05 | Active v1 compatibility plan; frozen and byte-identical forever. Its mutable index row changes to `SUPERSEDED` only after plan v2 M6 proves v1 writer retirement. |
| [`doc-warden-execution-plan-v2.md`](doc-warden-execution-plan-v2.md) | ACCEPTED | 2026-08-28 | **doc-warden v2 in-boundary governance.** Successor implementation plan scoped to the reviewer-cleared governance layer: typed artifact schema, referential integrity/code anchors, deterministic dynamic rigor, canonical nontechnical PRD, migration and new-repo instantiation, NLP-first operator verbs, and Save-Game **for authoring**. It does not supersede active v1 compatibility at §0; M6 owns that index transition after retirement proof. The net-new **agentic-execution safety layer** (autonomous GSD execution + hard-enforcement guarantees) is **removed and deferred** to [ADR 0010](../adr/0010-agentic-execution-safety-layer-deferred.md) + [`agentic-execution-safety-layer-deferred-v1.md`](agentic-execution-safety-layer-deferred-v1.md); see plan §1.5 for the exact deferred-scope map. Governed by accepted ADR 0009; implementation GO is granted. |
| [`manifest-driven-verification-target-design-v1.md`](manifest-driven-verification-target-design-v1.md) | ACCEPTED | 2026-09-02 | Normative minimal v1 wire appendix: sole InputRule ownership, strict additive JSON Pointer semantics with frozen limits, exact linked shadow/full receipts, three schemas/one hash chain, and fixed ISO-week/calendar-month runnerless periods with 24/48-hour fail-closed grace. Checkpoint 0 (2026-09-02) accepted D2–D5 and authorized the three-artifact acceptance merge; its commit freezes the design/plan/ADR (the two index files stay mutable projections) before M0 genesis mirroring. Only the contingent M0-T01 bootstrap is authorized. |
| [`manifest-driven-verification-execution-v1.md`](manifest-driven-verification-execution-v1.md) | ACCEPTED | 2026-09-02 | Agentic-execution plan sequenced M0 authority/wire bootstrap → M1 exact local shadow/full linkage → M2 selector proof → M3 exactly-once/AWA/remote invalidation plus live non-sliding surveillance → M4 lane-specific reversible focus → M5 steady-state hardening. Checkpoint 0 (2026-09-02) accepted the plan and authorized only the documentation acceptance merge and contingent M0 bootstrap; the first permitted skip is Checkpoint 4/M4. |
| [`agentic-execution-safety-layer-deferred-v1.md`](agentic-execution-safety-layer-deferred-v1.md) | DRAFT | 2026-08-26 | **NOT FOR IMPLEMENTATION** — scope-capture stub for the deferred **agentic-execution safety layer** split out of plan v2. Governed by [ADR 0010](../adr/0010-agentic-execution-safety-layer-deferred.md); records the initiative's end-state scope and high-level milestones (D0–D5) only. No operator acceptance, no implementation GO, no work authorized. |
| [`agent-worktree-automation-end-state-v3.md`](agent-worktree-automation-end-state-v3.md) | DRAFT | 2026-07-03 | AWA end-state architecture (v2.1 content; v1/v2 in `archive/`) |
| [`local-ci-migration-v2.md`](local-ci-migration-v2.md) | DRAFT | 2026-07-26 | CI cost control + local test signal |
| [`operator-voice-toolkit-build-plan-v4.md`](operator-voice-toolkit-build-plan-v4.md) | SUPERSEDED | 2026-07-30 | Historical Operator Voice Toolkit build plan, kept byte-identical; superseded by [`operator-voice-toolkit-build-plan-v5.md`](operator-voice-toolkit-build-plan-v5.md) |
| [`operator-voice-toolkit-build-plan-v5.md`](operator-voice-toolkit-build-plan-v5.md) | ACCEPTED | 2026-10-23 | Active Operator Voice Toolkit build plan: v4's roadmap with the amendments from operator-voice plan v2 §9 and ADRs 0004–0006 (channel-type voices, whole-bundle token budget); supersedes v4 without modifying it |
| [`operator-voice-toolkit-forensic-audit-v1.md`](operator-voice-toolkit-forensic-audit-v1.md) | DRAFT | 2026-07-30 | OVT forensic static audit (companion to build plan) |
| [`agentic-plan-template-upgrade-v1.md`](agentic-plan-template-upgrade-v1.md) | ACCEPTED | 2026-08-09 | Hybrid doc-warden + writing-plans agentic plan template (POLICY 1.2.0) |
| [`context-efficiency-program-v1.md`](context-efficiency-program-v1.md) | SUPERSEDED | 2026-08-16 | Immutable historical program; superseded by [`context-efficiency-program-v2.md`](context-efficiency-program-v2.md) |
| [`kp-context-measurement-v1-tooling-v1.md`](kp-context-measurement-v1-tooling-v1.md) | ACCEPTED | 2026-08-16 | Immutable historical implementation plan; its v1 wire contract is superseded by ADR 0005 and is unsafe for E-09 — use active Program v2 |
| [`context-efficiency-program-v2.md`](context-efficiency-program-v2.md) | ACCEPTED | 2026-08-16 | Active authority: corrected measurement, durable Release 0 evidence, E-01–E-09, and preserved Releases 1, 1.1, and 2; supersedes v1 without mutating it |
| [`context-efficiency-s01-dev-static-reduction-v1.md`](context-efficiency-s01-dev-static-reduction-v1.md) | ACCEPTED | 2026-08-20 | Release 1 S-01 plan for reducing only Dev-owned static projections after protected E-09 (implemented; PR #285, `release1-static-reduction-v1.json` PASS) |
| [`context-efficiency-d01-capability-discovery-inventory-v1.md`](context-efficiency-d01-capability-discovery-inventory-v1.md) | ACCEPTED | 2026-08-20 | Release 1.1 D-01 plan for inventorying actual installed and client-discovered capability catalogs (implemented; PR #289, `capability-discovery-inventory-v1.json` PASS) |
| [`context-efficiency-e06-dev-host-overlay-v1.md`](context-efficiency-e06-dev-host-overlay-v1.md) | SUPERSEDED | 2026-08-18 | Immutable historical E-06 host-overlay plan; superseded by [`context-efficiency-e06-dev-host-overlay-v2.md`](context-efficiency-e06-dev-host-overlay-v2.md) after the root-bootstrap call-path contradiction was proven |
| [`context-efficiency-e06-dev-host-overlay-v2.md`](context-efficiency-e06-dev-host-overlay-v2.md) | SUPERSEDED | 2026-08-18 | Immutable historical E-06 bootstrap-correction plan; superseded by [`context-efficiency-e06-dev-host-overlay-v3.md`](context-efficiency-e06-dev-host-overlay-v3.md) after the clean-room interruption window was proven |
| [`context-efficiency-e06-dev-host-overlay-v3.md`](context-efficiency-e06-dev-host-overlay-v3.md) | ACCEPTED | 2026-08-18 | Active E-06 authority: resolve AWA runtime/host state at an immediate bootstrap transaction barrier; fresh v3 implementation GO and separate real-machine GO remain required |
| [`context-efficiency-release2-closure-v1.md`](context-efficiency-release2-closure-v1.md) | ACCEPTED | 2026-08-23 | Release 2 closure plan: fresh-client projection matrix (C-01), versioned final evidence + built-vs-planned record (C-02), per-owner documentation closure (C-03) |

## Conventions

- Filename: `<slug>-vN.md` where `N` starts at `1`
- Status values: `DRAFT` → `ACCEPTED` → `SUPERSEDED` (tracked in the index row, NOT in the plan file itself after acceptance)
- A new version (`-v2`, `-v3`, …) is created when a material revision is needed post-acceptance; the prior version is immutable
- Draft plans may be edited in place before acceptance; accepted plans may not

## Archive

Superseded and retired plans that are no longer active but preserved for history live in
`docs/archive/plans/` (moved via `git mv`, not deleted).
