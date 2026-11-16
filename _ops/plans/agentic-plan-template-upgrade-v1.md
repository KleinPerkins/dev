# Agentic plan-template upgrade — merge doc-warden governance with writing-plans execution detail

**Version:** v1
**Status:** ACCEPTED — 2026-08-09
**Date:** 2026-08-09
**Owning repository:** `KleinPerkins/dev` (`~/dev`)
**Plan-type:** standard
**Review provenance:** Co-designed from a format evaluation of doc-warden's ADR/plan templates vs the superpowers `writing-plans` skill; drafted via `/prompt-architect` (RISEN) and executed on branch `feat/agentic-plan-template-upgrade`.

**Goal:** Give doc-warden-governed plans an opt-in, structurally-enforced "agentic-execution" Work-item shape so a zero-context implementer subagent can execute each work item from its block alone.
**Architecture:** Keep the Nygard ADR and the plan as separate artifacts. Add a `**Plan-type:** agentic-execution` header marker; when present, doc-warden additionally requires the writing-plans task-block shape (Files + Interfaces + checkbox TDD steps) across `## 5. Work items`. Enforcement is structural/presence-only inside the existing `dwl_classify_plan_file`; plans without the marker are unchanged.
**Tech stack:** POSIX bash (doc-warden engine), Markdown templates, the doc-warden POLICY contract, and the shell regression harness `_ops/checks/doc-warden-verify.sh`.

---

## Global Constraints

- No new artifact type and no new classification status: an agentic plan is still a `Plan`; `NEEDS_AUTHORING` / `DRIFTED` already exist.
- Backward compatible: existing plans (no `Plan-type: agentic-execution` marker) must keep classifying exactly as before.
- Structural-only enforcement: doc-warden never authors or validates the code/tests/prose inside a task block.
- Atomic POLICY + engine change with a policy-version bump (1.1.0 → 1.2.0); preserve dev-doctor's "non-zero exit ONLY on VIOLATION" invariant and the shallow (top-level) scan depth.
- Never edit an ACCEPTED plan/ADR; the frozen `doc-warden-execution-plan-v1.md` and its §19 acceptance-test ledger stay untouched.
- Local-only; no cpp / Affirm scope. Deliver via branch + PR; rollback is `git revert`.

## 1. Purpose

doc-warden governs the *shape and lifecycle* of a plan (immutable once ACCEPTED, indexed, provenance-bound) but says nothing about whether a plan's Work items are executable by an agent. The superpowers `writing-plans` skill is the inverse: strong agent-executable task decomposition (exact files, cross-task interfaces, bite-sized TDD steps) with no governance envelope. This plan merges the two so a single doc-warden-governed plan can be executed end-to-end by a zero-context subagent.

## 2. Scope and non-goals

**In scope:** an opt-in plan-type marker, a per-work-item task-block template, a POLICY §10 rule, a backward-compatible engine check, fixtures/regression tests, and README guidance.

**Non-goals:** touching the ADR (Nygard) template; changing the taxonomy (§2) or the classification ladder (§3); auto-authoring semantic content; any cross-repo / cpp change; making the shape mandatory for existing plans.

## 3. Background and context

- The engine's `dwl_classify_plan_file` checks only the header metadata prefix (`**Status:**` / `**Date:**` / `**Owning repository:**`) plus a placeholder-marker short-circuit; it never parses `## 5. Work items`. Making the task-block shape mandatory for *all* plans would flag the entire existing fleet `DRIFTED` — hence the opt-in marker.
- Worst-status precedence (unchanged): `CONTRADICTORY` > `NEEDS_OPERATOR` > `DRIFTED` > `NEEDS_AUTHORING` > `MISSING` > `CONFORMANT`.
- Fixtures live in `_ops/doc-warden/fixtures/`, asserted by `_ops/checks/doc-warden-verify.sh`; the ledger in `doc-warden-execution-plan-v1.md` §19 is frozen, so new regression assertions land in the durable harness and this plan.

## 4. Approach

Add `**Plan-type:** agentic-execution` as an opt-in header marker in `plan-header.md`. Extend `dwl_classify_plan_file`: once a file is past the placeholder→`NEEDS_AUTHORING` short-circuit, if it carries the marker, require a `**Files:**` block, an `**Interfaces:**` block, and at least one `- [ ]` checkbox step, else `DRIFTED`. Encode the per-item shape in a new `plan-task-block.md` template. Document the rule in POLICY §10 (rule 10) and §12, bump the policy version, and cover all four outcomes (backward-compat CONFORMANT, agentic CONFORMANT, DRIFTED, NEEDS_AUTHORING) with a new fixture plus regression assertions.

## 5. Work items

- **WI-1 — Task-block template.** `_ops/doc-warden/templates/plan-task-block.md`: Files / Interfaces / checkbox TDD steps + an inline no-placeholder rule. DoD: file present; presence asserted by the verify harness.
- **WI-2 — Extend plan-header.** Add `Plan-type`, `Goal`, `Architecture`, `Tech stack`, a `## Global Constraints` section, the agentic-worker sub-skill pointer, and a §5 note requiring the task-block shape. DoD: existing sections and author markers preserved.
- **WI-3 — POLICY §10 rule 10 + §12 + version bump.** Opt-in agentic shape; structural-only; version 1.1.0 → 1.2.0. DoD: §2 / §3 unchanged; §10 lists the rule; §12 reference matches the engine.
- **WI-4 — Engine check.** Backward-compatible opt-in shape check in `dwl_classify_plan_file`; marker + missing-shape → `DRIFTED`. DoD: lib `--self-test` and full harness green; byte-stability holds.
- **WI-5 — Fixtures + regression.** `_ops/doc-warden/fixtures/agentic-plan/` with standard / feature / missing-shape / skeleton plans and assertions for all four outcomes. DoD: four PASS lines + a byte-stability PASS.
- **WI-6 — README conventions + self-review checklist.** Update `templates/docs-plans-README.md`: the plan-type convention + a `writing-plans` pre-acceptance self-review (spec coverage, placeholder scan, type consistency). DoD: the index table is untouched.
- **WI-7 — This plan + index row + dry-run.** Author this doc, add its index row, and confirm `doc-warden repair ~/dev --dry-run` reports a clean/empty plan. DoD: `check ~/dev` is conformant on the new artifacts; PR opened.

## 6. Acceptance criteria

- `bash _ops/checks/doc-warden-verify.sh` prints `doc-warden-verify: OK`, including the four new agentic assertions and the agentic byte-stability check.
- A plan WITHOUT the marker classifies exactly as before (backward-compat PASS).
- A marked plan missing the shape → `DRIFTED`; a marked skeleton still holding author markers → `NEEDS_AUTHORING`; a marked, fully-shaped plan → `CONFORMANT`.
- POLICY version reads 1.2.0; §2 taxonomy and §3 ladder unchanged; the ADR template is unchanged.
- `doc-warden repair ~/dev --dry-run` on the delivered tree is clean (byte-stability invariant).
- Shipped as one branch + PR; the frozen `doc-warden-execution-plan-v1.md` and its §19 ledger are untouched.

## 7. Rollback

Single-PR change; rollback is `git revert` of the merge commit. No data migration, no persisted state, no cross-repo effects. Reverting restores POLICY 1.1.0 behavior; opt-in plans simply lose the extra shape check.
