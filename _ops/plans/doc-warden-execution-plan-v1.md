# `doc-warden` — Uniform Repository-Documentation Governance — Execution & Design Plan

**Version:** v1
**Status:** ACCEPTED — 2026-08-05. Operator-approved as the execution plan for `doc-warden` (Gate 4 — see §26). Per §13's archival rule, this text is now frozen byte-identical-forever; any future revision is a new `-v2` document with an explicit `Supersedes:` pointer, never an edit to this file.
**Date:** 2026-08-05
**Owning repository:** `KleinPerkins/dev` (`~/dev`)
**Review provenance:** Co-designed with operator across Gates 0–2 (owner/name/POC selection, architecture, reconciliation doctrine); reconciled against a bounded `/swarm` review (1 probe + 3 reviewers, evidence-grounded, several findings independently reproduced by 2–3 sources) before this Gate 3 publication approval. The pre-publication architecture/policy drafting (§1–§16) occurred in a part of the session that was subsequently compacted; §1–§16 were reconstructed from the swarm dispatch transcripts (which quoted most of that material as review evidence) plus fresh verification against live repository state, and §17–§19 (POC full specs, the M1 work-item ledger, the acceptance-test ledger) were authored directly against this plan's own requirements and the reconciled architecture, since no transcript fragment captured their original full text. No section content is invented beyond what the approved architecture (Gates 0–2) and the 14 reconciled swarm findings determine.

---

## 1. Purpose

Establish one uniform documentation-governance capability — canonical policy, one normalization/repair path, deterministic new-repo inheritance, deterministic growth triggers, safe unknown-case escalation, additive+subtractive reconciliation, provenance-driven reconstruction — across the local KleinPerkins development fleet, so documentation quality stops depending on which session or agent touched a repo last.

## 2. Scope and non-goals

**In scope:** local KleinPerkins-owned repos eligible per `repo-baseline.sh list`, **plus `~/dev` itself** (doc-warden's eligibility set is `repo-baseline`'s eligible set plus the umbrella repo — see §5); one canonical policy source; one engine (`check`/`repair`); deterministic trigger catalog; `NEEDS_OPERATOR` escalation; additive/subtractive reconciliation with strict plan/ADR immutability; provenance-driven reconstruction; gated, canary-paced fleet rollout.

