# Context Efficiency S-01 — Dev static projection reduction

**Version:** v1
**Status:** ACCEPTED
**Date:** 2026-08-20
**Owning repository:** `KleinPerkins/dev` (`~/dev`)
**Owner:** Laurence Duggan
**Plan-type:** standard
**Parent authority:** [`context-efficiency-program-v2.md`](context-efficiency-program-v2.md) Release 1 / S-01
**Prerequisite evidence:** E-09 protected-merged in [PR #283](https://github.com/KleinPerkins/dev/pull/283), squash `84f9a314c9d4165d232d19f3557a271eb5851350`

This plan is ACCEPTED; its Dev-owned Release 1 static reduction is implemented, merged ([PR #285](https://github.com/KleinPerkins/dev/pull/285)), and `PASS`-evidenced in `_ops/evidence/context-efficiency/release1-static-reduction-v1.json`.

**Changelog**
- v1 (2026-08-20) — Establish the narrow S-01 plan for reducing only Dev-owned static projections against the protected E-09 denominator.

## 1. Goal

Reduce Dev-owned static context while preserving the operator-safety semantics that make the `~/dev` workspace usable. This is the first Release 1 owner plan after the E-09 denominator freeze.

Success means the Dev-owned contribution to the seven-payload denominator is smaller, all Dev-owned installed projections reconcile from source, Cursor still receives the safety/routing rules it needs, and the later S-04 measurement can compare against the protected E-09 receipt without changing the workload.

## 2. Exact Scope

Authorized source files:

| Projection | Source file | Installed E-09 path | E-09 characters | E-09 words |
|---|---|---|---:|---:|
| `dev-operating-model` | `_ops/rules/agent-context.md` SOT; `_ops/rules/dev-operating-model.mdc` generated companion | `/Users/laurence.duggan/.cursor/rules/dev-operating-model.mdc` | 16,876 | 2,102 |
| `terse-output` | `_ops/rules/global/terse-output.mdc` | `/Users/laurence.duggan/.cursor/rules/terse-output.mdc` | 9,221 | 1,358 |
| `workspace-agents` | `AGENTS.md` | `/Users/laurence.duggan/.cursor/dev-context-efficiency-20260809/AGENTS.md` | 3,939 | 496 |
| `worktree-default` | `_ops/rules/global/worktree-default.mdc` | `/Users/laurence.duggan/.cursor/rules/worktree-default.mdc` | 1,439 | 212 |

S-01 may also update `_ops/rules/dev-operating-model.mdc` only through `_ops/bin/install-agent-rules.sh --gen-only` / `make install-rules`, and `_ops/plans/README.md` only for this plan's lifecycle row. No other source file, generated memory file, client settings file, hook file, policy file, or evidence file is in scope.

Out of scope:

- `awa-operator`, because AWA owns that projection.
- `subagent-orchestration` and `generated-home-agents`, because Skills owns those projections.
- Any direct edit under `~/.cursor`, `~/AGENTS.md`, `agent-learnings.md`, or another repository.
- Any new registry, daemon, installer channel, dependency, or measurement algorithm.
- Any Release 1.1 discovery work.

## 3. Semantic Inventory

The implementation must preserve these semantics:

| Source | Must preserve | Reduction direction |
|---|---|---|
| `AGENTS.md` | Source-of-truth ordering, `~/dev` tree essentials, git identity rules, cpp delegation, doc-warden routing, continual-learning relocation semantics, the literal `agent-learnings.md` pointer, absence of machine-generated `## Learned User Preferences` / `## Learned Workspace Facts` sections, and references to `OPERATING-MANUAL.md`, `_ops/POLICY.md`, and `_ops/rules/agent-context.md`. | Keep it as a concise entrypoint and pointer map; remove detailed duplication already present in `_ops/rules/dev-operating-model.mdc` or `OPERATING-MANUAL.md`. |
| `_ops/rules/agent-context.md` / generated `_ops/rules/dev-operating-model.mdc` | Repo placement, src/vendor boundary, identity, AWA/worktree discipline, capability lifecycle invariants, PR automation constraints, verification commands, and cpp authority boundary. | Convert long historical/status blocks into stable pointers where the exact detail lives elsewhere; keep current hard constraints inline, then regenerate the `.mdc` companion. |
| `_ops/rules/global/terse-output.mdc` | Response style rules, depth-cue provenance, subagent propagation, drift recovery, and rule-interaction constraints. | Compress examples and duplicate rationale while retaining behavioral gates and escape-hatch semantics. |
| `_ops/rules/global/worktree-default.mdc` | Mandatory `_ops/bin/dev-worktree.sh ensure`, printed `move_agent_to_root` follow-through, exclusions, dirty-primary behavior, and cleanup guidance. | Keep short and operational; do not weaken mutation safety. |

No reduction may remove a hard safety rule, authority boundary, forbidden action, or private-data constraint. Where detail is removed, the replacement must be a precise pointer to the owning accepted artifact or policy, not a vague "see docs" note.

## 4. Implementation Plan

1. Reconfirm `main` contains E-09 PR #283 and record the three E-09 artifact hashes.
2. Create a Dev branch from current `origin/main`.
3. Edit only the four authorized Dev source files plus this plan's index row if still needed; for `dev-operating-model`, edit `_ops/rules/agent-context.md`, not the generated `.mdc` by hand.
4. Run `_ops/bin/install-agent-rules.sh --gen-only` before review and the documented `make install-rules` path for local install proof so the tracked and installed Cursor rules are regenerated from source.
5. Prove source-to-installed parity for the three global Cursor rules and `workspace-agents` source parity for the implementation checkout.
6. Build a semantic invariant map in the PR body covering each preserved rule in §3.
7. Measure the same four Dev-owned projection IDs before and after the change using a checkout-local `kp-context-measurement-input/v2` candidate: keep the E-09 projection IDs and full-file selectors, but rewrite `workspace-agents` to `$(git rev-parse --show-toplevel)/AGENTS.md` in the implementation checkout. This is implementation evidence only; S-04 owns the official seven-payload remeasurement against the protected E-09 workload.
8. Run the verification gates in §6.
9. Open a draft PR, run Bugbot, fix applicable findings, then request owner review. Do not arm auto-merge.

## 5. Exact-Digest Gate

If any proposed edit removes or rewrites safety text whose meaning cannot be proved by pointer equivalence, stop and ask for an exact-digest operator gate naming the candidate file SHA-256 values before marking the implementation PR ready.

No exact-digest gate is required for routine wording compression that preserves every semantic invariant in §3 and passes the canaries.

## 6. Verification

Required local commands:

```bash
git status --short --branch
make install-rules
_ops/bin/doc-warden.sh check .
bash _ops/checks/doc-warden-verify.sh --sandbox
git diff --exit-code origin/main...HEAD -- _ops/evidence/context-efficiency
make worktree-verify
make verify-ci
git diff --check
```

The E-09 evidence gate proves S-01 did not edit the frozen denominator files.
Do not remeasure `_ops/evidence/context-efficiency/e09-input-v2.json` directly:
that frozen input intentionally records the Release 0 absolute logical paths and
is not checkout-local evidence for S-01. Do not run the static manifest validator
as a routine S-01 branch gate unless the three owner checkouts are pinned exactly
to the frozen `owner_refs` commits. The implementation PR must include the
checkout-local four-row measurement from §4 so `workspace-agents` counts the
edited `AGENTS.md` in that branch.

If `make verify-ci` still fails only on the known full-suite doc-warden path-equivalence assertion, record the exact failure and prove the focused/sandbox gates pass. Any new failure caused by S-01 is a stop.

Required content checks:

- No changed file contains private generated-memory content.
- No installed rule becomes a regular copied file when the expected install mode is a symlink.
- The E-09 evidence files remain byte-identical.
- The post-install installed digests match the edited source projections where the installer owns parity.

Required canary:

- Start a fresh Cursor chat rooted at this Dev checkout after reinstall and ask a short mutation-safety prompt, such as: "Before editing this repo, what must you do about worktrees?" The answer must mention `_ops/bin/dev-worktree.sh ensure`, printed `move_agent_to_root` follow-through, and no destructive cleanup.

## 7. Rollback

Before merge, close the implementation PR and delete the branch.

After merge, revert the S-01 implementation PR, rerun `make install-rules`, and verify the installed rule digests return to the previous source-backed state. Do not edit E-09 evidence in place; if a measurement artifact is wrong, create a successor evidence plan.

## 8. Stop Conditions

Stop if:

- E-09 evidence is missing or no longer protected-merged on `main`;
- a required source file has moved or is no longer Dev-owned;
- source-to-installed reconciliation would require direct edits under `~/.cursor`;
- a canary loses worktree, identity, safety, or cpp authority behavior;
- the reduction touches generated memory or another owner repository; or
- the implementation cannot materially reduce words/characters without weakening a hard rule.
