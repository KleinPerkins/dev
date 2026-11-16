# Context Efficiency Release 2 — Prove clients and close the program

**Version:** v1
**Status:** ACCEPTED
**Date:** 2026-08-23
**Owning repository:** `KleinPerkins/dev` (`~/dev`)
**Owner:** Laurence Duggan (Dev/program owner for C-01/C-02; each owner repo owns its own C-03)
**Plan-type:** standard
**Program milestone:** Release 2, “Prove clients and close the program” (C-01, C-02, C-03).
**Authority:** [`context-efficiency-program-v2.md`](context-efficiency-program-v2.md) Release 2 (§7 task table C-01/C-02/C-03) and §10 completion criteria; [D-01 inventory plan](context-efficiency-d01-capability-discovery-inventory-v1.md) (the reused capture/validate tool); the D-04 reconciliation plan (`KleinPerkins/ecosystem-orchestrator` `docs/plans/context-efficiency-d04-projection-reconciliation-v1.md`, ACCEPTED 2026-08-22, Release 1.1 completion).
**Baseline (live-verified 2026-08-23):** Dev `origin/main` `7037fcc`; Skills `origin/main` `f5a028b`; orchestrator `origin/main` `d36c10c`; CPP `origin/main` `5d5d584`. Release-0 `static-context-manifest-v1.json` `FROZEN`; Release-1 `release1-static-reduction-v1.json` `PASS`; Release-1.1 `capability-discovery-inventory-v1.json` `PASS`.
**Review provenance:** Live on-disk verification of the four owner refs and the three Release 0/1/1.1 evidence artifacts; a read-only cross-repo staleness/residual pass; a live re-run of the `skill-creator` zero-link check (PASS); and inspection of the D-01 tool contract. An independent rigor review hardened this draft pre-acceptance; Bugbot review precedes operator acceptance.

Accepted 2026-08-23 at Gate 1. Recorded Gate-1 decisions: the C-01 client scope is **Cursor only** (Claude and Codex stay ineligible with a documented product constraint — no reliable discovery-catalog source), and the fresh-surface capture is run by a **Dev-rooted agent**. Execution proceeds behind the remaining named gates only: the C-02 closure review and each C-03 owner GO. C-02 protected-merge and each C-03 cleanup still require their own authorization; this plan is not edited further.

**Changelog**
- v1 (2026-08-23) — Define the final Release 2 closure lane: the fresh-client projection matrix (C-01), the single versioned final-evidence/built-versus-planned record (C-02), and per-owner documentation closure (C-03), binding live post-Release-1.1 refs and recording verified residuals.
- v1 accepted (2026-08-23) — Hardened pre-acceptance via an independent rigor review (exact D-04 counts, S-03/PR-116 citation, M-series in built-versus-planned, AWA consistency, Gate-1→M0 ordering); accepted at Gate 1 with C-01 scope = Cursor-only and a Dev-rooted capture agent.

## 1. Purpose and boundary

Releases 0, 1, and 1.1 measured the denominator, reduced the static context, and reduced (and reconciled) the capability-discovery surface. Release 2 does not reduce anything further. It closes the program by proving three things and recording one durable result:

1. **C-01 — clients actually see the reductions.** Re-run the merged D-01 capture/validate flow on *fresh* client surfaces and prove the reduced descriptions are what the client discovery surface exposes, with identity/exposure/eligibility otherwise unchanged. Source-repository byte parity (already proven by D-04) is not client-projection proof.
2. **C-02 — one durable, content-safe final record.** Protected-merge a single versioned final-evidence and built-versus-planned artifact naming exact owner refs/digests, the static result, the catalog (client) result, verified residuals, and rollback refs, with no unresolved P0/P1.
3. **C-03 — owner docs match reality.** Each owner repository updates only the documentation/policy made stale by its own implementation and removes superseded process residue.

Boundary: no new reduction, exposure, enrollment, exclusion, or registry change; no re-opening of a merged release; no raw description or private client text in any artifact; the single sanctioned owner edges are unchanged (Skills/CPP/orchestrator/Dev never write each other outside the orchestrator’s sanctioned edge).

## 2. Authority, prerequisites, and live-verified state