**Non-goals (explicit):** no cpp delivery of any kind (no WF2 `cpp-sync`, no quiver payload, no control-plane change — structural, per ADR-3); no new fleet-inventory mechanism (reuses `repo-baseline.sh list`); no GitHub-settings mutation (stays `repo-baseline enforce`'s job); no autonomous fleet-wide mutation; no plugin framework, shared runtime, or generic reconciliation service (per ADR-2); no semantic-prose auto-rewriting; no capability-lifecycle enrollment (not a WF1/WF2 shelf, per ADR-1).

## 3. Verified precedent and live-state inventory

| Fact | Verified via |
|---|---|
| `repo-baseline.sh` already separates `list`/`verify`/`apply`/`enforce`, plus an explicit `profile pr-automation v3` sub-lifecycle | `_ops/bin/repo-baseline.sh` verb dispatch (L84–590) |
| `baseline-lib.sh` is shared by `repo-baseline` and `dev-doctor` | `_ops/checks/dev-doctor.sh` imports; `_ops/baseline/README.md` |
| `dev-new-repo.sh` already calls `repo-baseline.sh apply` then (greenfield-only) `enforce`, then optionally `reconcile-merge-safety` | `_ops/bin/dev-new-repo.sh` L96, L102, L125, L218, L235 |
| Baseline's own documented extension path is "fold a new payload into `baseline-lib.sh`" | `_ops/baseline/README.md` §"Extending the floor (v3+)" |
| `pr-automation-controller` has the fleet's clearest versioned-plan + Nygard-ADR convention | `personal/pr-automation-controller/docs/{plans,adr}/README.md` |
| That convention has a live, real drift: `docs/plans/README.md` L56 claims `docs/adr/` "has the same gap — no index/README of its own yet," but `docs/adr/README.md` exists with a populated index | Direct read of both files |
| `server-guard` has zero `docs/` (local and remote), 14 commits, all CI/infra plumbing, mixed sh/Swift/Python implementation | `git log`, `git ls-remote`, GitHub tree check |
| cpp has no ADR/plans convention (closest analogue: one 97KB monolithic evolving `_ops/cpp-operating-model-SOT.md`), but does run a deterministic integrity engine (Python; C0–C6 checks; `OK<ADVISORY<DRIFT<NEEDS_HUMAN<VIOLATION`; one artifact in `--local`/`--ci`/`--report` modes) | subagent research task |
| `personal/ecosystem-orchestrator` has the thinnest in-repo docs (4 files, no `AGENTS.md`, no ADR/plans) of the fleet's heavily-integrated repos, against 45 files/124 references depending on it | Same research task |
| `~/dev/_ops/` has no `adr/` directory and `_ops/plans/` has no index/README today | Direct `ls` |
| `_ops/POLICY.md` §6b shows the exact precedent for a subsystem pointer (brief, SOT-deferring) | Direct read |
| `dev-doctor.sh` did not return in a live 10-minute run (background job aborted, unknown exit) | Live run, this session |
| AWA is NOT cpp-sync-enrolled (`ecosystem-orchestrator/config/registry.yml` shows it `excluded`) | Direct read, prior session |

## 4. Real gap statement

No canonical documentation-structure policy exists anywhere in the fleet. Four independently-observed, mutually inconsistent conventions currently coexist with no arbitration: `~/dev`'s own flat unindexed `_ops/plans/` (no ADR dir at all); `pr-automation-controller`'s formal versioned/Nygard convention (itself internally stale in one place); `chaos-labs`'s flat `docs/INDEX.md` + ALL-CAPS topic-spec convention (no plans/adr split); and `server-guard`'s complete absence of any `docs/`. Separately, `ecosystem-orchestrator` demonstrates a different failure mode: real documentation exists but is disproportionately thin relative to how much of the ecosystem depends on it.

## 5. Fleet boundary and exclusions

Eligible fleet = `repo-baseline.sh list`'s existing output (23 eligible repos) **plus `~/dev` itself**. `repo-baseline.sh` hard-excludes `~/dev` as the "umbrella repo" (`bl_classify_repo`'s `rel=="."` branch, `_ops/bin/baseline-lib.sh`) because baseline's job is to govern *other* repos, not itself (`_ops/POLICY.md` §6) — but documentation hygiene is exactly what doc-warden governs, and `~/dev`'s own `_ops/plans`/`_ops/adr` (this very plan's home) are direct artifacts of doc-warden itself. Doc-warden's eligibility set is therefore explicitly `repo-baseline`'s eligible set **plus `~/dev` itself** — no new inventory mechanism beyond that one addition; see §14 for how `dev-doctor.sh`'s doc-warden loop reflects this without disturbing its separate, unchanged baseline loop. `repo-baseline`'s other hard exclusions are carried over unchanged: `chaos-scheduler` (permanent no-touch), `affirm/*` (work/vendor), separately-governed cpp, any dirty or non-`main` working tree, any foreign hook/governance framework. cpp is read-only comparison input only for this plan (informed §3, ADR-2) — never a mutation or delivery target (ADR-3).

## 6. Owner and authority model

`KleinPerkins/dev`, as a sibling `_ops/doc-warden/` subsystem — not a capability shelf (Options 2/3 rejected: this tool inspects/mutates sibling repos, it has no second consumer to install onto, so forcing `meta.yml`/`install.sh`/registry ceremony onto it would be pure overhead), not folded into `baseline-lib.sh` (Option 1b rejected: baseline's model is finite marker-diffable files; doc-warden needs a trigger catalog, `NEEDS_OPERATOR` escalation, provenance reconstruction, and semantic-collision handling that don't map onto `bl_baseline_verdict`'s vocabulary — folding it in would itself become "a second documentation-repair implementation," which baseline is explicitly barred from becoming). No-cpp-delivery is structural: `_ops/` has no capability-lifecycle or cpp-sync path at all (ADR-1, ADR-3).

## 7. Architecture and data flow

```
_ops/doc-warden/
  POLICY.md            canonical: taxonomy, precedence, lifecycle/supersession, normalization,
                        archival, verification, extension-point spec, detection heuristics
  triggers.yml          closed trigger catalog (id → detect → action → template → target → owner → verify)
  templates/             canonical templates (plan-header, docs-plans-README, docs-adr-README,
                        adr-entry, runbook, glossary, agents-md-pointer-block)
  state/                committed receipts (mirrors _ops/baseline/state/)
_ops/bin/doc-warden.sh         CLI: check, repair — the only two verbs
_ops/bin/doc-warden-lib.sh     shared engine: evidence gathering → normalized model → classification
                              → action plan → receipt (the one normalizer)
_ops/skills/doc-warden/SKILL.md  thin operator-facing wrapper
<any-repo>/.doc-warden.yml       optional local override: plans_dir / adr_dir (default: docs/plans, docs/adr)
```

Data flow: `POLICY.md + triggers.yml + templates/` (canonical) + repo's `.doc-warden.yml` (override, if any) + observed repo state (git-tracked files, history, cross-repo references) → `doc-warden-lib.sh` → classification per artifact → action plan → (`check` stops here) → (`repair --dry-run` prints diff+digest) → (`repair --approve` executes structural actions only, writes receipt).

Callers: `dev-new-repo.sh` (peer line calling `repair --approve --greenfield`, placed **after** the scaffold block's initial `git commit -m "init: scaffold ..."` call — not immediately after `repo-baseline.sh apply`, since at that earlier point in the script the repo has been `git init`-ed but has no commit yet, so there is no real, revertable HEAD for §12's rollback contract to bind to. Doc-warden's own receipt for the new repo — written to `_ops/doc-warden/state/<target-repo>/...` inside `~/dev`'s own tree, mirroring `_ops/baseline/state/` — is committed back into `~/dev` the same idempotent way `dev-new-repo.sh` already commits `_ops/baseline/state/` back into `~/dev` after `enforce`/`reconcile-merge-safety` act on the new repo) and `dev-doctor.sh` (loops `check` across doc-warden's own eligible-repo set — `repo-baseline.sh list`'s output plus `~/dev` itself, §5 — no second inventory). Neither reimplements policy logic.

Detection heuristics — scan depth: the plans/ADR directory classifier scans SHALLOW (top-level entries only) for names matching the canonical pattern (`<slug>-vN.md`, or a single-tracker no-suffix form for a continuously-amended document); non-matching entries — nested subdirectories, non-`.md` files — are out of scope for classification and are never flagged as drift. This is concrete, not theoretical: `~/dev`'s own `_ops/plans/` (this repo's `.doc-warden.yml` override target) contains both flat plan `.md` files and several nested project-scratch subdirectories with non-`.md` assets (e.g. `analytics-context-proposal/`, `dad-first-source/`, `evidence/`, `template-framework/`) — those nested directories are structurally out of scope by contract, not merely overlooked.

## 8. Artifact taxonomy

| Type | Default location | Governed by | Notes |
|---|---|---|---|
| Plans | `docs/plans/` (override: `.doc-warden.yml: plans_dir`) | doc-warden | Versioned, freeze-on-approval, byte-identical once approved |
| ADRs | `docs/adr/` (override: `adr_dir`) | doc-warden | 4-digit sequential, Nygard sections, byte-identical once accepted |
| Index/convention files (`docs/plans/README.md`, `docs/adr/README.md`) | Same dir as the artifacts they index (or override-dir equivalents) | doc-warden | Governed, in-place-mutable, **never frozen** — distinct from the byte-identical-forever Plans/ADRs rows above |
| Runbooks | `docs/runbooks/` | doc-warden | Operator procedures, trigger #3 |
| Glossary | `docs/GLOSSARY.md` | doc-warden | Trigger #7, created only on genuine terminology ambiguity |
| `AGENTS.md` pointer block | repo root, marker-delimited | doc-warden (render/diff, baseline-pattern) | Points to the repo's plans/adr location + `_ops/doc-warden/POLICY.md` |
| Historical/archived organic material | `docs/archive/<original-relative-path>` | doc-warden | git `mv`, stripped from active indexes, history preserved |
| `SECURITY.md` (boilerplate) | repo root | `repo-baseline` (unchanged) | Doc-warden's trigger #8 concerns substantive security *decisions* (ADR-shaped), not this floor file |
| `CODEOWNERS`, `.gitignore` block, `dependabot.yml` | repo root | `repo-baseline` (unchanged) | Explicitly out of doc-warden's scope |
| Canonical templates/policy themselves | `~/dev/_ops/doc-warden/` only | doc-warden (owner repo) | Never duplicated into consumer repos beyond their rendered projection |

The classifier structurally never scans any path outside its declared doc-roots (`docs/`, `docs/plans/`, `docs/adr/`, `AGENTS.md`, `GLOSSARY.md`, or — for this repo specifically — the `_ops/plans` + `_ops/adr` override). A plain `README.md`, and the capability-payload/lockkit files that `dev-new-repo.sh --capability` creates (`meta.yml`, `install.sh`, `.eco-registry.lock`, the CI workflow file), are therefore out-of-tree *by construction*, not merely unlisted. **Flag:** this is a must-resolve-before item on any future work that removes `dev-new-repo.sh`'s current early-exit gate on real (non-dry-run) `--capability` invocations — that future work must decide whether capability payloads get their own doc-warden taxonomy row or remain permanently out of scope.

## 9. Trigger model

Closed catalog in `triggers.yml`. M1 ships 3 (deliberately excludes trigger 1 so POC 3a can exercise a genuine unknown case):

| # | Trigger | Action | In M1? |
|---|---|---|---|
| 1 | First architectural decision | Create ADR | No — reserved as POC 3a's unknown case |
| 2 | First substantial multi-session plan | Create plan | Yes |
| 3 | First operator-facing runbook | Create runbook | Yes |
| 4 | First significant incident/remediation | Create corrective plan | No (M2+) |
| 5 | First durable external contract | Create ADR | No (M2+) |
| 6 | First cross-repo authority boundary | Create ADR in owning repo + pointer in dependent(s) | No (M4/POC 3d) |
| 7 | First terminology ambiguity | Create glossary | Yes |
| 8 | First material security/threat-model decision | Create ADR | No (M2+) |

Each entry: id, detect (heuristic, may require agent/operator judgment to *recognize*), action, target template, target path, index-update target, owner (repo-owner approval), verify rule. Recognizing a trigger fired is judgment; the resulting artifact/location/owner/verification is 100% deterministic once proposed — satisfies "discoverable without relying on memory."

Trigger-fired artifact creation is not one atomic action: it splits into a DETERMINISTIC skeleton (auto-appliable under an ordinary approved repair) and SEMANTIC prose content (always a separate, human-authored follow-up) — see §12 for the exact boundary, the new `NEEDS_AUTHORING` classification status, and why `--greenfield` never produces it.

## 10. Unknown-case behavior

No match against `triggers.yml`, and not `CONFORMANT` → classification `NEEDS_OPERATOR`. No writes. Output: description of the unmatched observed condition, smallest viable options, a recommendation. `check` exits `3` specifically for this case so a calling agent/script can mechanically distinguish "stop and ask" from "just repair." Resolution workflow once approved: (1) update `triggers.yml` first; (2) project into the originating repo via ordinary `repair --approve`; (3) re-run the *existing* `dev-doctor` fleet loop (no new mechanism — `check` re-evaluates against current policy automatically); (4) queue any further propagation one repo at a time with approval.

## 11. Provenance and evidence model

Precedence order for reconstruction (highest first): current `AGENTS.md`/policy/operating manuals/governed contracts → approved plans/accepted ADRs → current code/schemas/tests/enforcement behavior → git history/commits/tags/releases → issues/PRs/reviews/remediation records → runbooks/operator procedures → non-conforming historical documents/implicit conventions → cross-repo authority references → transcripts (last resort, private evidence only, **never copied verbatim into durable docs**).

Every proposed canonical assertion carries an evidence record:
```yaml
claim: "<the proposed canonical statement>"
source_type: agents_md | plan | adr | code | git_history | issue_pr | runbook | historical_doc | cross_repo_ref | transcript
source_ref: "<path, commit sha, blob ref, or PR#>"
confidence: verified | inferred | contested
conflicting_evidence: ["<pointer>", ...]
resolution: accepted | rejected | escalated_to_operator
```
Semantic ambiguity or conflicting authority → `CONTRADICTORY` classification, always escalated — never silently resolved by an LLM.

**M1 scope note:** the full 9-source-type evidence-record schema above is canonical POLICY as specified here — no unresolved decision is deferred. M1's actual CODE, however, only needs a working reconstruction implementation for the source types that M1's 2 shipped triggers (§9: multi-session plan, runbook) plus the `NEEDS_OPERATOR` escalation path actually reach — in practice `agents_md`, `plan`, `adr`, and `code`, exercised via straightforward file-existence checks against a brand-new canary repo with essentially no history to reconstruct from. The remaining source types (`git_history`, `issue_pr`, `historical_doc`, `cross_repo_ref`, `transcript`) may be stubbed until M3 / POC 3c, which is the actual reconstruction-heavy stress test against a thin, heavily-integrated repo.

## 12. Report and repair safety model

Verbs: `check` (read-only, exit `0`/`1`/`3`), `repair --dry-run` (read-only, exact plan + diffs + digest, flags semantic items separately), `repair --approve --revision <sha> --plan-digest <digest>` (refuses on HEAD or digest mismatch; executes only structural actions from that exact plan; never auto-applies flagged/semantic items; writes a receipt to `_ops/doc-warden/state/`), `repair --approve --greenfield` (narrow non-interactive path, only valid when `check` returns exclusively `MISSING`/`CONFORMANT`).

**Deterministic vs. semantic split for trigger-fired content.** When a trigger fires (§9), the resulting artifact creation splits into two layers. DETERMINISTIC — auto-appliable under an ordinary `repair --approve --revision <sha> --plan-digest <digest>` — covers only: the skeleton file rendered from the canonical template (header, metadata/status line, section headings with placeholder markers such as `<!-- TODO: author -->`), its target path, its index row (rendered with a human-readable status of "DRAFT — needs authoring"), and its owner assignment. SEMANTIC — never auto-applied under any repair mode, ever — covers the actual prose content that fills the skeleton in (an ADR's Decision/Why/Consequences, a runbook's steps, a glossary definition); it always arrives as a separate, human-authored follow-up commit/PR, reviewed exactly like any other semantic-prose change per this section's diff-review requirement below. `doc-warden`'s own internal classification for a just-created skeleton is a new status, `NEEDS_AUTHORING` — distinct from `NEEDS_OPERATOR` (§10): it is the *expected*, known outcome of skeleton creation, not an unknown-case escalation, and it does not stop `repair` from applying the rest of an otherwise-clean plan. `check` also reports `NEEDS_AUTHORING` for a skeleton still awaiting its semantic follow-up, at exit `1` (a known, describable, human-PR-repairable state) — never exit `3`, which stays reserved for a genuine `NEEDS_OPERATOR` unknown-trigger case per §10. `--greenfield` is unaffected by this split: it only ever creates the baseline inheritance structure (empty `docs/plans/`, `docs/adr/`, their index files, the `AGENTS.md` pointer block) for a brand-new repo, never trigger-fired content, so it never produces a `NEEDS_AUTHORING` item.

**`repair` exit codes** (a distinct ladder from `check`'s existing `0`/`1`/`3` above): `0` = applied cleanly, or (`--dry-run`) a plan was computed, including an empty "already conformant" plan; `1` = refused — HEAD mismatch, digest mismatch, or a failed `--greenfield` precondition; `2` = applied successfully but created one or more `NEEDS_AUTHORING` skeletons, signalling an unattended caller (a script, a fleet loop) that human follow-up is now expected before the repo is fully conformant.

**`--greenfield` self-validation.** `repair --approve --greenfield` MUST internally re-run a `check`-equivalent classification immediately before mutating, and refuse (zero writes) unless every classified item is `MISSING` or `CONFORMANT` — regardless of what the caller believes about the repo's state. The flag selects a lighter safety mechanism appropriate to a brand-new repo (no revision/digest pinning needed, since there is no prior approved state to protect) — never an exemption from validation.

**`--plan-digest` scope.** The digest is a hash over the rendered, byte-for-byte contents of every file the plan would write or move, taken in one canonical deterministic order — not a hash of the abstract operation list. A template edited between `--dry-run` and `--approve` therefore always invalidates a previously-computed digest, even when the abstract action list (e.g. "create ADR skeleton at path X") is unchanged.

Rollback: `git revert` is the specified mechanism for rolling back any pushed/shared commit — the normal case for an approved repair delivered via PR. `git reset` is permitted only for a strictly local, unpushed, single-commit undo (e.g. a mid-session correction before push). Byte-stability: re-running `repair --dry-run` after an approved repair must yield an empty plan. Structural changes normalize deterministically; semantic prose changes always require a human-reviewed exact diff, never auto-applied even under `--approve`.

## 13. Archival model

Two classes, resolved explicitly per operator decision (stricter than current fleet practice):

1. **Approved plans / accepted ADRs** — byte-identical forever, no exception (not even a status-bullet edit). Supersession recorded only via the new document's `Supersedes:` pointer and the index file's row. (`pr-automation-controller/docs/plans/README.md` currently documents allowing a 1-line status-bullet edit on the superseded file itself — POC 3b corrects this wording; see §17.)
2. **Non-plan/ADR organic material** — physically moved to `docs/archive/<original-relative-path>` via git `mv` (preserves blame/history), stripped from active indexes/routing. Purely generated/reconstructable duplicates may instead be deleted outright, only when deterministic, previewed, approved, rollback-able via git, and post-write-verified.

Durable archives never preserve credentials, secrets, auth state, live config, raw env dumps, raw transcripts, unnecessary PII, or sensitive machine-local receipts — sensitive evidence retains only a sanitized description, repo path, commit/blob ref, digest, evidence classification, and decision provenance.

**Classification stickiness.** Once a document is classified `Approved plan` or `Accepted ADR` (class 1 above), that classification is receipt-tracked — recorded in `_ops/doc-warden/state/` — not path-pattern-only. It therefore survives a later `.doc-warden.yml` override change to `plans_dir`/`adr_dir`, and is never silently reclassified as archivable "organic material" (class 2) merely because a directory path changed underneath it.

## 14. Integration matrix

| System | Relationship | Authority boundary |
|---|---|---|
| `repo-baseline` / `baseline-lib.sh` | Pattern precedent only (marker-block render/diff style copied, not shared code) | Baseline owns GitHub-settings/floor-file compliance; doc-warden owns documentation content — zero code sharing, zero call in either direction |
| `dev-new-repo.sh` | Called by (peer line, `repair --approve --greenfield`) | dev-new-repo orchestrates; doc-warden only renders/classifies its own domain |
| `dev-doctor.sh` | Called by (loops `check` over the existing fleet list) | dev-doctor reports only; never mutates; no new inventory mechanism |
| `pr-automation-controller` | Delivered through (approved repairs become ordinary PRs; existing verifier/reviewer Apps process them unchanged) | Not the normalizer, not the policy authority, not the semantic reviewer |
| `agent-route` | Called by (routes operator language to `_ops/skills/doc-warden/SKILL.md`) | Routes only; does not create repos or authorize repair |
| `/swarm` | Calls (optional, for semantic-collision option-generation and POC 3c-style reconstruction assistance) | Discovery/proposal only; never mutation authority |
| Capability lifecycle (WF1/WF2) | None — structurally outside it | This *is* the no-cpp-delivery guarantee (ADR-1, ADR-3) |

Both `NEEDS_OPERATOR` and `NEEDS_AUTHORING` map to `dev-doctor.sh`'s existing `DRIFT` verdict category (visible in its report table) — never to `VIOLATION` — and never flip `dev-doctor.sh`'s own process exit code; its stated invariant (`_ops/checks/dev-doctor.sh`: "exits non-zero ONLY when a VIOLATION is found") is preserved exactly as-is. `dev-doctor.sh`'s doc-warden check loop targets doc-warden's own eligible-repo set (§5: `repo-baseline.sh list`'s output plus `~/dev` itself) — unlike its own pre-existing baseline check, it does not reuse `bl_classify_repo`'s umbrella (`rel=="."`) exclusion; that baseline check is unaffected and keeps excluding `~/dev` exactly as it does today.

## 15. Reconciliation doctrine

Governing shape: canonical/previous state + observed state + provenance → deterministic classification → safe additive/subtractive proposal → explicit collisions/unknowns → approved action → receipt/verification/rollback. **Decision: Option A (shared doctrine + contract)** — forced by evidence, not merely preferred: `repo-baseline` (bash), cpp's integrity engine (Python), and `server-guard` (mixed sh/Swift/Python) are three already-existing, independent implementations of this same shape. Option B's own stated precondition — same runtime, no cross-language bridge — is already empirically false across the ecosystem. Full rationale in ADR-0002. The shared contract itself (classifications, lifecycle concepts, receipt shape, collision behavior, conformance fixtures) is documented in `_ops/doc-warden/POLICY.md` as a model + fixtures — no new package or service.

## 16. Complete roadmap

| M | Content | Proves | Gate |
|---|---|---|---|
| **M1** | Engine (`check`+`repair`, lib), policy v1 (3 triggers), `dev-new-repo.sh`/`dev-doctor.sh` wiring, POC 3a on new `doc-warden-canary` | Full loop: policy→projection→check→dry-run→approved repair→receipt→verify→rollback; real `NEEDS_OPERATOR`→4th-trigger promotion | Operator GO before repo creation; GO before canary repair approval |
| **M2** | POC 3b — `pr-automation-controller` | `DRIFTED`/`SUPERSEDED` classification; stale-cross-reference correction; dual-skeleton local governance preserved | Operator GO before repair approval on a real, in-use repo |
| **M3** | POC 3c — `ecosystem-orchestrator` | Full provenance/evidence reconstruction against thin-docs/heavy-integration repo | Operator GO before repair approval |
| **M4** | POC 3d — AWA ↔ dev host overlay | Cross-repo authority ownership; duplicate/contradictory active-authority removal | Operator GO before any cross-repo pointer/removal action |
| **M5** | Gated fleet rollout | Report-only fleet `check` first, then canary-paced one-repo-at-a-time `repair` across remaining ~19 eligible repos | Per-repo operator GO, no exceptions; pauseable/reversible |
| **M6 (ongoing)** | Maintenance / policy evolution | Steady-state trigger growth, periodic policy revision | Standing GO — each policy version bump is its own small approval, not a new milestone |

Deferred, not dropped: richer semantic-review tooling beyond basic `/swarm` calls (M3+ candidate if POC 3c proves insufficient); a `_ops/plans/` index (deferred until proven needed — currently unindexed by existing precedent); tag-protection/PR-required-workflow baseline candidates (already deferred by `_ops/baseline/README.md` itself, unrelated to this plan).

## 17. Proof of concept specifications

Each spec below states all twelve required fields: target & rationale, fixed starting revision/fixture, report-only phase, repair phase, expected action classifications, no-change invariants, operator gates, rollback, acceptance tests exercised, evidence retained, sensitive-data handling, and pass/revise/stop criteria.

### POC 3a — Greenfield inheritance (= M1)

- **Target & rationale:** new repo `KleinPerkins/doc-warden-canary`, created solely for this POC. A genuinely empty starting state is the only way to exercise deterministic inheritance and a real `NEEDS_OPERATOR` escalation without pre-existing drift confounding the result.
- **Fixed starting revision/fixture:** the repo's first commit, produced by `dev-new-repo.sh`'s ordinary (non-`--capability`) scaffold path, captured immediately after creation and before any doc-warden action runs.
- **Report-only phase:** `check` immediately post-creation must classify every taxonomy row `CONFORMANT` (baseline inheritance already applied) except ADR/runbook/glossary, which are future-conditional on a trigger and must NOT be flagged `MISSING` before one fires.
- **Repair phase:** (1) hand-author one small multi-session plan (fires trigger #2) → `repair --dry-run` then `--approve --revision <sha> --plan-digest <digest>` creates the plan's skeleton + index row (`NEEDS_AUTHORING` for its prose); (2) hand-make a first architectural decision (fires trigger #1, deliberately excluded from the M1 catalog) → `check` must return `NEEDS_OPERATOR` with zero writes.
- **Expected action classifications exercised:** `CONFORMANT` (post-baseline) → `MISSING`→structurally-repaired (trigger #2 skeleton) → `NEEDS_AUTHORING` (trigger #2 prose) → `NEEDS_OPERATOR` (trigger #1, genuinely unknown).
- **No-change invariants:** the `NEEDS_OPERATOR` check makes zero writes to `doc-warden-canary`; a second `repair --dry-run` immediately after trigger #2's approved repair returns an empty plan.
- **Operator gates:** repo creation; trigger #2's repair approval; trigger #1's new-rule co-design (template, target path, owner, verify rule) once escalated; the resulting `triggers.yml` update; its projection back into `doc-warden-canary`.
- **Rollback:** `git revert` the trigger #2 skeleton-creation commit in `doc-warden-canary`; the `triggers.yml` catalog-growth commit in `~/dev` is independently revertible without touching the canary repo.
- **Acceptance tests exercised:** ledger items 1, 2, 3, 4, 6, 7, 8, 15, 16, 18 (§19).
- **Evidence retained:** both repair receipts under `_ops/doc-warden/state/doc-warden-canary/`; the `NEEDS_OPERATOR` escalation record; the approved `triggers.yml` diff.
- **Sensitive-data handling:** none expected — brand-new repo, no legacy history to reconstruct from.
- **Pass/revise/stop:** Pass = every listed classification observed in order, zero unexpected writes, byte-stable second repair, trigger #1 successfully promoted and correctly projected. Revise = an expected classification didn't fire — fix the classifier and re-run this POC. Stop = any write occurs without a matching operator-approved digest — halt and root-cause before proceeding to POC 3b.

### POC 3b — Mature but non-uniform

- **Target & rationale:** `personal/pr-automation-controller` — the fleet's most mature existing plan/ADR convention, with one already-verified live drift and one wording gap relative to doc-warden's stricter rule, making it the right test of "conform without flattening valid local differences."
- **Fixed starting revision/fixture:** the repo's `main` HEAD as of the M2 start date (record the exact sha at POC kickoff).
- **Report-only phase:** `check` surfaces exactly two `DRIFTED` items — (1) `docs/plans/README.md`'s stale cross-reference at L56–57 claiming `docs/adr/` lacks an index; (2) the same file's rule-3 status-bullet allowance, looser than doc-warden's byte-identical-forever rule (§13) — and classifies the dual-plan-skeleton convention `CONFORMANT` under the repo's own declared valid skeletons.
- **Repair phase:** a two-line dry-run preview (one line per drift) → approved repair applies both via an ordinary branch + PR through the repo's own v3 merge path (doc-warden never bypasses a repo's existing delivery mechanism).
- **Expected action classifications exercised:** `DRIFTED` ×2 → structurally-repaired; `CONFORMANT` (dual-skeleton, untouched).
- **No-change invariants:** the dual-plan-skeleton pattern, every other README section, and every existing plan/ADR file are byte-identical before and after.
- **Operator gates:** repair-approval on a real, in-use repo — a higher bar than the greenfield canary, since this is the first POC touching live, externally-relied-upon content.
- **Rollback:** `git revert` the one delivered commit (already merged via the repo's normal PR path, so revert — not reset — per §12).
- **Acceptance tests exercised:** ledger items 6, 7, 9, 10, 12, 14 (§19).
- **Evidence retained:** the repair receipt; the before/after diff of both corrected lines; the PR link.
- **Sensitive-data handling:** none expected — the drift is documentation wording, not data.
- **Pass/revise/stop:** Pass = only the two verified drifts change, dual-skeleton and everything else byte-identical, delivered via the repo's own PR path with no doc-warden-specific bypass. Revise = `check` finds a drift beyond the two pre-verified ones — pause, do not repair an undiscussed item, bring it to the operator as a new case first. Stop = the dual-skeleton pattern gets flagged as drift by mistake — halt, that would mean the classifier is over-normalizing valid local governance, a core requirement violation.

### POC 3c — Under-documented (organic growth, heavy integration)

- **Target & rationale:** `personal/ecosystem-orchestrator` — thinnest in-repo documentation (4 files, no `AGENTS.md`, no ADR/plans dir) of any heavily-depended-on repo in the fleet (45 files / 124 references depend on it per prior research), making it the real stress test for provenance-driven reconstruction.
- **Fixed starting revision/fixture:** the repo's `main` HEAD as of the M3 start date (record the exact sha at POC kickoff).
- **Report-only phase:** full provenance reconstruction per §11's precedence order (code/tests/config first, then `OPERATING-MANUAL.md` cross-references, then git history, then cross-repo references) to propose a minimum canonical `AGENTS.md` + one ADR capturing its "single sanctioned writer of the cpp edge" role — every proposed claim carries a full evidence record (§11 schema, all 9 source types now genuinely exercised, closing the scope M1 deliberately deferred).
- **Repair phase:** dry-run preview of the new `AGENTS.md` + ADR-0001 skeletons (structural) with the full evidence-record set attached for operator review; any contested or conflicting claim is `CONTRADICTORY`, always escalated, never silently resolved.
- **Expected action classifications exercised:** `MISSING` (no `AGENTS.md`/ADR exist) → structurally-repaired (skeletons) → `NEEDS_AUTHORING` (the ADR's Decision/Why/Consequences body) → `CONTRADICTORY` (for any claim with genuinely conflicting sources — expected to occur at least once given the repo's thin history).
- **No-change invariants:** zero claims are asserted as canonical without a cited source and confidence tag; a `CONTRADICTORY` claim is never silently resolved by the engine or an LLM.
- **Operator gates:** repair-approval on the reconstructed `AGENTS.md`/ADR skeletons; separately, resolution of every `CONTRADICTORY` claim before it's allowed into the canonical document.
- **Rollback:** `git revert` the skeleton-creation commit; the semantic content (once authored) follows the same human-reviewed-diff path as any other semantic change.
- **Acceptance tests exercised:** ledger items 6, 7, 11, 13, 14 (§19).
- **Evidence retained:** the full evidence-record set (claim/source_type/source_ref/confidence/conflicting_evidence/resolution) for every proposed assertion, contested or not.
- **Sensitive-data handling:** git history and PR/issue records may reference internal discussion — only sanitized pointers (path, commit sha, PR#) are retained in the evidence record, never raw quoted transcript or PR-comment text.
- **Pass/revise/stop:** Pass = every canonical claim in the resulting `AGENTS.md`/ADR has a cited source and confidence tag, zero contested claims silently resolved. Revise = the reconstruction proposes a claim with no traceable source — pull it, don't assert it. Stop = evidence-gathering surfaces anything resembling a credential, token, or PII — halt immediately, do not include it in any receipt or evidence record, report to the operator out-of-band.

### POC 3d — Cross-repository authority

- **Target & rationale:** AWA (`KleinPerkins/awa`) ↔ `~/dev`'s host overlay (`_ops/awa/`) — a real, already-documented cross-repo relationship where the same canonical facts are described in two places, making it the right test for "cross-repository policy does not become ownerless."
- **Fixed starting revision/fixture:** both repos' `main` HEAD as of the M4 start date (record both shas at POC kickoff).
- **Report-only phase:** identify every duplicated canonical AWA statement appearing in both `KleinPerkins/awa`'s own docs and `~/dev`'s `_ops/awa/` overlay docs; classify each as owned-correctly-in-one-place, duplicated, or contradicting.
- **Repair phase:** for each duplicate/contradiction, establish sole ownership (the standalone system repo, `KleinPerkins/awa`, per the existing SSP/GCB pattern) and convert the other copy to an explicit pointer/reference — never deleted outright without review, per §13's rule for cross-repo material.
- **Expected action classifications exercised:** `DUPLICATE_AUTHORITY` (a classification specific to this POC's cross-repo case — both copies exist and agree) and `CONTRADICTORY` (both copies exist and disagree) → both structurally resolved to one owner + one reference.
- **No-change invariants:** every statement retains exactly one canonical owner and zero contradicting copies after repair; nothing is deleted without an explicit operator review step first.
- **Operator gates:** approval before any cross-repo pointer/removal action, since this is the only POC that touches two repositories from one repair action — each repo's change ships as its own separate, independently-reviewable commit/PR, never a single atomic cross-repo transaction.
- **Rollback:** `git revert` in each affected repo independently (they are never coupled into one non-revertible transaction).
- **Acceptance tests exercised:** ledger items 6, 7, 9, 10, 11 (§19).
- **Evidence retained:** the before/after ownership map (which repo owns which statement, and where the reference lives).
- **Sensitive-data handling:** none expected — AWA's own docs are already scoped to exclude credentials/secrets per its own security model.
- **Pass/revise/stop:** Pass = every previously-duplicated statement has exactly one owner and the other location is a reference, not a copy. Revise = a statement's true owner is ambiguous even after reconstruction — escalate as `NEEDS_OPERATOR`, do not guess. Stop = any statement would end up with zero owners after repair (i.e., both copies would be removed) — halt, this violates the "never ownerless" invariant outright.

## 18. Atomic work-item ledger (M1 fully decomposed; M2–M6 scope-pointers)

Each M1 work item is scoped to one session and, where practical, one PR; each states its own prerequisites and produces the handoff state the next item needs.

**WI-M1-01 — Author canonical policy v1**
Objective: write the canonical policy source doc-warden's engine will read. Owning repo: `KleinPerkins/dev`. Scope: `_ops/doc-warden/POLICY.md` (taxonomy, precedence, lifecycle/supersession, normalization, archival, verification, extension-point spec, detection heuristics per §8–§13), `_ops/doc-warden/triggers.yml` (3 M1 triggers: #2 plan, #3 runbook, #7 glossary — each with id/detect/action/template/target/owner/verify), `_ops/doc-warden/templates/{plan-header,docs-plans-README,docs-adr-README,adr-entry,runbook,glossary,agents-md-pointer-block}.md` — the canonical policy source itself; no engine, CLI, or target-repo mutation. Interfaces/contracts: `POLICY.md`'s section contract (taxonomy, precedence, lifecycle/supersession, normalization, archival, verification, extension-point spec, detection heuristics — must cover §8–§13 1:1); `triggers.yml`'s per-entry schema (id/detect/action/template/target/owner/verify) for the 3 M1 triggers (#2 plan, #3 runbook, #7 glossary); the 7 template filenames as the render contract WI-M1-02 depends on. Prerequisites: none (first work item). Dependencies: none beyond this plan's own approved architecture. Session/PR boundary: one session, one PR. Allowed mutations: create-only, under `_ops/doc-warden/` exclusively. Non-goals: no engine code, no CLI, no repo mutation of any kind outside `~/dev`. Steps: (1) draft `POLICY.md` section by section, mirroring this plan's §8–§13 as the authoritative source; (2) draft `triggers.yml` for the 3 M1 triggers only; (3) draft the 7 templates; (4) self-review against §19 #1 and #12. Tests/commands: `yamllint _ops/doc-warden/triggers.yml`; manual structural review of `POLICY.md` against §8–§13. Evidence to retain: the PR diff itself. Rollback: `git revert` the PR's merge commit. Definition of done: `POLICY.md`, `triggers.yml`, and all 7 templates exist, are internally consistent with each other and with this plan, and the PR is merged. Handoff state: WI-M1-02 can read a stable, merged `POLICY.md`/`triggers.yml`/`templates/` as its normative input.

**WI-M1-02 — Build `doc-warden-lib.sh`**
Objective: the one shared engine — evidence gathering → normalized model → classifier → action-planner → receipt writer. Owning repo: `KleinPerkins/dev`. Scope: `_ops/bin/doc-warden-lib.sh` only. Interfaces/contracts: exposes 4 functions WI-M1-03's CLI depends on — an evidence-gatherer (per source type), a classifier (returns one of `MISSING`/`CONFORMANT`/`DRIFTED`/`NEEDS_OPERATOR`/`NEEDS_AUTHORING`/`CONTRADICTORY`), an action-planner (returns a structured plan + digest), and a receipt-writer (writes the receipt shape defined in §16/§18 to `_ops/doc-warden/state/<repo>/`); WI-M1-03 binds to these exact function signatures, not to this file's internals. Prerequisites: WI-M1-01 merged. Dependencies: `_ops/bin/baseline-lib.sh` (read as a rendering-pattern reference per ADR-0001, not imported/shared code). Session/PR boundary: one session, one PR — may split into two PRs if needed (evidence-gathering + normalization; then classifier + action-planner + receipt writer). Allowed mutations: create-only, `_ops/bin/doc-warden-lib.sh`; read-only against fixture repos during development, never a real fleet repo. Non-goals: no CLI entrypoint (WI-M1-03), no caller wiring (WI-M1-04); per §11's M1 scope note, does NOT need working reconstruction logic for all 9 source types — only `agents_md`, `plan`, `adr`, `code` need to actually work in M1, the remaining 5 (`git_history`, `issue_pr`, `runbook`, `historical_doc`, `cross_repo_ref`, `transcript`) may be stubbed (`not_implemented_until_m3`) since POC 3c is their real exercise. Steps: (1) build 3 local fixture repos under `/tmp` (empty→all `MISSING`; template-conformant→all `CONFORMANT`; hand-drifted→`DRIFTED` on the drifted files only); (2) implement evidence-gathering for the 4 M1-required source types; (3) implement the classifier (`MISSING`/`CONFORMANT`/`DRIFTED`/`NEEDS_OPERATOR`/`NEEDS_AUTHORING`/`CONTRADICTORY`); (4) implement the action-planner (structural-only plan generation, semantic items flagged separately per §9/§12); (5) implement the receipt writer (target repo id, revision, policy digest, approved actions, timestamp) to `_ops/doc-warden/state/<repo>/`. Tests/commands: `bash _ops/bin/doc-warden-lib.sh --self-test` covering all 3 fixtures × expected classification; a byte-stability test (run the classifier twice against the same fixture, assert identical output). Evidence to retain: the 3 fixture repos (kept under `_ops/doc-warden/fixtures/` for regression use by later work items), the self-test output. Rollback: `git revert` the PR's merge commit; no target-repo state to unwind. Definition of done: all 3 fixtures classify correctly, self-test passes, byte-stability holds. Handoff state: WI-M1-03 can call `doc-warden-lib.sh`'s functions directly against the same fixtures.

**WI-M1-03 — Build `doc-warden.sh` CLI**
Objective: the two-verb operator/caller-facing surface. Owning repo: `KleinPerkins/dev`. Scope: `_ops/bin/doc-warden.sh` only. Interfaces/contracts: the CLI grammar itself, which WI-M1-04's caller wiring and WI-M1-05's skill wrapper both bind to — `check <repo>` (exit `0`/`1`/`3`); `repair <repo> --dry-run` (exit `0`/`1`, prints plan+diff+digest); `repair <repo> --approve --revision <sha> --plan-digest <digest>` (exit `0`/`1`/`2`); `repair <repo> --approve --greenfield` (exit `0`/`1`). Prerequisites: WI-M1-02 merged. Dependencies: none new. Session/PR boundary: one session, one PR. Allowed mutations: create-only, `_ops/bin/doc-warden.sh`; read/write only against WI-M1-02's fixture repos during testing. Non-goals: no caller wiring (WI-M1-04). Steps: (1) implement `check` (exit 0/1/3 per §10); (2) implement `repair --dry-run` (prints plan + diff + digest, exit 0/1 per §12); (3) implement `repair --approve --revision --plan-digest` (refuses on HEAD/digest mismatch, applies structural actions only, writes receipt, exit 0/1/2 per §12); (4) implement `repair --approve --greenfield` (internal self-check per §12, refuses unless exclusively `MISSING`/`CONFORMANT`). Tests/commands: exercise every verb/flag combination against the WI-M1-02 fixtures; a revision-mismatch test (mutate the fixture between dry-run and approve, assert refusal); a digest-mismatch test (edit a template between dry-run and approve, assert refusal); a `--greenfield` misuse test (call it against the hand-drifted fixture, assert refusal); an exit-code assertion for every path. Evidence to retain: the test-run transcript (command + exit code + output) for each case above. Rollback: `git revert` the PR's merge commit. Definition of done: every verb/flag/exit-code case in §12 is exercised and passes. Handoff state: WI-M1-04 can call a stable `doc-warden.sh check`/`repair` from the two caller scripts.

**WI-M1-04 — Wire callers + `~/dev`'s own override**
Objective: connect doc-warden to the two existing entrypoints and make `~/dev` itself a doc-warden target. Owning repo: `KleinPerkins/dev`. Scope: one peer-line edit to `_ops/bin/dev-new-repo.sh` (placed after the scaffold block's first commit, calling `repair --approve --greenfield`, plus the commit-back-into-`~/dev` step for the receipt, per §7); one fleet-loop edit to `_ops/checks/dev-doctor.sh` (loops `check` across doc-warden's own eligible set — `repo-baseline.sh list`'s output plus `~/dev` itself, NOT reusing `bl_classify_repo`'s `rel=="."` exclusion, per §5/§14; maps `NEEDS_OPERATOR`/`NEEDS_AUTHORING` to `dev-doctor`'s DRIFT-equivalent category, never flipping its VIOLATION-only exit invariant); new file `~/dev/.doc-warden.yml`. Interfaces/contracts: `dev-new-repo.sh` calls `doc-warden.sh repair --approve --greenfield` (WI-M1-03's contract) after the scaffold's first commit, then commits doc-warden's own receipt back into `~/dev`, mirroring `_ops/baseline/state/`'s existing commit-back pattern; `dev-doctor.sh` calls `doc-warden.sh check` in a loop over doc-warden's own eligible-repo set (§5) and maps `NEEDS_OPERATOR`/`NEEDS_AUTHORING` to its own `DRIFT`-equivalent report category without touching its `VIOLATION`-only exit invariant; `.doc-warden.yml`'s schema is exactly `plans_dir: <path>` / `adr_dir: <path>`, consumed by `doc-warden-lib.sh`'s evidence-gatherer (WI-M1-02). Prerequisites: WI-M1-03 merged. Dependencies: `dev-new-repo.sh`/`dev-doctor.sh`'s current structure (re-verify line numbers immediately before editing — this plan's own citations may drift as those scripts evolve). Session/PR boundary: one session; one PR preferred (both edits are small and land together). Allowed mutations: the two named edits plus the one new `.doc-warden.yml`; no other changes to either caller script. Non-goals: does not touch `repo-baseline.sh`'s own baseline loop or its own exclusions (unchanged) — this adds a second, parallel, doc-warden-specific loop to `dev-doctor.sh`, it does not modify the existing baseline one. Steps: (1) re-read both live scripts to confirm current line numbers for the scaffold-commit and fleet-loop insertion points; (2) add the `dev-new-repo.sh` peer-line + receipt-commit-back step; (3) add the `dev-doctor.sh` doc-warden loop with the corrected eligibility set and exit-verdict mapping; (4) create `~/dev/.doc-warden.yml`; (5) dry-run `dev-new-repo.sh` to confirm the new call site is reached in the right order without executing a real repair. Tests/commands: a dry-run creation of a throwaway test repo, confirming doc-warden's greenfield repair fires after the first commit exists (inspect `git log` ordering); a `dev-doctor.sh` run scoped to `~/dev` + one other eligible repo (not the full fleet) confirming the doc-warden loop reports without mutating and without flipping dev-doctor's own exit code on a `NEEDS_OPERATOR`/`NEEDS_AUTHORING` result. Evidence to retain: the dry-run transcript; the scoped `dev-doctor.sh` test-run transcript. Rollback: `git revert` the PR's merge commit; delete the throwaway test repo. Definition of done: both caller integrations verified against a real (throwaway) invocation, not just read-through; `~/dev/.doc-warden.yml` committed. Handoff state: WI-M1-06 can create a real canary repo through the normal, wired `dev-new-repo.sh` path.

**WI-M1-05 — Thin operator skill wrapper**
Objective: `_ops/skills/doc-warden/SKILL.md`, mirroring the existing `_ops/skills/dev-doctor/SKILL.md` / `_ops/skills/dev-new-repo/SKILL.md` pattern. Owning repo: `KleinPerkins/dev`. Scope: one new file, `_ops/skills/doc-warden/SKILL.md`. Interfaces/contracts: documents `doc-warden.sh`'s exact verb/flag grammar (WI-M1-03's contract) as operator-facing usage; introduces no new verb, flag, or behavior of its own. Prerequisites: WI-M1-03 merged. Dependencies: none new. Session/PR boundary: one session, one PR (small). Allowed mutations: create-only, this one file. Non-goals: no new operator verbs beyond what `doc-warden.sh` already exposes. Steps: (1) read the two existing `_ops/skills/{dev-doctor,dev-new-repo}/SKILL.md` files for the exact wrapper convention; (2) write the doc-warden equivalent, delegating to `doc-warden.sh check`/`repair` exactly, adding no logic of its own. Tests/commands: manual check that every verb the skill describes matches `doc-warden.sh`'s actual `--help` output. Evidence to retain: none beyond the PR diff. Rollback: `git revert` the PR's merge commit. Definition of done: skill file merged, verbs match the CLI exactly. Handoff state: doc-warden is now operator-discoverable the same way `dev-doctor`/`dev-new-repo` are.

**WI-M1-06 — Execute POC 3a end to end**
Objective: run the full POC 3a spec (§17) for real. Owning repo: `KleinPerkins/dev` (creates `KleinPerkins/doc-warden-canary`). Scope: exactly POC 3a's spec (§17) — creates `KleinPerkins/doc-warden-canary`, no other repo touched. Interfaces/contracts: consumes WI-M1-03's CLI contract and WI-M1-04's wired `dev-new-repo.sh` path exactly as built; produces no new interface of its own — this item is an execution/evidence-gathering pass, not a build item. Prerequisites: WI-M1-01 through WI-M1-05 all merged. Dependencies: operator availability for POC 3a's gates (repo creation, trigger #2 approval, trigger #1 co-design). Session/PR boundary: likely spans 2–3 sessions given the multiple operator gates; each gate crossing is its own natural session boundary. Allowed mutations: exactly what POC 3a's repair phase describes. Non-goals: does not touch any other fleet repo. Steps: exactly POC 3a's "Repair phase" steps, in order, with each operator gate honored before proceeding. Tests/commands: §19 items 1,2,3,4,6,7,8,15,16,18 — check each explicitly. Evidence to retain: exactly POC 3a's "Evidence retained" list. Rollback: exactly POC 3a's "Rollback" description. Definition of done: POC 3a's own "Pass/revise/stop" criteria reach Pass. Handoff state: WI-M1-07 can cite POC 3a's concrete evidence as proof for the M1 acceptance-test pass.

**WI-M1-07 — M1 acceptance-ledger evidence pass**
Objective: verification-only close-out — confirm M1's claimed acceptance-test coverage against POC 3a's actual evidence, no new mutation. Owning repo: `KleinPerkins/dev`. Scope: read-only review of WI-M1-06's evidence against §19's 21-item ledger. Interfaces/contracts: none produced — this item is a verification pass, not a build item; its only output is the pass/fail memo named in its own Evidence-to-retain field. Prerequisites: WI-M1-06 complete. Dependencies: none. Session/PR boundary: one session; produces a short evidence memo, not necessarily a PR. Allowed mutations: none against any repo's functional content; at most an evidence-index note. Non-goals: does not re-run any repair; does not touch M2+ scope. Steps: (1) walk §19 items 1,2,3,4,6,7,8,15,16,18 one by one against WI-M1-06's retained evidence; (2) record pass/fail per item; (3) if any item fails, open it as a new, separate work item — never silently folded back into a "done" M1. Tests/commands: none beyond the review itself. Evidence to retain: the pass/fail memo itself. Rollback: not applicable (no mutation). Definition of done: every M1-scoped acceptance item has an explicit pass/fail verdict. Handoff state: M1 is closeable (or, if any item failed, exactly one new corrective work item is queued) before M2/POC 3b begins.

**WI-M2-00 … WI-M6-00 — scope pointers only.** Each milestone's work items are decomposed to this same shape at the start of that milestone, once its POC's live target state is re-verified (repo content shifts over multi-week gaps between milestones) — decomposing them now would risk stale line-number/file citations by the time M2+ actually starts.

## 19. Acceptance-test ledger (21 items)

Each item names the concrete procedure that proves it, not just the requirement it satisfies.

1. **New repos inherit the exact baseline** — create a throwaway repo via `dev-new-repo.sh`, run `doc-warden.sh check`, assert 100% `CONFORMANT` against `POLICY.md`'s v1 baseline set. (POC 3a)
2. **Known triggers produce the expected governed action** — fire trigger #2 in a fixture/canary repo, assert the resulting skeleton/path/index-row/owner exactly matches `triggers.yml`'s entry. (POC 3a)
3. **Unknown triggers stop with no writes** — fire trigger #1 (excluded from M1's catalog) in the canary repo, assert `check` returns `NEEDS_OPERATOR` and `git status` shows zero changes. (POC 3a)
4. **An approved new trigger updates canonical policy before repository projection** — after trigger #1's co-design, assert the `triggers.yml` commit in `~/dev` predates (by commit order) the projection commit in the canary repo. (POC 3a)
5. **Report-only fleet checks detect repositories affected by a new rule** — after trigger #1 is added, run `dev-doctor.sh`'s doc-warden loop across ≥2 eligible repos, assert any repo matching the new trigger's detect-condition is reported, not silently skipped. (M5 precursor, exercised in miniature during WI-M1-04's scoped test-run)
6. **`check` and `repair` consume the same normalized action plan** — instrument (or log-inspect) `doc-warden-lib.sh` to confirm both verbs call the identical classifier/action-planner function, not parallel implementations. (WI-M1-02/03 unit-level)
7. **Dry-run output matches the later approved mutation** — diff `repair --dry-run`'s printed plan against the actual files written by the subsequent `--approve` run, byte-for-byte. (WI-M1-03, POC 3a, 3b)
8. **A second repair is byte-stable and produces no changes** — run `repair --dry-run` immediately after any approved repair, assert an empty plan. (WI-M1-02 self-test, POC 3a)
9. **Stronger repository-specific governance is preserved** — in POC 3b, assert `pr-automation-controller`'s dual-plan-skeleton convention is unchanged before/after repair (byte diff on every file except the two verified drifts). (POC 3b)
10. **Superseded material leaves the active surface** — in a fixture with a deliberately-superseded plan, assert the old plan is removed from the active index and does not appear in the repo's routing/`AGENTS.md` pointer after repair. (WI-M1-02 fixture)
11. **Eligible history remains discoverable** — assert the same superseded plan still exists on disk (moved to `docs/archive/` per §13, not deleted) and is `git log`-traceable. (WI-M1-02 fixture, POC 3c)
12. **Approved plans and ADRs retain the same digest forever** — compute a SHA-256 of this plan file and each ADR immediately after this PR merges; re-check after every subsequent milestone's PR merges; assert no drift. (ongoing, checked at every milestone gate)
13. **Sensitive evidence is excluded or redacted** — grep every written receipt and evidence record for common credential/token/PII patterns before it's committed; assert zero matches. (every WI, every POC)
14. **Semantic prose cannot be mutated without an approved exact diff** — attempt (in a fixture) to have `repair --approve` apply a change to an ADR's Decision/Why/Consequences body; assert it is refused/flagged `NEEDS_AUTHORING`, never silently applied. (WI-M1-03, POC 3b)
15. **Rollback restores the pre-mutation state** — after any approved repair, run the stated rollback (`git revert`), diff the resulting tree against the pre-mutation commit, assert identical. (POC 3a, every subsequent POC)
16. **Receipts bind target revision, policy version, approved actions, and observed outcome** — read back a written receipt from `_ops/doc-warden/state/`, assert all four fields are present and match the actual repair that produced it. (WI-M1-02/03, POC 3a)
17. **`dev-doctor` reports through shared checks without mutating** — run `dev-doctor.sh` against a repo with a known drift, assert it reports the drift but `git status` in the target repo shows zero changes. (WI-M1-04's scoped test-run)
18. **New-repository inheritance uses the existing bootstrap** — confirm, by reading the diff (not just describing it), that WI-M1-04's `dev-new-repo.sh` change is a single peer-line addition, not a parallel repo-creation path. (WI-M1-04, POC 3a)
19. **Fleet repair cannot execute silently or all at once** — attempt `doc-warden.sh repair --approve` without an explicit `--revision`/`--plan-digest` pair (or `--greenfield`) against a real fleet repo; assert it refuses. Separately, confirm no code path in `doc-warden.sh`/`doc-warden-lib.sh` iterates the fleet and calls `--approve` in a loop. (WI-M1-03, code review)
20. **No cpp-sync, cpp payload, or cpp control-plane mutation is possible** — grep the entire `_ops/doc-warden/` and `_ops/bin/doc-warden*.sh` tree for any reference to `meta.yml`, `install.sh`, the capability registry, or any cpp path; assert zero matches. (per ADR-0001/0003; any milestone, static check)
21. **Every POC has reproducible evidence and explicit pass/fail criteria** — confirm each of POC 3a–3d's spec (§17) states fixed starting revision/fixture, expected classifications, and pass/revise/stop criteria before that POC executes, not after, retroactively. (this plan itself, verified at Gate 3)

## 20–26. Dependencies, Risks, Migration, Rollout, Rollback, Evidence, GO/NO-GO gates

Dependencies: repo-baseline/baseline-lib (pattern only), dev-new-repo.sh/dev-doctor.sh (call sites), git (rollback substrate), gh CLI + pr-automation-controller v3 (delivery path), /swarm (optional semantic assist).
Risks: inconsistent trigger-detection judgment across sessions (mitigated: triggers.yml is sole heuristic source, NEEDS_OPERATOR is safe default); `_ops/plans/` has no index (mitigated: POLICY.md §9 pointer is the anchor, index deferred not dropped); dev-doctor.sh currently hangs live, unresolved root cause (flagged as an M5 prerequisite health-check, not an M1-M4 blocker since those call doc-warden.sh directly against one repo); provenance-reconstruction LLM overconfidence (mitigated: hard escalation requirement); fleet rollout touching unknown local governance (mitigated: exclusion list + one-repo-at-a-time gating).
Migration: existing repos migrate via ordinary repair dry-run→approve, one at a time, POCs before general fleet; ~/dev migrates itself via WI-M1-04's .doc-warden.yml + this session's hand-authored _ops/adr/ creation.
Rollout: report-only first, canary-based, one repo at a time, operator-approved, pauseable/reversible, evidenced, exclusion-aware.
Rollback: every mutation is an ordinary git commit/PR; rollback follows §12's mechanism — `git revert` for any pushed/shared commit (the normal case), `git reset` only for a strictly local, unpushed, single-commit undo.
Evidence: receipts in _ops/doc-warden/state/ (committed); evidence records per §11 schema attached to any reconstruction-derived action.
GO/NO-GO: Gates 0-2 already exercised (cpp read-only-only, owner/name/POCs, architecture/ADR decisions). Gate 3 (this package, post-swarm) authorized publication only. Gate 4 — operator acceptance of this exact published text as the execution plan — is recorded in the header's Status line above (2026-08-05); it clears WI-M1-01 through WI-M1-05 to begin without a further planning gate. Separate later GOs remain required before: WI-M1-06 creates doc-warden-canary; any POC's repair --approve executes; M5 touches any repo beyond the four POCs.