### 2.1 The program snapshot is stale; this plan binds live state

`context-efficiency-program-v2.md` §2.2/§2.3 is an accepted **2026-08-16 snapshot** that still reads `E01_E02_E03_E04_PLANNED_NOT_IMPLEMENTED`. That is history, not current truth: D-01 through D-04 have since shipped. Those authoring-time pins are not license to trust stale refs later: Release 2 binds the live-verified refs and evidence in §2.2 below, and M0 re-verifies them at execution time. The accepted program plan is not edited.

### 2.2 Live-verified current state (2026-08-23)

| Owner | Repo | `origin/main` | Role in Release 2 |
|---|---|---|---|
| Dev | `KleinPerkins/dev` | `7037fcc` | Program owner; C-01 capture root (`DEV_ROOT`); C-02 evidence host |
| Skills | `KleinPerkins/skills` | `f5a028b` | D-02 reduced descriptions; C-03 owner (S-02 label) |
| Orchestrator | `KleinPerkins/ecosystem-orchestrator` | `d36c10c` | Sanctioned ld→CPP edge; C-03 owner (`registry.yml` comment) |
| CPP | `Affirm/card-platform-product` | `5d5d584` | Vendored client projections (13 D-04 payloads merged) |
| AWA | `KleinPerkins/awa` | `01053f6` | Capability source for the C-01 capture; C-02 `owner_ref` |

| Release | Evidence artifact (`_ops/evidence/context-efficiency/`) | Schema | Status |
|---|---|---|---|
| 0 (E-09 freeze) | `static-context-manifest-v1.json` | `static-context-manifest/v1` | `FROZEN` |
| 1 (static reduction) | `release1-static-reduction-v1.json` | `context-efficiency-release1-static-evidence/v1` | `PASS` (`RELEASE1_STATIC_TARGET_MET`) |
| 1.1 (discovery inventory) | `capability-discovery-inventory-v1.json` | `capability-discovery-inventory/v1` | `PASS` |

### 2.3 C-01 prerequisite satisfaction

C-01 requires “Releases 1 and 1.1 merged/reconciled” and an accepted Dev closure plan (this document).

- **Release 1:** complete. `release1-static-reduction-v1.json` is `PASS` with the 30% word and character targets met; the evidence records owner reductions S-01 (Dev, PR 285), S-02 (Skills, PR 152), and the conditional S-03 (AWA, PR 116) all merged.
- **Release 1.1:** complete. The merged D-01 inventory is `PASS`; D-02/D-03 descriptions merged; D-04 reconciled the **13** description-reconciliation target payloads into CPP `origin/main` `5d5d584` with byte parity, lockkit parity, and all **26** zero-link checks green (13 masters + 13 CPP payloads), proven at D-04 M3. The registry-wide Option-B sync that delivered those 13 also re-vendored 2 unrelated drifted capabilities (**15** payloads total), and post-sync consistency covered all **27** enrolled capabilities; the **13** targets are the C-01 pass-rule and C-02 evidence input.

Acceptance of this plan supplies the remaining closure-plan prerequisite.

### 2.4 Verified residual ledger

Reconnaissance and a live re-check classified every open item. Two prior plan-snapshot concerns were re-verified as already resolved and must not be re-carried:

| # | Item | Class | Owner lane | Blocks closure? |
|---|---|---|---|---|
| R1 | `save-game`, `verification-before-completion` (`global/skills/*`), `snow-kit` and `widget-kit` (`capabilities/mcp/*`) exist on disk but are absent from orchestrator `config/registry.yml` | Open decision (enroll or explicitly exclude) | Orchestrator registry lane (outside context-efficiency scope) | No — record as residual |
| R2 | `agent-route` exposure widening held: Skills master `meta.yml` `expose: cursor claude codex`; CPP manifest still `expose: [cursor]` (manifest PR was deliberately not merged) | Deliberate deferral (operator hold) | Orchestrator manifest / CPP-sync lane | No — record as residual with named follow-up |
| R3 | `skill-creator` `.cpp` zero-link false-positive (program-v2 D-04 §2.9 item 4) | **Verified resolved** — live `zero-link global skill-creator` = OK (exit 0); the `.cpp` token is a file-extension literal the reconciled scanner accepts | Orchestrator (already reconciled) | No — resolved |
| R4 | Non-description payload drift in `local-jobs`, `subagent-orchestration`, and extra `agent-route`/`swarm` files (program-v2 D-04 §2.9 items 1–2) | **Verified resolved** — the Option-B registry-wide D-04 sync vendored all 15 payloads; D-04 M3 consistency reported all 27 enrolled capabilities byte-OK | Orchestrator (already synced) | No — resolved |
| R5 | Merged reduction plans still labeled `DRAFT`: Dev `context-efficiency-s01-...-v1.md` and its index row; Skills `docs/plans/README.md` S-02 row; Dev D-01 plan header | Documentation lifecycle lag (C-03) | Dev + Skills owners | No — handled by C-03 |

Only R1, R2, and R5 remain open; none is a P0/P1. R1 and R2 are recorded as residuals in C-02; R5 is fixed by C-03.

### 2.5 C-03 stale-documentation candidates (implementation-caused)

| Owner repo | File:line | Why stale | Caused by |
|---|---|---|---|
| Orchestrator | `config/registry.yml:25-28` | Header comment calls `agent-route` “not meaningful as a cpp copy” and the flavor-2 snapshots “excluded until then,” but the live records (same file) show `agent-route` and the flavor-2 fleet all `state: enrolled` and vendored | Release 1.1 enrollment + D-04 vendoring |
| Dev | `context-efficiency-s01-dev-static-reduction-v1.md:4,12` + `_ops/plans/README.md` S-01 row; D-01 plan header | `Status: DRAFT` / “does not authorize implementation” on plans whose implementations are merged and `PASS`-evidenced | S-01, D-01 implementation |
| Skills | `docs/plans/README.md` S-02 row | S-02 index row still `DRAFT` though merged | S-02 implementation |

Reconnaissance found **no** stale doctrinal documentation in CPP, and no other Skills/Dev prose asserting a superseded budget or count outside immutable ACCEPTED plans. ACCEPTED plans and ADRs are immutable and out of C-03 scope.

## 3. Scope and non-goals

### 3.1 In scope after the named gates
- Re-run the merged D-01 `capture`/`validate` flow on fresh eligible client surfaces and prove projection parity for the program-reduced IDs (C-01).
- Assemble, validate, operator-review, and protected-merge one versioned `release2-closure-v1.json` final-evidence and built-versus-planned record (C-02).
- Per owner, update only implementation-stale documentation/policy and remove superseded process residue (C-03).

### 3.2 Out of scope
- No new reduction, description edit, exposure change, enrollment, exclusion, demotion, or registry item.
- No resolution of R1 (unenrolled capabilities) or R2 (held `agent-route` exposure) — both are recorded residuals with owner lanes outside this plan.
- No edit to any ACCEPTED plan, ADR, generated lock, `meta.yml`, manifest, or client-installed file.
- No re-opening, re-measuring, or re-freezing of Release 0/1/1.1 evidence.
- No new registry, daemon, installer channel, dependency, analytics store, or long-lived crawler.
- No GitHub Actions runner (hosted or self-hosted); Release 2 uses the existing runnerless verifier/reviewer path.

## 4. Design and closure mechanism

### 4.1 One existing mechanism per proof

| Release 2 proof | Mechanism | Pass rule |
|---|---|---|
| Client projection (C-01) | Merged D-01 `capability_discovery_inventory.py` `capture`/`validate` on each fresh eligible surface + a content-safe projection filter | Each eligible surface yields a `PASS` artifact; every program-reduced ID shows its reduced normalized count and unchanged identity/exposure/eligibility vs. the D-01 baseline; each ineligible surface cites a current product constraint |
| Final evidence (C-02) | New minimal `release2_closure.py` assemble/validate (reusing D-01 canonical-JSON + content-safety helpers) + operator closure review + protected merge | Canonical, content-safe `release2-closure-v1.json` whose cited refs all resolve; no unresolved P0/P1; protected-merged |
| Owner docs (C-03) | Per-owner governed doc/comment edit + that repo’s `doc-warden`/governance | Only implementation-stale bytes change; owner governance green; no duplicate authority |

### 4.2 C-01 — fresh-client projection matrix

C-01 reuses the merged D-01 tool unchanged. For each surface it (a) captures the client discovery catalog on a *fresh* session, (b) validates a `PASS` inventory artifact, and (c) filters to the program-reduced IDs and compares against the D-01 baseline (`capability-discovery-inventory-v1.json`), allowing only the reductions and separately-merged D-02/D-03/D-04/S-01 effects and rejecting any new change.

**Fresh-surface eligibility matrix.** Every row is either proven or cites a current product constraint; no row may be silently skipped, and current-chat evidence is never accepted.

| Surface | Default eligibility | Capture basis | Pass rule / product constraint |
|---|---|---|---|
| Cursor Desktop @ `DEV_ROOT` | **Eligible (primary proof)** | Fresh Cursor Desktop session whose workspace root equals `DEV_ROOT`; the agent writes `CURSOR_SESSION_CONTEXT_SOURCE` from the live always-applied context (rules + requestable rules + skills catalog), then runs `capture`+`validate` | PASS = valid `PASS` artifact + projection-filter parity |
| Cursor Cloud @ `DEV_ROOT` | Conditional | Fresh Cursor Cloud agent rooted at `DEV_ROOT` | PASS if it can emit a same-session `cursor-session-catalog/v1` at `DEV_ROOT`; else cite constraint (cloud session-context source unavailable / committed-hooks-only environment) |
| Cursor background @ `DEV_ROOT` | Conditional | Fresh background agent rooted at `DEV_ROOT` | PASS if capturable; else cite constraint |
| Cursor multi-root (with `DEV_ROOT`) | Conditional | Multi-root workspace including `DEV_ROOT` | PASS only if the capture adapter validates a single `workspace_root == DEV_ROOT`; else cite constraint (multi-root workspace-root ambiguity) |
| Claude | **Ineligible by default** | D-01 §4: no default capture; installed-root scans cannot prove exposure | Cite product constraint: no structured Claude discovery-catalog source. Becomes eligible only via operator scope decision naming a concrete catalog source (see Gate 1) |
| Codex | **Ineligible by default** | Same as Claude | Cite product constraint; eligible only via operator scope decision |

**Projection filter (content-safe).** For each `PASS` surface, restrict rows to the program-reduced IDs and prove:
- The 13 D-04-reconciled CPP payloads report the §2.3 reduced Skills counts and resolve to the current approved bytes.
- D-02 Skills-owned reduced descriptions and D-03 CPP-owned reduced descriptions report their merged reduced counts.
- Release-1/S-01 Dev-owned static rows reflect the reduced static context.
- Identity, exposure class, eligibility class, and client cohort are unchanged except for the reduced description digest/count.
- All other rows equal the D-01 baseline, allowing only separately-merged effects and rejecting any new Release-2-caused change.

Record only IDs, root/exposure/eligibility classes, digests, and normalized counts — never raw description text or private session content.

### 4.3 C-02 — versioned final evidence and built-versus-planned record

C-02 produces exactly one canonical, content-safe artifact `_ops/evidence/context-efficiency/release2-closure-v1.json` (schema `context-efficiency-release2-closure/v1`) assembled and validated by a small `_ops/context-measurement/release2_closure.py` (`assemble`/`validate`) that reuses the existing canonical-JSON conventions (UTF-8, SHA-256 digests, ASCII-safe IDs, sorted keys, `indent=2, sort_keys=True, ensure_ascii=True` + trailing newline) and content-safety rules, with one unit test. Required top-level fields:

| Field | Content |
|---|---|
| `schema` / `status` / `captured_at_utc` / `repository` / `dev_commit` / `dev_tree` | Canonical header; `status: PASS` only when every cited ref resolves and no P0/P1 is open |
| `owner_refs` | Exact `KleinPerkins/dev`, `KleinPerkins/skills`, `KleinPerkins/ecosystem-orchestrator`, `Affirm/card-platform-product`, `KleinPerkins/awa` commits |
| `release_evidence` | Pointers + SHA-256 to Release 0/1/1.1 artifacts and the D-04 CPP payload merges + orchestrator registry re-pin merge |
| `static_result` | Release-1 30%-target result copied content-safe from `release1-static-reduction-v1.json` |
| `catalog_result` | C-01 matrix: per-surface `{surface, eligible, discovery_source_class, catalog_sha256|null, result, product_constraint|null}` plus per-reduced-ID normalized counts/digests |
| `residuals` | R1, R2 (and any newly found), each `{id, class, owner_lane, status, follow_up_ref}`; content-safe |
| `rollback_refs` | Per-release/per-task rollback pointers (revert targets, orchestrator `rollback <id>` anchors) |
| `built_versus_planned` | Per program-v2 milestone/task (M-00–M-04, E-01–E-09, S-01–S-04, D-01–D-04, C-01–C-03): `{planned, built, evidence_ref}` |
| `content_safety` / `no_unresolved_p0_p1` | Attestations: no raw descriptions/source; boolean + enumerated open items with severity (must contain no P0/P1) |

The record enumerates the C-03 documentation cleanups as remaining closure tasks with owner lanes rather than blocking on them: it is the final *evidence* record (merged in M2), while program closure is declared only after C-03 lands (M3). It is validated, operator-reviewed, and protected-merged, never edited in place after acceptance; a successor version supersedes it.

### 4.4 C-03 — per-owner documentation closure

C-03 is per owner and runs after that owner’s last implementation; program closure waits for all applicable owners. Each owner uses its own governed path and touches only implementation-stale bytes.

| Owner | Governed action | Path |
|---|---|---|
| Orchestrator | Rewrite the stale `registry.yml:25-28` header comment to match live enrolled/vendored state | orchestrator Regime A PR |
| Dev | Reconcile the lifecycle labels of the merged S-01 and D-01 plans + their index rows to their post-merge state (per the plans README convention) | Dev governed PR |
| Skills | Reconcile the S-02 index-row lifecycle label | Skills governed PR |

Stop conditions: no duplicate authority, no unrelated documentation cleanup, no edit to an ACCEPTED plan/ADR or generated artifact.

## 5. Milestones

### M0 — Preflight and live re-verification
- Fetch Dev, Skills, orchestrator, CPP, and AWA origins; record current `origin/main`.
- Re-verify the three Release 0/1/1.1 evidence artifacts exist unchanged with their §2.2 statuses; confirm Releases 0/1/1.1 complete.
- Re-confirm the §2.4 residual classification live (including re-running `zero-link global skill-creator`).
- Confirm the Gate-1 scope decision (Claude/Codex catalog inclusion and the fresh-surface capture owner) is recorded before any capture.
- **DoD:** current refs and content-safe evidence support the closure lane; no mutation has occurred.

### M1 — C-01 fresh-client projection matrix
- For each eligible surface, capture on a fresh session and `validate` a `PASS` artifact; apply the §4.2 projection filter.
- For each ineligible surface, record the specific current product constraint.
- **DoD:** every matrix row is proven or product-constrained; projection parity holds for all program-reduced IDs; no current-chat evidence used.

### M2 — C-02 final evidence and closure review
- Implement the minimal `release2_closure.py` assemble/validate + test; assemble `release2-closure-v1.json` from M0/M1 outputs; validate content-safety and ref resolution.
- Present the artifact for operator closure review (Gate 2).
- After GO, protected-merge through the runnerless verifier/reviewer path; do not arm auto-merge manually.
- **DoD:** the versioned final-evidence/built-versus-planned record is merged with no unresolved P0/P1.

### M3 — C-03 documentation closure and program close
- Land each owner’s C-03 cleanup through its own governed path and GO.
- Once all applicable owners are merged, record program closure against the §10 completion criteria.
- **DoD:** all implementation-stale docs reconciled; owner governance green; the program meets every §10 completion criterion.

## 6. Operator gates

| Gate | Authority required | Forbidden without it |
|---|---|---|
| 1 — Plan acceptance | Operator accepts this DRAFT plan; names the Claude/Codex catalog scope (default: excluded, product-constrained) and confirms the fresh-surface capture owner | Any C-01 capture beyond a content-safe dry-run, any evidence assembly, any C-03 edit |
| 2 — C-02 closure review | Explicit operator review of the assembled `release2-closure-v1.json`, bound to current refs and the C-01 matrix result | `release2-closure-v1.json` protected merge and program-closure declaration |
| C-03 per-owner GOs | Each owner repo’s own local plan/GO | That owner’s documentation edit |

No gate implies the next. A changed ref, evidence status, residual class, or surface result returns to M0.

## 7. Acceptance criteria

### 7.1 This planning PR
- Status remains `DRAFT`; the plan is indexed once as DRAFT in `_ops/plans/README.md`.
- The diff contains only this plan and `_ops/plans/README.md`.
- The authoring baseline uses live-verified owner refs and evidence statuses.
- `doc-warden`, `doc-warden-verify.sh --sandbox`, `git diff --check`, and Bugbot have no unresolved in-scope finding.
- The PR is unarmed and unmerged.

### 7.2 Later Release 2 completion
- Every C-01 matrix surface is proven or cites a current product constraint; projection parity holds for all program-reduced IDs; no current-chat evidence is used.
- `release2-closure-v1.json` is canonical, content-safe, cites resolving refs, records R1/R2 residuals and the built-versus-planned map, and is protected-merged with no unresolved P0/P1.
- Each applicable owner’s C-03 cleanup is merged through its own governed path.
- The program satisfies every `context-efficiency-program-v2.md` §10 completion criterion.

## 8. Verification commands

### 8.1 Preflight (M0)
```bash
set -euo pipefail
DEV_ROOT="$HOME/dev"; SKILLS_ROOT="$HOME/dev/capabilities/skills"
ORCH_ROOT="$HOME/dev/personal/ecosystem-orchestrator"; CPP_ROOT="$HOME/dev/affirm/src/card-platform-product"
AWA_ROOT="$HOME/dev/capabilities/awa"
for r in "$DEV_ROOT" "$SKILLS_ROOT" "$ORCH_ROOT" "$CPP_ROOT" "$AWA_ROOT"; do
  git -C "$r" fetch --prune origin main
  git -C "$r" rev-parse --short origin/main
done
for f in static-context-manifest-v1 release1-static-reduction-v1 capability-discovery-inventory-v1; do
  python3 -c "import json;d=json.load(open('$DEV_ROOT/_ops/evidence/context-efficiency/$f.json'));print('$f',d.get('schema'),d.get('status'))"
done
( cd "$ORCH_ROOT" && bin/orchestrator.sh zero-link global "$SKILLS_ROOT/global/skills/skill-creator" )
```

### 8.2 C-01 matrix (M1) — per eligible surface, fresh session rooted at `DEV_ROOT`
```bash
: "${CURSOR_SESSION_CONTEXT_SOURCE:?written by the fresh in-session capture pre-step, umask 077, outside the checkout}"
: "${C01_CANDIDATE:?absolute temp path outside the checkout}"
PYTHONDONTWRITEBYTECODE=1 python3 _ops/context-measurement/capability_discovery_inventory.py capture \
  --dev-root "$DEV_ROOT" --skills-root "$SKILLS_ROOT" --cpp-root "$CPP_ROOT" --awa-root "$AWA_ROOT" \
  --cursor-session-source "$CURSOR_SESSION_CONTEXT_SOURCE" --out "$C01_CANDIDATE"
PYTHONDONTWRITEBYTECODE=1 python3 _ops/context-measurement/capability_discovery_inventory.py validate "$C01_CANDIDATE"
# then run the content-safe projection filter comparing $C01_CANDIDATE rows for the reduced IDs
# against _ops/evidence/context-efficiency/capability-discovery-inventory-v1.json
```

### 8.3 C-02 evidence (M2)
```bash
: "${R2_CANDIDATE:?absolute temp path outside the checkout}"
PYTHONDONTWRITEBYTECODE=1 python3 _ops/context-measurement/release2_closure.py assemble --out "$R2_CANDIDATE" # + inputs
PYTHONDONTWRITEBYTECODE=1 python3 _ops/context-measurement/release2_closure.py validate "$R2_CANDIDATE"
python3 -m unittest discover _ops/context-measurement -p 'test_release2_closure.py'
cp "$R2_CANDIDATE" _ops/evidence/context-efficiency/release2-closure-v1.json
```

### 8.4 Plan/PR hygiene (all PRs)
```bash
"$HOME/dev/_ops/bin/doc-warden.sh" check "$(git rev-parse --show-toplevel)"
bash "$HOME/dev/_ops/checks/doc-warden-verify.sh" --sandbox
git diff --check
git diff --name-status origin/main...HEAD
git status --short --branch
```

The plan PR changed-file set is exactly:
```text
_ops/plans/README.md
_ops/plans/context-efficiency-release2-closure-v1.md
```

## 9. Rollout and rollback

Roll out only in this order: (1) accept this plan and resolve Gate 1; (2) run M0; (3) run the M1 matrix on fresh surfaces; (4) build/validate the C-02 evidence; (5) obtain Gate 2 and protected-merge the evidence; (6) land each owner’s C-03; (7) declare program closure against §10.

Rollback:
- Before this plan is accepted: close the DRAFT PR and delete the branch.
- Before the C-02 evidence merge: discard the candidate; nothing is authoritative.
- After the C-02 merge: never edit it in place; supersede with a new accepted plan/version.
- For a C-03 doc edit: ordinary governed revert in the owning repo.

## 10. Risks and stop conditions

| Risk | Control / stop |
|---|---|
| Current-chat or cached client state masquerades as fresh proof | C-01 requires a fresh session and forbids current-chat evidence; installed-file presence is never exposure proof |
| Claude/Codex included without a real catalog source | Default them ineligible with a cited product constraint; include only after an explicit Gate 1 scope decision names a concrete catalog source |
| Evidence claims a resolved item that is actually open (or vice-versa) | M0 re-verifies every residual live (including `skill-creator` zero-link) before assembly |
| A recorded residual is silently “fixed” outside its owner lane | R1/R2 are recorded only; resolution is out of scope and belongs to their owner lanes |
| C-03 drifts into unrelated cleanup or duplicate authority | Touch only §2.5 implementation-stale bytes; ACCEPTED plans/ADRs are immutable |
| Program-v2 stale snapshot is mistaken for current state | Bind live refs in §2.2; M0 re-verifies |
| Partial closure declared complete | Program closure waits for the merged C-02 evidence and all applicable C-03 owners |

Stop immediately on: a dirty/unknown owner root, a changed evidence status, an unknown or reclassified residual, a surface that can neither be proven nor product-constrained, any raw description/private-content leak, a missing named GO, or an unproved rollback.

## 11. Zero-context executor pickup

### Repositories and identities
| Role | Path | Remote / identity |
|---|---|---|
| Program, evidence, this plan | `~/dev` | `KleinPerkins/dev`; local `KleinPerkins <49759187+KleinPerkins@users.noreply.github.com>`; umbrella root is worktree-excluded (author in the primary tree on a fresh branch) |
| Skills owner source | `~/dev/capabilities/skills` | `KleinPerkins/skills` |
| Orchestrator (sanctioned edge) | `~/dev/personal/ecosystem-orchestrator` | `KleinPerkins/ecosystem-orchestrator` |
| CPP consumer | `~/dev/affirm/src/card-platform-product` | `Affirm/card-platform-product`; separately governed |

The C-01 Cursor capture must run in a fresh Cursor session whose workspace root equals `DEV_ROOT` (`~/dev`); an orchestrator or other worktree cannot produce a valid `DEV_ROOT` capture. Set `DEV_SESSION_ID` before any Dev commit. Never update git config, skip hooks, push to `main`, force-push, mark ready, arm auto-merge, or merge.

### Ordered execution
Execute the §5 milestones behind the §6 gates in the §9 rollout order: **Gate 1** (accept plan + record the Claude/Codex scope and capture owner) → **M0** preflight (stop if any ref/evidence/residual disagrees with §2) → **M1** matrix on fresh surfaces (prove or product-constrain every row) → **C-02** build + **Gate 2** + protected-merge → **C-03** owner cleanups → declare program closure only once C-02 is merged and every applicable C-03 owner is done. Before starting, read this plan, `context-efficiency-program-v2.md` Release 2 + §10, the D-01 tool contract, `_ops/plans/README.md`, and each owner repo’s policy.

No later step infers a gate from an earlier approval. If a session ends, the next executor restarts at origin-first M0.
