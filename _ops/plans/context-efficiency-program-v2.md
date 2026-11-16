# Context Efficiency Program v2 — corrected execution handoff

**Version:** v2
**Status:** ACCEPTED — 2026-08-16
**Date:** 2026-08-16
**Owning repository:** `KleinPerkins/dev` (`~/dev`)
**Owner:** Laurence Duggan
**Plan-type:** standard
**Review provenance:** Live-main/GitHub verification of Dev PRs #264/#269/#270, exact-head defect probes, actual runnerless recipe/lock/Check-API inspection, accepted owner-plan and implementation-surface inspection across Skills/CPP/AWA, independent final review, and fresh zero-context reader testing.
**Scope:** `~/dev`, `KleinPerkins/skills`, `Affirm/card-platform-product`, `KleinPerkins/awa`, installed client projections, and the private operator gate
**Supersedes:** [Context Efficiency Program v1](context-efficiency-program-v1.md), which remains byte-identical history
**Governing decision:** accepted [ADR 0005](../adr/0005-harden-context-measurement-before-e09.md)
**Operator acceptance:** “Proceed with recommended plan, first step being the corrected ADR and updated plan … Put all important findings and instructions on disk within the context of an accepted doc-warden artifact.”

This status accepts the documentation and sequence. It does **not** authorize implementation, machine-local writes, release publication, E-07 private-data access, E-09 freezing, merge bypass, or manual/agent-armed auto-merge. Each implementation task below still requires its named repository and operator gates.

**Changelog**
- v2 (2026-08-16) — Correct the landed measurement contract, bind exact remote coverage and durable dogfood evidence, record verified release state, and provide a zero-context handoff from measurement correction through E-09 and the preserved Releases 1, 1.1, and 2.

## 1. Goal

Produce a trustworthy, content-safe denominator before removing any static agent context. The immediate step is one corrective Dev implementation PR for the already-landed `kp-context-measurement` tool. The broader program then fixes source-owned projections in their own repositories, proves exact merged artifacts, treats private learned data separately, and freezes E-09 last.

Success means:

1. the measurement tool has one closed v2 wire contract with canonical projection-ID ordering and controlled exits `0/2/3/4`;
2. the exact-head runnerless Dev job demonstrably runs its focused suite;
3. E-01/E-03, E-02, and E-04 are implemented under their accepted owner plans;
4. the E-04 release is pinned into Skills (E-05), then installed through Dev’s thin host overlay (E-06);
5. E-07 runs only after a new explicit private operator authorization;
6. E-08 runs only if valid E-07 evidence reproduces a code defect; and
7. E-09 freezes the seven projected payloads only after every applicable prerequisite is green; and
8. Releases 1, 1.1, and 2 then deliver the accepted static reduction, capability-discovery reduction, fresh-client proof, and program closure work.

## 2. Authoritative baseline

### 2.1 Dev

| Authority/evidence | Live binding |
|---|---|
| Repository | `KleinPerkins/dev` |
| Live main inspected | `28bfd06093d4fed84d2862f52aac2be8a3fa812b` |
| Accepted v1 program/ADR PR | [#264](https://github.com/KleinPerkins/dev/pull/264), head `45d181c36f39f97be925a9cb6b855b144584c9c5`, squash `0818be2f3beb0bfafaa17abd6250e780f87a19a1`, merged `2026-08-15T23:50:52Z` |
| Accepted v1 tooling-plan PR | [#269](https://github.com/KleinPerkins/dev/pull/269), head `724a2d401dc8237137104dea0f23cbbcf04995b0`, squash `47308080f9a6fb82275a557434638b9d4bf3c8e2`, merged `2026-08-16T10:03:41Z` |
| Tooling implementation PR | [#270](https://github.com/KleinPerkins/dev/pull/270), head `39f217939598af6583cba65cbce415eed5a1ac99`, squash `28bfd06093d4fed84d2862f52aac2be8a3fa812b`, merged `2026-08-16T23:15:00Z` |
| PR #270 checks | five completed/successful Check Runs; no review, comment, or auto-merge record |
| Accepted historical decision | `_ops/adr/0004-optimize-context-projections-without-moving-authority.md` |
| Accepted historical program | `_ops/plans/context-efficiency-program-v1.md` |
| Accepted historical tool plan | `_ops/plans/kp-context-measurement-v1-tooling-v1.md` |
| Active decision/program | ADR 0005 + this v2 plan |
| Current tool | `_ops/context-measurement/kp_context_measure.py` |
| Current tests | `_ops/context-measurement/test_kp_context_measure.py`; 16 tests on the inspected head |
| Current remote recipe | `.github/pr-recipe.json`, job `repo.dev.m3-verify` invokes `bash _ops/checks/doc-warden-verify.sh --sandbox` |
| Current Check visibility | exact Check name `pr-automation / job:repo.dev.m3-verify`; GitHub Check API exposes conclusion/head SHA and fixed summary but `output.text` is `null`, so no remote test stdout/count is retrievable |
| Current recipe currency | read-only v3 `plan` reports `phase=current`, `mutated=false`, lock validated/current |

The retained qualified controller release used only to verify recipe currency was:

```text
manifest:
~/.local/state/pr-automation-controller/releases/sha256-70d664ac78f1483d1008907f8f8eeba96649b28a227349b16b699d93c2bd1d51/manifest.json
version: 0.8.0
commit: 75ff5b83aa3d2dcd378f4623099edab8f871f1b9
lock-compiler sha256:
cfecfc39316637907e959b3dd0d360395dfa7fe3d880f8aa8c95d2ec5b9cfb4a
```

Do not treat that machine path as timeless. Re-verify it before use and stop if it is absent, unqualified, or differs from current central authority.

```bash
RELEASE_MANIFEST="$HOME/.local/state/pr-automation-controller/releases/sha256-70d664ac78f1483d1008907f8f8eeba96649b28a227349b16b699d93c2bd1d51/manifest.json"
LOCK_COMPILER="${RELEASE_MANIFEST%/manifest.json}/lock-compiler"
python3 "$HOME/dev/personal/pr-automation-controller/scripts/retain-qualified-release.py" \
  verify --manifest "$RELEASE_MANIFEST"
_ops/bin/repo-baseline.sh profile pr-automation v3 plan \
  --repo KleinPerkins/dev \
  --coverage-mode local \
  --profile-id stdlib-shell.v1 \
  --target-root "$(git rev-parse --show-toplevel)" \
  --lock-compiler "$LOCK_COMPILER" \
  --release-manifest "$RELEASE_MANIFEST"
```

Required result: qualified release `0.8.0`; `phase=current`;
`mutated=false`; lock validation/current `true`. This is read-only verification, not authority to run `sync` or change the recipe.

### 2.2 Owner-repository plans

| Work | Accepted authority | Accepted merge | Live status rechecked 2026-08-16 |
|---|---|---|---|
| E-01 Skills bootstrap projection | [`context-efficiency-e01-durable-skills-source-v1.md`](https://github.com/KleinPerkins/skills/blob/main/docs/plans/context-efficiency-e01-durable-skills-source-v1.md), [PR #139](https://github.com/KleinPerkins/skills/pull/139) | `da3463f9cf7e201d334c95412a75990bd2157733` | Accepted plan; Skills main still equals that plan merge; not implemented |
| E-03 Skills description eligibility | [`context-efficiency-e03-description-eligibility-v1.md`](https://github.com/KleinPerkins/skills/blob/main/docs/plans/context-efficiency-e03-description-eligibility-v1.md), [PR #139](https://github.com/KleinPerkins/skills/pull/139) | `da3463f9cf7e201d334c95412a75990bd2157733` | Accepted plan; Skills main still equals that plan merge; not implemented |
| E-02 CPP durable projection | [`durable-cpp-skill-projections-v1.md`](https://github.com/Affirm/card-platform-product/blob/main/_ops/plans/durable-cpp-skill-projections-v1.md), [PR #681](https://github.com/Affirm/card-platform-product/pull/681) | `466d641efe4a485fdbf7a642926ee992e125567f` | Accepted plan; required helper remains absent on live main `de07f2e811d258e64a0672b8601224e1ab100d91`; not implemented |
| E-04 AWA external hook owner | [`external-hook-owner-contract-v1.md`](https://github.com/KleinPerkins/awa/blob/main/docs/plans/external-hook-owner-contract-v1.md), [PR #111](https://github.com/KleinPerkins/awa/pull/111) | `09d4f0991118b245ccce23291821f5d4dbd4ddd4` | Accepted plan; AWA main still equals that plan merge, `awa-hook-owner/v1` is absent, and candidate `v1.5.2` is unpublished |

Latest published AWA tag observed is `v1.5.1`, targeting
`f4b3c9b85ea1cce83d00ab9eb9f26bf3be900342`. The Skills GCB currently pins that same commit. E-04 therefore has no releasable implementation to consume.

Recheck these point-in-time authorities before each owner task:

```bash
gh pr view 139 --repo KleinPerkins/skills \
  --json state,mergedAt,mergeCommit,headRefOid
gh pr view 681 --repo Affirm/card-platform-product \
  --json state,mergedAt,mergeCommit,headRefOid
gh pr view 111 --repo KleinPerkins/awa \
  --json state,mergedAt,mergeCommit,headRefOid
gh api repos/KleinPerkins/skills/commits/main --jq '.sha'
gh api repos/Affirm/card-platform-product/commits/main --jq '.sha'
gh api repos/KleinPerkins/awa/commits/main --jq '.sha'
gh api repos/KleinPerkins/awa/releases/latest \
  --jq '{tag_name,target_commitish,draft,prerelease,published_at}'
gh api repos/KleinPerkins/awa/git/ref/tags/v1.5.1 --jq '.object'
```

After creating each repository’s safe writer tree, read that repository’s `AGENTS.md`/policy and the full accepted child plan from its refreshed default branch. The summaries below do not override those frozen child authorities.

### 2.3 Status vocabulary

Use the accepted program’s Release 0 / Release 1 / Release 1.1 / Release 2 and task IDs E-01–E-09. Historical “Stage 1/2/3” shorthand is not authority.

Current program classification:

```text
DOCUMENTATION_V2_ACCEPTED
MEASUREMENT_V1_LANDED_NOT_E09_SAFE
E01_E02_E03_E04_PLANNED_NOT_IMPLEMENTED
E05_E06_BLOCKED_BY_E04_RELEASE
E07_PRIVATE_OPERATOR_AUTHORIZATION_REQUIRED
E08_CONDITIONAL_ONLY
E09_UNFROZEN
RELEASES_1_1_1_2_NOT_STARTED
```

Terms used below:

- **AWA** — Agent Worktree Automation (`KleinPerkins/awa`).
- **CPP** — `Affirm/card-platform-product`.
- **LD** — Laurence Duggan, the named CPP owner/operator.
- **GCB** — Global Capability Binding, the Skills shelf pointer to an exact standalone release.
- **SSP** — Standalone System Package, the independently released AWA product.
- **WF1 / lockkit** — Skills ecosystem enrollment/metadata-lock lifecycle; generated lock material is changed only through its normal lockkit commands.

## 3. Architecture and invariants

### 3.1 Authority remains distributed

- Skills owns reusable global/local capability projection and bootstrap/update behavior.
- CPP owns its durable projection semantics and CPP-native repair/doctor path.
- AWA owns generic finish lifecycle and machine-local finish runtime behavior.
- Dev owns only its host overlay, policy literals, installed AWA wiring, and measurement evidence.
- The private operator gate owns learned-data observation and authorization.
- The E-09 manifest is evidence, never source authority.

### 3.2 Hard invariants

1. Keep accepted v1 artifacts byte-identical. Correct with this plan and ADR 0005.
2. Before mutation in a governed repo, run that repo’s `_ops/bin/dev-worktree.sh ensure` when present and follow its printed `move_agent_to_root` instruction. CPP follows its own governed session-start path and exclusion.
3. One writer per tree. Parallel work uses distinct worktrees and must not share an index.
4. Establish `origin/main` from the remote; never infer live state from a stale checkout.
5. No generated-memory mutation during documentation, M-01–M-04, E-01–E-06,
   or E-09 measurement. E-07 may write only the explicitly authorized private
   generated-memory target under its backup/restore gate. S-02 may create a
   generated-memory candidate only under its separately accepted Skills plan
   and exact private machine GO. No other task inherits either authorization.
6. No new registry, ledger, daemon, service, dependency, or analytics store.
7. No E-09 payload reduction/freeze until the final gate.
8. No E-07 access without a new explicit operator GO naming the private candidate and machine.
9. E-08 is dormant unless valid E-07 evidence reproduces a source-code defect.
10. No agent calls `gh pr merge --auto`, enables/disables native auto-merge, manually merges, approves, bypasses checks, force-pushes, or pushes directly to `main`.
11. Protected-path owner/admin merge is the durable acceptance gate even when a document carries operator-accepted status.
12. Measurement receipts bind only the closed workload/algorithm identity in ADR 0005. Implementation evidence reports additionally bind repository, exact commit/tree, changed-file hashes, command, environment class, and result. The E-09 static manifest binds owner refs/blobs to the measurement receipt.
13. Fail closed on authority drift, missing evidence, ambiguous private scope, or material baseline change.

### 3.3 Zero-context handoff boundary

This plan is the complete program router and sequencing authority; it does not
copy immutable owner-repository child plans. For E-01/E-03, E-02, and E-04,
the linked accepted child plan is a required one-hop input. The first action in
that owner task is to fetch the current default branch, verify the plan merge
from §2.2 is still an ancestor, and read that repository’s `AGENTS.md`, policy,
and full child plan before mutation. If any link/plan is unavailable or its
authority changed, stop. The files/tests/commands below are pickup summaries,
not permission to skip or contradict the child authority.

### 3.4 Non-goals

- changing the accepted character/word-counting algorithm;
- preserving or migrating v1 measurement receipts;
- changing source ownership or vendoring boundaries;
- moving learned/private data into tracked repositories;
- generalizing the measurement tool beyond this program;
- adding performance SLAs, streaming, caching, parallel measurement, JSON Schema dependencies, or network calls;
- repairing unrelated doc-warden/profile prerequisite failures in the measurement correction PR;
- hand-vendoring CPP capability bytes;
- activating a new AWA release before E-04 is implemented and qualified; or
- treating synthetic dogfood as the authoritative seven-payload baseline.

## 4. Material findings

| Severity | Finding | Implication |
|---|---|---|
| P1 | Parent authority requires projection-ID order; v1 child plan/code preserve manifest order. | Receipts are caller-order-dependent and cannot freeze E-09. |
| P1 | `projections:[null]` raises `AttributeError` and exits `1`. | Caller input escapes the documented `0/2/3/4` contract. |
| P1 | Malformed receipts can raise `KeyError` and exit `1`. | Comparison is not a safe validation boundary. |
| P1 | Unknown `select` keys and values are copied into receipts. | Content-safety claim is false for open input. |
| P1 | CLI grammar failures use `argparse` exit `2`, colliding with blocked measurement. | Exit classes are not semantically stable. |
| P1 | PR #270’s green Checks did not execute the focused measurement suite. | Remote exact-head coverage is unproven. |
| P1 | The live recipe/lock invoke `doc-warden-verify.sh --sandbox`, not runnerless profile `test.sh`; Check API `output.text` is null. | Wire the focused suite into the actual sandbox entry point and prove execution from exact-head bindings, not inaccessible stdout. |
| P1 | An earlier v2 draft stopped at E-09. | E-09 is only the Release 0 denominator; accepted Releases 1, 1.1, and 2 remain required. |
| P1 | Synthetic dogfood had no mandatory tracked handoff. | Later owner work could not prove its prerequisite after local/PR context disappeared. |
| P2 | Equal and overlapping region markers can succeed. | Region identity and selected bytes are ambiguous. |
| P2 | Receipt validation is open/shallow and lacks descriptor compatibility checks. | Different workloads can be compared as if identical. |
| P2 | Accepted v1 plan/ADR retain pre-acceptance draft/governance wording. | Readers can misclassify current authority. |
| P2 | `make verify-ci` failed identically on isolated base and head for pre-existing doc-warden/profile fixtures. | Full gate is not green, but the failure is not caused by PR #270; preserve differential evidence. |
| P3 | Valid-input determinism, working-directory independence, and input-file immutability passed. | Reuse the core counting functions; do not rewrite the tool wholesale. |
| P3 | The runnerless recipe already routes a dedicated Dev job through the tracked doc-warden sandbox entry point. | Add focused execution to the actual entry point; leave recipe, lock, profile tests, and controller unchanged. |

## 5. Execution graph

Release 0 and program graph:

```text
Docs v2 protected merge (M-00)
  -> Dev corrective tests + remote job wiring + implementation
  -> Dev corrective protected merge
  -> bounded synthetic correction dogfood + protected evidence merge
       ├─ E-01 then E-03 in Skills (shared file; serial integration) ─┐
       ├─ E-02 in CPP ───────────────────────────────────────────────┤
       └─ E-04 in AWA -> qualified v1.5.2 release ───────────────────┤
                                                                    ↓
     accept E-05 plan -> E-05 Skills GCB pin
  -> accept E-06 plan -> E-06 Dev host-overlay install/receipt
  -> explicit private E-07 GO
  -> E-07 learned projection
  -> accept/execute E-08 plan only if valid code defect
  -> E-09 freeze last
  -> Release 1: S-01 + S-02 -> conditional S-03 -> S-04
  -> Release 1.1: D-01 -> D-02 + D-03 -> D-04
  -> Release 2: C-01 -> C-02 + owner-local C-03
```

After M-04, E-02 and E-04 may run in parallel with the Skills lane in their own repositories. E-01 and E-03 may be developed in separate worktrees, but both modify `.github/scripts/verify-skills.sh`; merge/integration is serial, with E-03 rebased and re-proven after E-01. E-05 waits for both the qualified E-04 release and merged E-01/E-03 Skills main. E-09 waits for E-02 and E-06, private E-07 completion, and either a merged E-08 fix or an explicit `E08_NOT_ACTIVATED` result. Release 1 starts only from the protected-merged E-09 denominator; Release 1.1 starts only after Release 1 evidence is stable; Release 2 closes the program only after both reduction releases are merged and reconciled.

## 6. Machine/executor pickup

### 6.1 Preflight: establish reality

Start in the currently open Dev checkout; do not assume it is the primary tree. These commands make no local write:

```bash
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
git status --short --branch
git remote get-url origin
git rev-parse HEAD
gh api repos/KleinPerkins/dev/commits/main --jq '.sha'
gh pr view 264 --repo KleinPerkins/dev --json state,mergedAt,mergeCommit
gh pr view 269 --repo KleinPerkins/dev --json state,mergedAt,mergeCommit
gh pr view 270 --repo KleinPerkins/dev --json state,mergedAt,headRefOid,mergeCommit,statusCheckRollup
```

The origin URL must resolve to `KleinPerkins/dev`. The last pre-M-00 authoring baseline is
`28bfd06093d4fed84d2862f52aac2be8a3fa812b`; it is evidence, not the future implementation base.

### 6.2 Create the safe writer tree

Before any mutation:

```bash
_ops/bin/dev-worktree.sh ensure
```

If it prints `move_agent_to_root`, discover the Cursor app-control schema and invoke that exact root move before editing, setup, commit, push, or PR creation. If it refuses because the primary tree is dirty, stop and report the existing work; do not clean or relocate it silently.

From the safe workspace:

```bash
git fetch origin main
DOC_COMMIT="$(git log -1 --format=%H origin/main -- \
  _ops/adr/0005-harden-context-measurement-before-e09.md \
  _ops/plans/context-efficiency-program-v2.md)"
test -n "$DOC_COMMIT"
git cat-file -e \
  "$DOC_COMMIT:_ops/adr/0005-harden-context-measurement-before-e09.md"
git cat-file -e \
  "$DOC_COMMIT:_ops/plans/context-efficiency-program-v2.md"
gh api "repos/KleinPerkins/dev/commits/$DOC_COMMIT/pulls" \
  --jq '.[] | {number,state,merged_at,merge_commit_sha}'
git merge-base --is-ancestor "$DOC_COMMIT" origin/main
git diff --exit-code 28bfd06093d4fed84d2862f52aac2be8a3fa812b \
  "$DOC_COMMIT" -- \
  _ops/adr/0004-optimize-context-projections-without-moving-authority.md \
  _ops/plans/context-efficiency-program-v1.md \
  _ops/plans/kp-context-measurement-v1-tooling-v1.md
git switch -c fix/context-measurement-v2 origin/main
git status --short --branch
git config --get user.name
git config --get user.email
```

The commit→PR lookup must contain one merged protected-path PR whose merge SHA is on `origin/main`. If it does not, M-00 is not durably complete and implementation stops. Review every change from `28bfd…` through `origin/main`; stop on a material ADR, tool, test, remote-recipe, doc-warden, or PR-governance change. Required identity is `KleinPerkins <49759187+KleinPerkins@users.noreply.github.com>`.

### 6.3 First failing tests

Add a `TestContractV2` class to
`_ops/context-measurement/test_kp_context_measure.py`. Write these tests before production code:

| Test name | Minimal input | Required assertion |
|---|---|---|
| `test_manifest_order_is_canonical_projection_id_order` | valid v2 manifest ordered `z`, `a` | receipt order is `a`, `z` |
| `test_null_projection_is_usage_error_without_traceback` | `projections:[null]` | exit `3`; fixed diagnostic; no stdout/traceback |
| `test_unknown_select_field_is_rejected_without_value_echo` | full selector plus key `unexpected_payload` with sentinel value | exit `3`; sentinel absent from stdout/stderr |
| `test_missing_compare_argument_is_usage_error` | `compare --baseline x` | exit `3`, not `2` |
| `test_malformed_receipt_is_refused_without_traceback` | two `{}` receipt files | exit `4`; closed comparison refusal; no traceback |
| `test_v1_receipt_is_refused` | structurally valid historical v1 receipt | exit `4`; reason `UNSUPPORTED_RECEIPT_SCHEMA` |
| `test_equal_region_markers_are_usage_error` | same nonempty begin/end | exit `3` |
| `test_overlapping_region_markers_are_misordered` | begin `abc`, end `bcd`, content `abcd` | blocked receipt; exit `2`; `REGION_MISORDERED` |
| `test_repeated_overlapping_marker_is_ambiguous` | begin `aa`, end `Z`, content `aaaZ` | blocked receipt; exit `2`; `REGION_AMBIGUOUS` |
| `test_receipt_rejects_unknown_fields` | valid receipt plus one extra nested key | exit `4`; no key/value echo |
| `test_compare_refuses_descriptor_mismatch` | valid receipts with same IDs/counts but different path or marker digest | exit `4`; `PROJECTION_DESCRIPTOR_MISMATCH` |
| `test_valid_errors_use_only_public_exit_classes` | table of malformed manifest/receipt/CLI cases | observed exits are only `2`, `3`, or `4`; no traceback |

Add `TestCorrectionDogfood` to
`_ops/context-measurement/test_correction_dogfood.py` before the bounded helper:

| Test name | Minimal input | Required assertion |
|---|---|---|
| `test_run_is_atomic_and_closed` | fixed fixtures with one forced failure | no output on failure; canonical closed PASS output only after every probe passes |
| `test_validator_rejects_wrong_nested_types` | booleans substituted for exit integers and integers for booleans | exit `3`; fixed diagnostic; no traceback |
| `test_validator_rejects_contradictory_digests` | unequal run-A/run-B or pre/post digest pairs | exit `3` |
| `test_validator_checks_commit_tree_without_assert` | wrong tree under normal Python and `PYTHONOPTIMIZE=1` | exit `3` in both environments |

Run the expected-red slice:

```bash
cd _ops/context-measurement
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  test_kp_context_measure.TestContractV2
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  test_correction_dogfood.TestCorrectionDogfood
```

Retain the failing assertion names and exact head/tree in the PR evidence. If the tests unexpectedly pass, inspect whether live main already implements ADR 0005; do not weaken tests to manufacture red.

### 6.4 Evidence ledger

This frozen table is the program ledger; do not create another registry. Future executors append exact result rows to the relevant implementation PR body and gate report, not to this accepted plan.

| Evidence ID | Claim | Bound source/result |
|---|---|---|
| EV-001 | v1 program/ADR accepted | Dev PR #264; squash `0818be2f3beb0bfafaa17abd6250e780f87a19a1` |
| EV-002 | v1 tooling plan accepted | Dev PR #269; squash `47308080f9a6fb82275a557434638b9d4bf3c8e2` |
| EV-003 | v1 tool landed | Dev PR #270; head `39f217939598af6583cba65cbce415eed5a1ac99`; squash `28bfd06093d4fed84d2862f52aac2be8a3fa812b` |
| EV-004 | focused suite green on PR head | `16/16`, exit `0` |
| EV-005 | deterministic / cwd-independent / input immutable | passed exact-head probes; unchanged inode/mode/size/mtime/digest |
| EV-006 | ordering contradiction reproduced | input `z,a` emitted `z,a` |
| EV-007 | malformed input failure reproduced | null projection exited `1` with traceback |
| EV-008 | content-safety failure reproduced | unknown selector sentinel emitted |
| EV-009 | malformed receipt failure reproduced | compare exited `1` with traceback |
| EV-010 | marker ambiguity reproduced | equal and overlapping markers succeeded |
| EV-011 | remote coverage gap proven | live recipe/lock invoke `bash _ops/checks/doc-warden-verify.sh --sandbox`; no focused measurement command exists there and Check API output text is null |
| EV-012 | full-gate environmental baseline | isolated base/head `make verify-ci` fail identically on pre-existing doc-warden/profile fixtures; measurement stanza and doc-warden sandbox pass |
| EV-013 | child plans accepted/unimplemented | Skills #139 at `da3463f9…`, CPP #681 at `466d641e…`, AWA #111 at `09d4f099…`, plus live-file probes in §2.2 |
| EV-014 | E-09 not frozen | no authoritative v2 seven-payload receipt or accepted static-context manifest |
| EV-015 | retained clone has no unique tree payload | clean; HEAD tree `a37b899d773e34e55d94a2beead605d4c49ab366` equals PR #270 merge tree; other branch trees equal remote commits `47308080…`/`bddf4069…`; sole unreachable rollback-proof commit `6f75876d…` has tree `6def1e8e…`, equal to PR #269 merge tree |

### 6.5 Retained clone cleanup

Candidate:

```text
~/.local/share/kp-cm-clone-20260816-013850
```

Do not delete it during this documentation step. After M-00 is durably merged, recheck:

```bash
CLONE="$HOME/.local/share/kp-cm-clone-20260816-013850"
test -d "$CLONE/.git"
test -z "$(git -C "$CLONE" status --porcelain=v1)"
git -C "$CLONE" rev-parse HEAD HEAD^{tree}
git -C "$CLONE" for-each-ref \
  --format='%(refname) %(objectname) %(*objectname)' refs/heads refs/tags
git -C "$CLONE" fsck --no-reflogs --unreachable
gh api repos/KleinPerkins/dev/git/commits/28bfd06093d4fed84d2862f52aac2be8a3fa812b \
  --jq '.tree.sha'
gh api repos/KleinPerkins/dev/git/commits/47308080f9a6fb82275a557434638b9d4bf3c8e2 \
  --jq '.tree.sha'
gh api repos/KleinPerkins/dev/git/commits/bddf406918d830af9bfafefcaf7c3fc0a85606f8 \
  --jq '.tree.sha'
git -C "$CLONE" show -s --format='%H %T %P %s' \
  6f75876d5a911e9d1fb84d714b7b76d93f50cf5b
```

The expected tree equalities are recorded in EV-015. Commit ancestry is not the test because PRs #269/#270 were squash-merged. Classify the outcome as:

- `CLEANABLE_NO_UNIQUE_PAYLOAD` when status is clean, every ref/unreachable tree matches a named remote tree, and no new object appears;
- `RETAINED_WITH_REASON` for absent-path uncertainty, dirty state, a new ref/object, or unresolved tree mismatch.

Cleanup is not an M-01 blocker when the clone is `RETAINED_WITH_REASON`; never use it as the writer tree. For `CLEANABLE_NO_UNIQUE_PAYLOAD`, request an exact destructive GO naming this path. Only then run:

```bash
CLONE="$HOME/.local/share/kp-cm-clone-20260816-013850"
test "$CLONE" = "$HOME/.local/share/kp-cm-clone-20260816-013850"
test -d "$CLONE/.git"
test -z "$(git -C "$CLONE" status --porcelain=v1)"
rm -rf -- "$CLONE"
test ! -e "$CLONE"
```

No bundle is needed for the observed state because the sole unreachable commit has no unique tree payload. If the recheck finds a new object/tree, retain the entire clone; do not invent an incomplete bundle procedure.

## 7. Ordered work items

### M-00 — Merge this documentation authority

- **Root / owner:** `KleinPerkins/dev`; Laurence Duggan.
- **Dependencies:** none beyond current protected checks.
- **Files:** only ADR 0005, this plan, `_ops/adr/README.md`, and `_ops/plans/README.md`.
- **GO:** the operator acceptance quoted above authorizes the documents; protected owner/admin merge remains required.
- **Verify:**

```bash
_ops/bin/doc-warden.sh check .
bash _ops/checks/doc-warden-verify.sh --sandbox
bash _ops/checks/doc-warden-verify.sh
make worktree-verify
make verify-ci
git diff --cached --check
bash _ops/hooks/data-guard
git diff --cached --name-only
git diff --cached -- \
  _ops/adr/README.md \
  _ops/adr/0005-harden-context-measurement-before-e09.md \
  _ops/plans/README.md \
  _ops/plans/context-efficiency-program-v2.md
```

  If full verification is red, run the same command from a clean exact-base worktree and record the differential. The PR contains only the four named files. After push, read exact-head Checks with `gh api "repos/KleinPerkins/dev/commits/$(git rev-parse HEAD)/check-runs"`.
- **Evidence:** commit SHA, PR URL/head, check names/conclusions, merge SHA when owner merges.
- **Rollback:** revert the docs PR; runtime is unchanged.
- **Stop:** any accidental implementation/config/policy change, v1 byte drift, red exact-head check, or unauthorized merge path.

### M-01 — Add exact remote coverage and closed v2 tests

- **Root / owner:** Dev safe workspace; KleinPerkins/Laurence.
- **Dependencies:** M-00 merge proven by §6.2; live-main preflight complete; retained clone classified `CLEANABLE_NO_UNIQUE_PAYLOAD` or `RETAINED_WITH_REASON`.
- **GO:** a new implementation GO is required because this accepted plan authorizes sequence, not code mutation.
- **Expected files:**
  - `_ops/context-measurement/test_kp_context_measure.py`
  - `_ops/context-measurement/test_correction_dogfood.py`
  - `_ops/checks/doc-warden-verify.sh`
- **Interfaces:**
  - add the §6.3 red tests;
  - before editing, validate and inspect the actual remote bindings:

    ```bash
    RELEASE_DIR="$HOME/.local/state/pr-automation-controller/releases/sha256-70d664ac78f1483d1008907f8f8eeba96649b28a227349b16b699d93c2bd1d51"
    LOCK_COMPILER="$RELEASE_DIR/lock-compiler"
    PLAN_FILE="$(mktemp "${TMPDIR:-/tmp}/context-recipe-plan.XXXXXX")"
    trap 'rm -f "$PLAN_FILE"' EXIT
    python3 "$HOME/dev/personal/pr-automation-controller/scripts/retain-qualified-release.py" \
      verify --manifest "$RELEASE_DIR/manifest.json"
    _ops/bin/repo-baseline.sh profile pr-automation v3 plan \
      --repo KleinPerkins/dev \
      --coverage-mode local \
      --profile-id stdlib-shell.v1 \
      --target-root "$(git rev-parse --show-toplevel)" \
      --lock-compiler "$LOCK_COMPILER" \
      --release-manifest "$RELEASE_DIR/manifest.json" \
      >"$PLAN_FILE"
    python3 - "$PLAN_FILE" <<'PY'
    import json
    import sys

    def require(condition):
        if not condition:
            raise SystemExit("remote binding validation failed")

    expected = [
        "run-literal", "bash",
        "_ops/checks/doc-warden-verify.sh", "--sandbox",
    ]
    plan = json.load(open(sys.argv[1], encoding="utf-8"))
    recipe = json.load(open(".github/pr-recipe.json", encoding="utf-8"))
    lock = json.load(open(
        ".github/pr-automation.lock.json", encoding="utf-8"
    ))["payload"]
    require(plan["phase"] == "current")
    require(plan["mutated"] is False)
    require(plan["lock_currency"]["current"] is True)
    require(plan["lock_currency"]["artifact_validation"]["validated"] is True)
    require(recipe["custom_jobs"][0]["id"] == "repo.dev.m3-verify")
    require(recipe["custom_jobs"][0]["argv"] == expected)
    jobs = {item["runtime"]["id"]: item for item in lock["jobs"]}
    require(jobs["repo.dev.m3-verify"]["runtime"]["argv"] == expected)
    PY
    ```

    All commands must exit `0`; the lock compiler must still be the qualified
    retained release. This is read-only evidence, not recipe authority.
  - in `--sandbox` mode, run the focused suite unconditionally after the
    existing doc-warden assertions:

    ```bash
    (
      cd "$DEV_ROOT/_ops/context-measurement"
      PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
        test_kp_context_measure.py test_correction_dogfood.py
    )
    ```

  - make any nonzero focused-suite exit set the sandbox script’s existing
    failure result; prove the wiring bites by temporarily introducing one
    failing assertion, observing nonzero from
    `bash _ops/checks/doc-warden-verify.sh --sandbox`, then removing it;
  - retain the existing full and sandbox doc-warden behavior;
  - do not change `.github/pr-recipe.json`, `.github/pr-automation.lock.json`,
    `.github/pr-verification.json`, `.github/pr-automation.json`,
    `_ops/baseline/profiles/pr-automation/v3/test.sh`, profile assignments,
    controller pins, or rulesets.
- **Local red evidence:** new v2 tests fail for the reproduced reasons; existing 16 tests still describe v1 behavior and may be updated only where the accepted contract changed.
- **Remote evidence:** after implementation, prove all four bindings from ADR
  0005’s “actual remote Dev entry point” decision. The exact Check name is
  `pr-automation / job:repo.dev.m3-verify`. Do not claim remote stdout or a
  remote test count; Check API `output.text` is currently null.
- **Rollback:** revert the three M-01 files; no remote control-plane mutation occurred.
- **Stop:** if the live recipe/lock no longer invoke
  `bash _ops/checks/doc-warden-verify.sh --sandbox`, the lock is not current,
  the noexec/no-network sandbox cannot run the stdlib suite, or the change
  requires recipe/profile/controller authority. Supersede the plan before
  widening scope.

### M-02 — Implement the v2 wire contract

- **Root / owner:** same Dev safe workspace and implementation PR as M-01.
- **Dependencies:** M-01 expected-red evidence.
- **Expected files:**
  - `_ops/context-measurement/kp_context_measure.py`
  - `_ops/context-measurement/test_kp_context_measure.py`
  - `_ops/context-measurement/correction_dogfood.py`
  - `_ops/context-measurement/test_correction_dogfood.py`
  - `_ops/context-measurement/README.md`
  - `_ops/checks/doc-warden-verify.sh`
- **Files that remain unchanged:** accepted ADR/plan v1 artifacts, `verify-operating-model.sh` test stanza, `.github/pr-*.json`, CODEOWNERS, runnerless profile authority/config/schema/test files, package/dependency files, and every source outside this list.
- **Interfaces:**
  - keep counting primitives at `kp-context-measurement/v1`;
  - add closed validators for input v2, measurement receipt v2, and comparison v2;
  - sort unique ASCII-token projection IDs by ascending bytes;
  - canonical JSON remains `json.dumps(..., indent=2, sort_keys=True, ensure_ascii=True) + "\n"`;
  - replace raw `argparse` termination with controlled usage exit `3`;
  - validate both receipts fully before indexing;
  - enumerate overlapping marker occurrences and implement ADR 0005 precedence;
  - digest valid marker descriptors; never echo invalid keys/values or marker text;
  - catch expected `OSError`, `UnicodeError`, `json.JSONDecodeError`, and validation errors at the CLI boundary without catching programmer failures as successful receipts;
  - produce only exits `0/2/3/4` for external input.
  - add the bounded `correction_dogfood.py` interface:
    `run --tool PATH --implementation-root PATH --output PATH` and
    `validate --evidence PATH --implementation-root PATH`; no other verb,
    fixture override, free-form field, network, or tracked-write mode;
  - hardcode and test the M-04 fixture bytes/command matrix; `run` requires an
    absent output path, writes a same-directory temporary file, and atomically
    renames only after every expected exit, digest equality, stat equality,
    no-echo probe, and self-validation pass;
  - `validate` uses explicit conditionals, exact JSON types, canonical-byte
    comparison, run-receipt/pre-post digest equality, and local
    `git rev-parse COMMIT^{tree}` binding; it returns `0` or fixed exit `3`
    with no traceback/value echo even under `PYTHONOPTIMIZE=1`.
- **No dependency change:** use Python 3 stdlib only.
- **Pass command:**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  _ops/context-measurement/test_kp_context_measure.py -v
PYTHONDONTWRITEBYTECODE=1 python3 \
  _ops/context-measurement/test_correction_dogfood.py -v
PYTHONDONTWRITEBYTECODE=1 python3 -c \
  'import ast,pathlib; ast.parse(pathlib.Path("_ops/context-measurement/kp_context_measure.py").read_text(encoding="utf-8"))'
bash _ops/checks/doc-warden-verify.sh --sandbox
bash _ops/baseline/profiles/pr-automation/v3/test.sh
```

- **Evidence:** expected-red/green delta, deterministic receipt fixtures, fixed-error no-echo probes, exit-class matrix, source-file stat/digest before and after, and exact changed-file hashes.
- **Rollback:** governed revert to the pre-correction Dev commit; classify measurement as unavailable, not v1-authorized.
- **Stop:** any counting primitive must change, a third-party dependency is proposed, a valid v1 receipt must be preserved, content values appear in an error, or a valid external input reaches exit `1`.

### M-03 — Verify and deliver one corrective Dev PR

- **Root / owner:** same Dev safe workspace; protected owner/admin gate.
- **Dependencies:** M-02 green.
- **Exact local matrix:**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  _ops/context-measurement/test_kp_context_measure.py -v
PYTHONDONTWRITEBYTECODE=1 python3 \
  _ops/context-measurement/test_correction_dogfood.py -v
PYTHONDONTWRITEBYTECODE=1 python3 -c \
  'import ast,pathlib; ast.parse(pathlib.Path("_ops/context-measurement/kp_context_measure.py").read_text(encoding="utf-8"))'
bash _ops/baseline/profiles/pr-automation/v3/test.sh
_ops/bin/doc-warden.sh check .
bash _ops/checks/doc-warden-verify.sh --sandbox
bash _ops/checks/doc-warden-verify.sh
make worktree-verify
make verify-ci
git diff --check
git status --short --branch
```

- **Baseline differential:** if `make verify-ci` fails, run the same command from a clean worktree at the exact merge base. A failure is pre-existing only when command, environment class, and diagnostic are identical. Record both exits. Do not “fix nearby” failures outside M-01/M-02.
- **Diff constraints:**

```bash
git diff --exit-code origin/main...HEAD -- \
  _ops/adr/0004-optimize-context-projections-without-moving-authority.md \
  _ops/plans/context-efficiency-program-v1.md \
  _ops/plans/kp-context-measurement-v1-tooling-v1.md \
  .github/pr-recipe.json \
  .github/pr-automation.lock.json \
  .github/pr-verification.json \
  .github/pr-automation.json
```

- **Commit:** concise why-focused message; never skip hooks.
- **PR body:** contract decisions, expected-red/green evidence, complete commands/exits, baseline differential, content-safety probes, exact remote job expectation, rollback, and non-goals.
- **Required remote evidence:** exact-head
  `pr-automation / job:repo.dev.m3-verify` and aggregate
  `pr-automation / verify` successful. Retrieve the exact-head records with:

```bash
HEAD_SHA="$(git rev-parse HEAD)"
gh api "repos/KleinPerkins/dev/commits/$HEAD_SHA/check-runs" \
  --jq '.check_runs[]
    | select(.name=="pr-automation / job:repo.dev.m3-verify"
          or .name=="pr-automation / verify")
    | {id,name,status,conclusion,head_sha,details_url,output}'
```

  Assert the returned records have the exact current head SHA and successful
  conclusions. The job Check’s `output.text` may be null; do not infer or
  require remote stdout. Separately prove with `git show HEAD:` that the
  sandbox script unconditionally invokes the focused suite, prove the
  recipe/validated lock bind that sandbox command, and record the local
  exact-head focused count/exit in the PR body.
- **Forbidden:** direct main push, approval, manual merge, check bypass, force push, or arming native auto-merge.
- **Stop:** owner/admin gate after all fixable defects and Checks are green.

### M-04 — Bounded post-merge correction dogfood

- **Root / owner:** clean disposable Dev clone; KleinPerkins.
- **Dependencies:** M-03 protected-merged; fetch exact live main and prove the merge commit is its ancestor. Dogfood never runs from an unmerged implementation head.
- **GO:** the M-01–M-03 implementation GO must explicitly include post-merge synthetic dogfood and its one-file evidence PR, or obtain a fresh M-04 GO. The tool remains runtime-read-only, but clone/fixture/receipt/evidence creation is mutation. No client-home/private payload measurement.
- **Fixtures:** temporary UTF-8 files covering LF/CRLF/CR, Unicode whitespace, full/region selectors, canonical ID reorder, blocked path, missing/ambiguous/misordered markers, malformed schemas, and compatible/incompatible comparisons.
- **Run:** two independent processes from two working directories against the same copied fixture tree; compare receipt bytes and input stats/digests.
- **Classification:** `CORRECTION_PROVEN_NOT_E09`. Never call it E-09, a baseline, a denominator, or a seven-payload receipt.
- **Durable evidence:** build the closed ADR 0005 correction record at
  `_ops/evidence/context-efficiency/correction-dogfood-v1.json`. The fixture
  manifest is itself content-free: sorted fixture IDs, selector kinds, expected
  exits, and raw fixture digests only. `pre_stats_sha256` and
  `post_stats_sha256` hash canonical content-free maps of fixture ID to
  mode/size/mtime/raw digest. No path or source bytes enter the record.
- **Write and verify:** create the candidate outside the checkout with
  `umask 077`; validate exact keys/constants/types/digest formats and canonical
  bytes against ADR 0005; then copy it into the new tracked path. Run the same
  validator on the tracked copy, `git diff --check`, data guard, doc-warden
  check, and full differential gates. Deliver a separate protected Dev PR
  containing only that file. No PR comment is part of the contract.
- **Exact run/write procedure:** the independently tested bounded helper owns
  fixture creation, all five digest computations, the six expected exits,
  canonical serialization, and atomic candidate output:

  ```bash
  set -euo pipefail
  umask 077
  ROOT="$(git rev-parse --show-toplevel)"
  HELPER="$ROOT/_ops/context-measurement/correction_dogfood.py"
  TOOL="$ROOT/_ops/context-measurement/kp_context_measure.py"
  CANDIDATE="$(mktemp "${TMPDIR:-/tmp}/correction-dogfood-v1.XXXXXX")"
  rm -f "$CANDIDATE"
  trap 'rm -f "$CANDIDATE"' EXIT
  PYTHONDONTWRITEBYTECODE=1 python3 "$HELPER" run \
    --tool "$TOOL" \
    --implementation-root "$ROOT" \
    --output "$CANDIDATE"
  test -s "$CANDIDATE"
  PYTHONDONTWRITEBYTECODE=1 python3 "$HELPER" validate \
    --evidence "$CANDIDATE" \
    --implementation-root "$ROOT"
  mkdir -p "$ROOT/_ops/evidence/context-efficiency"
  TRACKED="$ROOT/_ops/evidence/context-efficiency/correction-dogfood-v1.json"
  test ! -e "$TRACKED"
  cp "$CANDIDATE" "$TRACKED"
  PYTHONDONTWRITEBYTECODE=1 python3 "$HELPER" validate \
    --evidence "$TRACKED" \
    --implementation-root "$ROOT"
  git status --short
  ```

  Required final status is only the new tracked JSON. `run` refuses an
  existing output path and atomically renames only after self-validation, so a
  failed probe leaves no candidate. The helper’s fixed fixtures are:

  | Fixture ID | Exact bytes (base64) | Use |
  |---|---|---|
  | `full-newlines` | `YWxwaGEgYmV0YQ0KZ2FtbWEK` | CRLF/LF/full selector |
  | `unicode-cr` | `QQ1CwqBD4oCoRAo=` | lone CR + pinned Unicode whitespace |
  | `region` | `cHJlCjwhLS0gQkVHSU4geCAtLT4KbWlkIG9uZQo8IS0tIEVORCB4IC0tPgpwb3N0Cg==` | valid inclusive region |
  | `sentinel` | `VE9LRU5fU0VOVElORUxfU0VDUkVUIHN0dWZmCg==` | no-echo probe |
  | `ambiguous` | `YWFhWgo=` | overlapping repeated marker |
  | `overlap` | `YWJjZAo=` | begin/end overlap |

  The helper also creates one absent-path entry and one unknown-field manifest.
  Its command matrix is exactly: valid measure twice from the repository and
  `/` (`0`, `0`); compatible compare (`0`); valid-identity-mismatch compare
  (`4`); aggregate blocked path/ambiguous/overlap measure (`2`); malformed
  manifest (`3`). It snapshots the six real fixtures before/after as canonical
  sorted rows with exactly `fixture_id`, integer `mode`, integer `size`, integer
  `mtime_ns`, and `raw_sha256`; snapshots must be byte-identical. The
  content-safe fixture manifest is canonical sorted rows with exactly
  `fixture_id`, `raw_sha256`, `select_kind`, and `expected_class`. These
  canonical bytes are the recorded stats/fixture digests.
- **Closed validator command:** use only the helper’s tested `validate` verb
  against the external candidate, tracked copy, and later lookup. Its contract
  is the exact schema in ADR 0005 plus: explicit type checks (booleans never
  equal integers), equal run-A/run-B and pre/post digests, canonical bytes, and
  `git rev-parse IMPLEMENTATION_COMMIT^{tree}` equality. It uses no `assert`
  and returns only `0` or fixed exit `3`, including under
  `PYTHONOPTIMIZE=1`.

  Selected invariant checks inside the helper’s already-parsed `validate`
  verb are:

  ```python
  import datetime, json, re, subprocess, sys
  from pathlib import Path

  def fail():
      print("correction evidence invalid", file=sys.stderr)
      raise SystemExit(3)

  def require(condition):
      if not condition:
          fail()

  try:
      path = Path(args.evidence)
      implementation_root = Path(args.implementation_root).resolve()
      raw = path.read_bytes()
      value = json.loads(raw.decode("utf-8"))
      keys = {
          "schema", "status", "classification", "captured_at_utc",
          "implementation_commit", "implementation_tree", "algorithm",
          "tool_contract", "environment_class", "command_set",
          "fixture_manifest_sha256", "run_a_receipt_sha256",
          "run_b_receipt_sha256", "pre_stats_sha256", "post_stats_sha256",
          "observed_exits", "content_safety",
      }
      require(type(value) is dict and set(value) == keys)
      require(value["schema"] ==
              "kp-context-measurement-correction-evidence/v1")
      require(value["status"] == "PASS")
      require(value["classification"] == "CORRECTION_PROVEN_NOT_E09")
      require(value["algorithm"] == "kp-context-measurement/v1")
      require(value["tool_contract"] == "kp-context-measurement-tool/v2")
      require(value["environment_class"] == "macos-bash3-stdlib")
      require(value["command_set"] ==
              "kp-context-measurement-correction-dogfood/v1")
      require(type(value["captured_at_utc"]) is str)
      datetime.datetime.strptime(
          value["captured_at_utc"], "%Y-%m-%dT%H:%M:%SZ"
      )
      for key in ("implementation_commit", "implementation_tree"):
          require(type(value[key]) is str)
          require(re.fullmatch(r"[0-9a-f]{40}", value[key]) is not None)
      digest_keys = (
          "fixture_manifest_sha256", "run_a_receipt_sha256",
          "run_b_receipt_sha256", "pre_stats_sha256", "post_stats_sha256",
      )
      for key in digest_keys:
          require(type(value[key]) is str)
          require(re.fullmatch(r"[0-9a-f]{64}", value[key]) is not None)
      expected_exits = {
          "blocked": 2, "compare_compatible": 0,
          "compare_incompatible": 4, "measure_a": 0,
          "measure_b": 0, "usage": 3,
      }
      require(type(value["observed_exits"]) is dict)
      require(set(value["observed_exits"]) == set(expected_exits))
      require(all(type(item) is int
                  for item in value["observed_exits"].values()))
      require(value["observed_exits"] == expected_exits)
      expected_safety = {
          "input_immutable": True, "receipts_byte_identical": True,
          "sentinel_absent": True, "source_content_present": False,
      }
      require(type(value["content_safety"]) is dict)
      require(set(value["content_safety"]) == set(expected_safety))
      require(all(type(item) is bool
                  for item in value["content_safety"].values()))
      require(value["content_safety"] == expected_safety)
      require(value["run_a_receipt_sha256"] ==
              value["run_b_receipt_sha256"])
      require(value["pre_stats_sha256"] == value["post_stats_sha256"])
      tree = subprocess.run(
          ["git", "-C", str(implementation_root), "rev-parse",
           value["implementation_commit"] + "^{tree}"],
          check=False, capture_output=True, text=True,
      )
      require(tree.returncode == 0)
      require(tree.stdout.strip() == value["implementation_tree"])
      canonical = (
          json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
      ).encode("ascii")
      require(raw == canonical)
  except SystemExit:
      raise
  except (KeyError, OSError, TypeError, UnicodeError, ValueError,
          json.JSONDecodeError):
      fail()
  ```
- **Lookup for every later task:**

  ```bash
  set -euo pipefail
  : "${DEV_EVIDENCE_ROOT:?set DEV_EVIDENCE_ROOT to the authoritative Dev checkout}"
  test "$(git -C "$DEV_EVIDENCE_ROOT" rev-parse --is-inside-work-tree)" = "true"
  DEV_TOPLEVEL="$(git -C "$DEV_EVIDENCE_ROOT" rev-parse --show-toplevel)"
  test "$(cd "$DEV_EVIDENCE_ROOT" && pwd -P)" = \
    "$(cd "$DEV_TOPLEVEL" && pwd -P)"
  DEV_ORIGIN_URL="$(git -C "$DEV_EVIDENCE_ROOT" remote get-url origin)"
  case "$DEV_ORIGIN_URL" in
    git@github.com:KleinPerkins/dev.git|\
    https://github.com/KleinPerkins/dev.git|\
    ssh://git@github.com/KleinPerkins/dev.git) ;;
    *) printf '%s\n' "DEV_EVIDENCE_ROOT origin is not KleinPerkins/dev" >&2; exit 1 ;;
  esac
  test "$(gh api repos/KleinPerkins/dev \
    --jq '(.id == 1278387789 and .full_name == "KleinPerkins/dev")')" = "true"
  LIVE_DEV_MAIN="$(gh api repos/KleinPerkins/dev/git/ref/heads/main \
    --jq '.object.sha')"
  test -n "$LIVE_DEV_MAIN"
  git -C "$DEV_EVIDENCE_ROOT" fetch --no-tags origin \
    refs/heads/main:refs/remotes/origin/main
  test "$(git -C "$DEV_EVIDENCE_ROOT" rev-parse \
    refs/remotes/origin/main)" = "$LIVE_DEV_MAIN"

  EVIDENCE_PATH="_ops/evidence/context-efficiency/correction-dogfood-v1.json"
  git -C "$DEV_EVIDENCE_ROOT" cat-file -e \
    "refs/remotes/origin/main:$EVIDENCE_PATH"
  EVIDENCE_COMMIT="$(git -C "$DEV_EVIDENCE_ROOT" log -1 --format=%H \
    refs/remotes/origin/main -- "$EVIDENCE_PATH")"
  test -n "$EVIDENCE_COMMIT"
  TMP_EVIDENCE="$(mktemp "${TMPDIR:-/tmp}/correction-dogfood-v1.XXXXXX")"
  TMP_HELPER="$(mktemp "${TMPDIR:-/tmp}/correction-dogfood-helper.XXXXXX")"
  trap 'rm -f "$TMP_EVIDENCE" "$TMP_HELPER"' EXIT
  git -C "$DEV_EVIDENCE_ROOT" show \
    "refs/remotes/origin/main:$EVIDENCE_PATH" >"$TMP_EVIDENCE"
  HELPER_PATH="_ops/context-measurement/correction_dogfood.py"
  HELPER_BLOB="$(git -C "$DEV_EVIDENCE_ROOT" rev-parse \
    "$EVIDENCE_COMMIT:$HELPER_PATH")"
  test -n "$HELPER_BLOB"
  git -C "$DEV_EVIDENCE_ROOT" show \
    "$EVIDENCE_COMMIT:$HELPER_PATH" >"$TMP_HELPER"
  PULL_COUNT="$(gh api \
    "repos/KleinPerkins/dev/commits/$EVIDENCE_COMMIT/pulls" \
    --jq '[.[] | select(.merged_at != null)] | length')"
  test "$PULL_COUNT" -eq 1
  MERGE_SHA="$(gh api \
    "repos/KleinPerkins/dev/commits/$EVIDENCE_COMMIT/pulls" \
    --jq '[.[] | select(.merged_at != null)][0].merge_commit_sha')"
  test -n "$MERGE_SHA"
  git -C "$DEV_EVIDENCE_ROOT" merge-base --is-ancestor \
    "$MERGE_SHA" refs/remotes/origin/main
  PYTHONDONTWRITEBYTECODE=1 python3 "$TMP_HELPER" validate \
    --evidence "$TMP_EVIDENCE" \
    --implementation-root "$DEV_EVIDENCE_ROOT"
  IMPLEMENTATION_COMMIT="$(python3 -c \
    'import json,sys; print(json.load(open(sys.argv[1]))["implementation_commit"])' \
    "$TMP_EVIDENCE")"
  git -C "$DEV_EVIDENCE_ROOT" merge-base --is-ancestor \
    "$IMPLEMENTATION_COMMIT" "$EVIDENCE_COMMIT"
  ```

  `DEV_EVIDENCE_ROOT` is mandatory even when the caller is already in Dev.
  Every Git read is rooted there, its canonical top level and exact Dev origin
  are verified, repository id `1278387789` is confirmed live, and
  `refs/remotes/origin/main` must equal GitHub’s live Dev `main`. The helper
  validation and exactly-one-merged-PR ancestry checks must pass. A Skills,
  CPP, AWA, stale Dev, fork, or sibling checkout therefore fails closed rather
  than supplying evidence.
  Later tasks consume only `PASS` +
  `CORRECTION_PROVEN_NOT_E09`; the artifact never authorizes E-09 or a
  reduction.
- **Lifecycle:** Dev/Laurence owns the artifact. It is append-never/edit-never:
  before consumption, revert an erroneous candidate through a governed PR;
  after consumption, retain v1 and create a new versioned schema/path under a
  successor authority. Do not create an evidence index, registry, or ledger.
- **Rollback:** before evidence merge, close/revert the candidate and discard
  temporary clone/fixtures/receipts. After merge but before downstream
  consumption, governed-revert the one-file PR and classify M-04 incomplete.
- **Stop:** any nondeterminism, unexpected exit, content echo, input mutation,
  invalid evidence shape, or remote/local mismatch reopens M-02 through a new
  corrective PR; no PASS artifact is written.

### E-01 — Make Skills bootstrap a durable projection

- **Root / owner:** `~/dev/capabilities/skills`; KleinPerkins.
- **Authority:** accepted `docs/plans/context-efficiency-e01-durable-skills-source-v1.md`.
- **Dependencies:** M-04 evidence protected-merged and revalidated. It may run in parallel with E-02, not with E-03 integration.
- **GO:** implementation GO plus the plan’s separate live-machine candidate GO before real-home execution.
- **Files:** `.github/scripts/verify-skills.sh`, `bootstrap.sh`, and `global/skills/swarm/tests/test_bootstrap.sh` only.
- **Tests:** add the plan’s red temporary-HOME cases first; prove link retargeting, unchanged real-directory collision failure, second-run no-op, no duplicate archive, no repo-byte mutation, and isolated candidate home before any real home.
- **Commands/evidence:**

```bash
bash -n bootstrap.sh
bash -n global/skills/swarm/tests/test_bootstrap.sh
bash -n .github/scripts/verify-skills.sh
bash global/skills/swarm/tests/test_bootstrap.sh
bash .github/scripts/verify-skills.sh
~/dev/_ops/bin/doc-warden.sh check "$(git rev-parse --show-toplevel)"
```

  After governed merge and the plan’s separate machine GO, preview then apply only through
  `bash "${HOME}/dev/capabilities/skills/bootstrap.sh" --reconcile --dry-run`
  and `bash "${HOME}/dev/capabilities/skills/bootstrap.sh" --reconcile`.
  Bind commit/tree and before/after link/pointer maps.
- **Rollback:** restore prior projection from the plan’s backup-before-write path; verify exact target map.
- **Stop:** candidate scope differs, real directories would be overwritten, rollback proof fails, or shared verifier changes beyond plan.

### E-03 — Establish strict skill-description eligibility

- **Root / owner:** same Skills repo; KleinPerkins.
- **Authority:** accepted `docs/plans/context-efficiency-e03-description-eligibility-v1.md`.
- **Dependencies:** E-01 merged and E-03 branch rebased/re-proven because both edit `.github/scripts/verify-skills.sh`.
- **GO:** implementation GO plus the plan’s separate exact-candidate live GO.
- **Files:** `.github/scripts/verify-skills.sh`, `local/skills/update-skills/SKILL.md`, `scripts/skill-description-inventory.py`, `scripts/tests/fixtures/skill-description-normalization-v1/cases.json`, and `scripts/tests/test_skill_description_inventory.py`.
- **Tests/interfaces:** strict bounded YAML 1.2 Core parser and
  `skill-description-normalization/v1`; tracked candidate discovery; one quoted
  `argument-hint` syntax repair; no partial rows/totals, budget, shortening, fallback parser, registry, or description rewrite.
- **Commands:**

```bash
python3 -m py_compile \
  scripts/skill-description-inventory.py \
  scripts/tests/test_skill_description_inventory.py
bash -n .github/scripts/verify-skills.sh
python3 -m unittest discover -s scripts/tests \
  -p 'test_skill_description_inventory.py' -v
bash .github/scripts/verify-skills.sh
~/dev/_ops/bin/doc-warden.sh check "$(git rev-parse --show-toplevel)"
```

- **Evidence/rollback/stop:** follow the accepted exact parser/fixture/source digest gate; reconcile Cursor/Claude only after machine GO; no CPP descriptor, generated memory, fallback parser, or client action during the canary.

### E-02 — Make CPP projections durable

- **Root / owner:** `~/dev/affirm/src/card-platform-product`; CPP governed owner path.
- **Authority:** accepted `_ops/plans/durable-cpp-skill-projections-v1.md`.
- **Dependencies:** M-04 evidence protected-merged and revalidated; may run in parallel with E-01/E-03 in its own repo.
- **GO:** LD-authored control-plane implementation GO; run `_ops/hooks/session-start`.
- **Files:** `_ops/bin/cpp-lib.sh`, `_ops/bin/cpp-install-skills.sh`, `_ops/bin/cpp-doctor.sh`, three named test files, two named skill docs, and `_ops/cpp-operating-model-SOT.md`, exactly as §5 of the accepted plan.
- **Tests:** implement all 16 §6 cases red-first; then run the focused commands and full CPP gates in §8, using temporary HOME and synthetic primary/linked worktrees.
- **Commands:**

```bash
bash _ops/tests/test_cpp_install_skills.sh
bash _ops/tests/test_bootstrap_idempotency.sh
bash _ops/tests/test_skills.sh
bash _ops/tests/test_eco_reconcile.sh
bash _ops/tests/test_agent_shims.sh
_ops/ci/cpp-integrity-engine check --report
_ops/ci/cpp-integrity-engine check --local --base origin/main
bash _ops/tests/run.sh
_ops/bin/render-agent-shims.sh --check
git diff --check
```
- **Evidence:** clean install/upgrade/repair/dry-run/failure/rerun/idempotence/linked-worktree-removal/rollback receipts bound to exact commit and changed-file hashes.
- **Merge:** one governed LD-authored PR; no agent-armed auto-merge.
- **Rollback/stop:** follow §§10–11; stop on baseline blob drift, ownership ambiguity, CPP policy/control-plane widening, or inability to preserve foreign/real collisions.

### E-04 — Implement AWA external hook ownership and release v1.5.2

- **Root / owner:** `~/dev/capabilities/awa`; KleinPerkins.
- **Authority:** accepted `docs/plans/external-hook-owner-contract-v1.md`.
- **Dependencies:** M-04 evidence protected-merged and revalidated; E-01/E-03 and E-02 are independent, but E-05/E-09 wait for all applicable lanes.
- **GO:** plan’s implementation GO, protected PR merge, then a separate release GO after exact merged-main and isolated installed-runtime proof.
- **Files:** the accepted plan’s exact surfaces:
  `contracts/awa-contract.v1.json`,
  `kernel/checks/awa-contract-freeze.sh`,
  hook-owner tests/fixtures,
  `kernel/lib/install-lib.sh`,
  `kernel/hooks/install-hooks.sh`,
  `install.sh`, `Makefile`,
  `live-verify/trial-runner/_trial_phase2.py`,
  `README.md`, `ARCHITECTURE.md`,
  `engine/__init__.py`, and `pyproject.toml`.
- **Contract:** add persisted `awa-hook-owner/v1`; direct remains the fresh/legacy default; external mode performs zero selected-hook-file reads/writes across install/repair/doctor/uninstall; runtime hook scripts, finish executor, Git classification, kernel-first safety, fail-open, recovery, and heartbeat remain v1.5.1-compatible.
- **Commands:**

```bash
python3 -m unittest engine.tests.test_hook_owner_modes
python3 -m unittest engine.tests.test_guard_hook_wrappers
python3 -m unittest \
  engine.tests.test_finish_conversation \
  engine.tests.test_finish_hardening
bash engine/tests/run-tests.sh
AWA_HOME="$(pwd)" bash kernel/checks/awa-contract-freeze.sh
./install.sh --check
make verify
make verify-install
git diff --check
git diff --check origin/main...HEAD
~/dev/_ops/bin/doc-warden.sh check "$(pwd)"
```

- **Release:** prepare version `1.5.2` only if still available; after governed implementation merge, stop for explicit
  `GO to publish AWA v1.5.2 at MERGE_SHA`. Then tag/publish that exact merge and hand tag/commit/release URL/contract digest/verification/rollback ref to E-05.
- **Rollback:** before release use a governed revert PR; after publication never move/delete v1.5.2—publish a separately reviewed corrective patch; downstream Skills/Dev own pin/hook rollback and maintain a complete owner.
- **Stop:** any external hook-file access, host literal, v1.5.1 behavior-file drift, repository-owned red gate, unavailable v1.5.2, missing Release GO, or release tag/commit mismatch.

### E-05 — Pin the qualified AWA release in Skills

- **Root / owner:** Skills; KleinPerkins.
- **Dependencies:** E-01 and E-03 merged on Skills main; E-04 release qualified and immutable.
- **GO:** author and accept a narrow Skills implementation plan first, then separate implementation GO.
- **Expected plan/implementation surface:** `global/tools/awa/meta.yml`, `tool.yml`, `README.md`, `install.sh`, the existing verifier/clean-room surfaces that already own Flavor-2 bindings, `.eco-registry.lock` only through its normal lockkit path, and tests proving exact release commit/digest and isolated install.
- **Contract:** change the GCB from v1.5.1’s commit to the exact E-04 release commit; no runtime vendoring, no hand-edited generated lock, no local-scope enrollment confusion.
- **Evidence:** tag→commit proof, release artifact digests, static `--check`, temporary-HOME clone-at-pin/install/doctor, idempotence, lockkit parity, and normal governed Skills PR.
- **Rollback:** revert GCB to the previously qualified pin and re-run isolated install/doctor.
- **Stop:** release is mutable/unqualified, pin and tag disagree, runtime bytes are proposed for the shelf, or WF1/lockkit authority is bypassed.

### E-06 — Consume the AWA pin through Dev’s thin host overlay

- **Root / owner:** Dev; KleinPerkins/Laurence.
- **Dependencies:** E-05 merged and the Skills checkout at that exact commit.
- **GO:** author/accept a narrow Dev host-overlay plan, then implementation GO; real-home candidate requires a separate exact machine GO.
- **Expected surface:** `_ops/bin/install-dev-awa-overlay.sh`, `_ops/bin/install-worktree-hooks.sh`, focused overlay/worktree tests, and operator docs only if the accepted E-06 plan proves they are stale.
- **Contract:** preserve the thin host boundary; Skills GCB installs the standalone AWA runtime while Dev owns only host policy literals and real `~/.cursor/hooks.json` wiring. Required projection is the accepted external hook-owner five-role contract, not a forked kernel copy.
- **Tests/evidence:** offline static check, isolated HOME install/repair/doctor, exact hook-event inventory, no duplicate/stale AWA hooks, second-run byte identity, prior-runtime rollback, then operator-authorized real-machine install receipt.
- **Rollback:** restore hooks backup and prior GCB/runtime pointer; prove doctor and hook inventory match the pre-candidate state.
- **Stop:** SSP writes real hooks behind the overlay, Dev gains kernel/engine bytes, clean-room fails, or real-machine scope is not exact.

### E-07 — Project learned data through the private gate

- **Root / owner:** private operator-controlled local state only; Laurence.
- **Dependencies:** M-04 evidence, E-01, E-02, E-03, E-04, E-05, and E-06 green on exact merged artifacts.
- **GO:** a new explicit authorization must name the candidate root, exact machine, operation, source/target classes, backup path, and rollback command. Prior program acceptance is not this GO.
- **Protocol:** read-only discovery first; reject unsupported/ambiguous/private scope; backup-before-write; project only the accepted generated-memory target; verify content class and permissions without placing contents in tracked artifacts; run rollback rehearsal.
- **Evidence:** content-free counts/digests/status only, kept private; no raw learned data in chat, git, PRs, test fixtures, or receipts.
- **Rollback:** exact private backup restore, then permission/digest verification.
- **Stop:** authorization absent/stale, scope ambiguous, secret classification unresolved, or any public/tracked surface would receive content.

### E-08 — Repair a reproduced code defect only

- **Root / owner:** the repository that owns the reproduced defect.
- **Dependencies:** valid E-07 run plus deterministic evidence that the failure is code, not data/state/config.
- **GO:** explicit implementation GO after a narrow defect plan names files, tests, and owner.
- **Action:** add the smallest biting regression, fix only the reproduced defect, verify owner-repo gates, and deliver one governed PR.
- **Not activated when:** E-07 succeeds, evidence is ambiguous, or the defect is in operator data.
- **Rollback:** governed revert of the narrow fix.
- **Stop:** proposed fix broadens scope, requires viewing/publishing private content, or cannot reproduce hermetically.

### E-09 — Freeze the seven-payload denominator last

- **Root / owner:** Dev evidence surface; Laurence.
- **Dependencies:** M-04 evidence protected-merged and revalidated; E-01–E-06 repository changes merged and their required machine/client reconciliations green; E-07 privately complete; E-08 either merged/green or explicitly `E08_NOT_ACTIVATED`.
- **GO:** explicit freeze GO naming the seven exact paths, eligible client/root class, baseline ID, owner commits/trees/blobs, generated-input digest set, validator branch, and evidence branch. It authorizes only the four validator-PR files and three later evidence-PR files below; both protected merges remain owner/admin gates.
- **Seven canonical IDs:** `awa-operator`, `dev-operating-model`,
  `generated-home-agents`, `subagent-orchestration`, `terse-output`,
  `workspace-agents`, `worktree-default`.
- **Expected files:**
  Validator PR:
  - `_ops/context-measurement/validate_static_context_manifest.py`
  - `_ops/context-measurement/test_validate_static_context_manifest.py`
  - `_ops/context-measurement/README.md`
  - `_ops/checks/doc-warden-verify.sh`

  Later freeze PR:
  - `_ops/evidence/context-efficiency/e09-input-v2.json`
  - `_ops/evidence/context-efficiency/e09-receipt-v2.json`
  - `_ops/evidence/context-efficiency/static-context-manifest-v1.json`
- **Validator interface:** stdlib-only, read-only CLI:

```text
validate_static_context_manifest.py
  --manifest PATH
  --input PATH
  --receipt PATH
  --owner-checkout REPOSITORY=PATH
  [--owner-checkout REPOSITORY=PATH ...]
```

  It requires exactly the three owner repositories in ADR 0005, invokes only local read-only Git commands, proves each checkout HEAD is the manifest commit, imports the closed v2 receipt validator, proves every ADR 0005 “E-09 uses one closed evidence envelope” join, verifies canonical JSON bytes, and emits one canonical content-free object with exactly
  `schema`, `status`, `manifest_sha256`, `input_sha256`, and `receipt_sha256`.
  Fixed values are `static-context-manifest-validation/v1` and `OK`.
  Exit `0` is valid; exit `3` is fixed, value-free usage/validation failure. No network or write mode exists.
- **Validator tests/PR:** write malformed-key/type/join/hash/tree/blob/path/order/generated-output/total/canonical-byte cases red-first, then implement. Add its test file to the actual `doc-warden-verify.sh --sandbox` remote entry point alongside the measurement suite. Run focused/full Dev gates and deliver one protected validator PR before creating candidate evidence. This preparatory PR does not freeze or measure any operator payload.
- **Preflight:** after the validator PR merges, create the closed `kp-context-measurement-input/v2`; use full-file selection for all seven unless the explicit GO and actual client projection prove a region; require exact owner refs/blobs and installed-byte equality before measuring.
- **Python 3.9 portability gate:** run this with the same unpinned
  `python3` executable used for E-09 and record its version. It statically
  parses the write pattern against Python 3.9 grammar and probes the
  `Path.open(..., newline="\n")` API without relying on newer
  `Path.write_text` parameters:

```bash
python3 --version
PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
import ast
import sys
import tempfile
from pathlib import Path

if sys.version_info < (3, 9):
    raise SystemExit("Python 3.9 or newer is required")
source = """\
with Path("out.json").open(
    mode="w", encoding="utf-8", newline="\\n"
) as output:
    output.write("{}\\n")
"""
ast.parse(source, mode="exec", feature_version=9)
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "out.json"
    with path.open(mode="w", encoding="utf-8", newline="\n") as output:
        output.write("{}\n")
    if path.read_bytes() != b"{}\n":
        raise SystemExit("Python 3.9 newline probe failed")
PY
```

- **Run:**

```bash
set -euo pipefail
umask 077

ROOT="$(git rev-parse --show-toplevel)"
TOOL="$ROOT/_ops/context-measurement/kp_context_measure.py"
VALIDATOR="$ROOT/_ops/context-measurement/validate_static_context_manifest.py"
INPUT="$ROOT/_ops/evidence/context-efficiency/e09-input-v2.json"
MANIFEST="$ROOT/_ops/evidence/context-efficiency/static-context-manifest-v1.json"
RECEIPT="$ROOT/_ops/evidence/context-efficiency/e09-receipt-v2.json"
RECEIPT_DIR="${RECEIPT%/*}"
test -f "$TOOL"
test -f "$VALIDATOR"
test -f "$INPUT"
test -f "$MANIFEST"
test -d "$RECEIPT_DIR"
test ! -e "$RECEIPT"
: "${AWA_ROOT:?set AWA_ROOT to the exact clean owner checkout}"
: "${DEV_ROOT:?set DEV_ROOT to the exact clean owner checkout}"
: "${SKILLS_ROOT:?set SKILLS_ROOT to the exact clean owner checkout}"

TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/kp-e09.XXXXXX")"
RUN_A="$TMP_ROOT/receipt-a.json"
RUN_B="$TMP_ROOT/receipt-b.json"
VALIDATION="$TMP_ROOT/validation.json"
PRE_STATS="$TMP_ROOT/pre-stats.json"
POST_STATS="$TMP_ROOT/post-stats.json"
RECEIPT_STAGE=""
cleanup() {
  rm -rf "$TMP_ROOT"
  if [ -n "$RECEIPT_STAGE" ]; then rm -f "$RECEIPT_STAGE"; fi
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

snapshot_inputs() {
  OUTPUT="$1"
  python3 - "$INPUT" "$OUTPUT" <<'PY'
import hashlib, json, stat, sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
rows = []
for item in manifest["projections"]:
    path = Path(item["path"])
    raw = path.read_bytes()
    info = path.stat()
    rows.append({
        "mode": stat.S_IMODE(info.st_mode),
        "mtime_ns": info.st_mtime_ns,
        "projection_id": item["projection_id"],
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "size": info.st_size,
    })
rows.sort(key=lambda item: item["projection_id"].encode("ascii"))
value = {"schema": "e09-input-stats/v1", "rows": rows}
with Path(sys.argv[2]).open(
    mode="w", encoding="utf-8", newline="\n"
) as output:
    output.write(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    )
PY
}

snapshot_inputs "$PRE_STATS"

set +e
PYTHONDONTWRITEBYTECODE=1 python3 "$TOOL" measure \
  --manifest "$INPUT" >"$RUN_A"
MEASURE_A_EXIT=$?
set -e
test "$MEASURE_A_EXIT" -eq 0
test -s "$RUN_A"

set +e
(
  cd /
  PYTHONDONTWRITEBYTECODE=1 python3 "$TOOL" measure \
    --manifest "$INPUT"
) >"$RUN_B"
MEASURE_B_EXIT=$?
set -e
test "$MEASURE_B_EXIT" -eq 0
test -s "$RUN_B"
cmp "$RUN_A" "$RUN_B"

set +e
PYTHONDONTWRITEBYTECODE=1 python3 "$VALIDATOR" \
  --manifest "$MANIFEST" \
  --input "$INPUT" \
  --receipt "$RUN_A" \
  --owner-checkout "KleinPerkins/awa=$AWA_ROOT" \
  --owner-checkout "KleinPerkins/dev=$DEV_ROOT" \
  --owner-checkout "KleinPerkins/skills=$SKILLS_ROOT" \
  >"$VALIDATION"
VALIDATOR_EXIT=$?
set -e
test "$VALIDATOR_EXIT" -eq 0
test -s "$VALIDATION"
snapshot_inputs "$POST_STATS"
cmp "$PRE_STATS" "$POST_STATS"
STATS_SHA256="$(python3 -c \
  'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' \
  "$PRE_STATS")"
test "${#STATS_SHA256}" -eq 64

# Only a successful, independently reproduced, validator-accepted receipt
# reaches the tracked path. The temporary file is created in the same
# directory so the final rename is atomic on macOS.
RECEIPT_STAGE="$(mktemp "${RECEIPT}.tmp.XXXXXX")"
cp "$RUN_A" "$RECEIPT_STAGE"
cmp "$RUN_A" "$RECEIPT_STAGE"
test ! -e "$RECEIPT"
mv "$RECEIPT_STAGE" "$RECEIPT"
RECEIPT_STAGE=""
```

  The candidate static manifest is assembled against a prior untracked
  duplicate receipt; the final procedure above remeasures and validates that
  binding before promotion. A pre-existing receipt is a hard stop. A failed
  measure, validator, or stat comparison exits before `RECEIPT_STAGE` is
  created, so it cannot truncate, replace, or create the tracked receipt. The
  manifest uses stable absolute installed paths so the
  independent-CWD run addresses the same bytes. Capture and compare pre/post
  input stats/digests through `snapshot_inputs`; record the single content-safe
  `$STATS_SHA256` in the evidence PR body.

  `$AWA_ROOT`, `$DEV_ROOT`, and `$SKILLS_ROOT` are clean local checkouts at the exact commits named by the freeze GO. No source text or learned content is tracked.
- **PR/acceptance:** one protected Dev evidence PR containing only the three files; operator reviews the exact three artifact SHA-256 values plus the content-safe pre/post stats SHA-256; exact-head Checks pass; protected merge makes the static manifest authoritative. Require seven `OK` rows, exact totals, byte-identical independent run, immutable sources, and operator signoff. Do not arm auto-merge.
- **Rollback:** before protected merge, close/revert the candidate. After authoritative use, never edit it in place; a new accepted decision/plan defines a successor schema/file and baseline ID. Correct the owning projection first, then remeasure.
- **Stop:** any prerequisite missing, receipt incompatibility, authority drift, nondeterminism, blocked projection, content leak, or owner/operator gate absent.

### Release 1 — Reduce the seven static payloads

E-09 freezes the denominator; it does not authorize or perform a reduction.
Each owner must first refresh live authority and accept a narrow plan naming
exact files, semantic inventory, commands, canaries, rollback, and any
exact-digest operator gate.

| ID | Root / owner | Dependencies and GO | Required result and evidence | Rollback / stop |
|---|---|---|---|---|
| S-01 | Dev / Laurence | Protected-merged E-09; accepted Dev reduction plan; implementation GO | Reduce only Dev-owned static projections by removing duplication and adding precise progressive-disclosure pointers. Bind before/after source and installed digests, semantic invariant map, focused/full Dev gates, and fresh Cursor canary. | Governed revert + standard rule reinstall. Stop on safety/authority loss, routing drift, or unowned bytes. |
| S-02 | Skills / KleinPerkins | Protected-merged E-09; accepted Skills reduction plan; implementation GO; separate private machine GO before any generated-memory candidate | Reduce Skills-owned generated/global wording while preserving every learned source bullet, model-tier behavior, routing, and restore path. Prove source/install parity, semantic identity, isolated HOME, private restore, and affected Cursor/Claude/Codex canaries. | Revert owner source, reinstall/regenerate from preserved inputs, verify digest/semantics. Stop on learned-fact loss, private-content disclosure, or client access regression. |
| S-03 | AWA / KleinPerkins, conditional | S-01/S-02 merged and measured shortfall remains; explicit operator decision; accepted AWA plan; implementation GO | Reduce `awa-operator` only as much as needed. Require exact candidate digest, full finish/hook/operator regression, install proof, and fresh affected-client canary. | Governed revert and reinstall last qualified AWA projection. Stop if S-01/S-02 already meet 30%, safety prose changes, or exact-digest approval is absent. |
| S-04 | Dev/program | S-01/S-02 and, only if activated, S-03 merged/reconciled | Remeasure the same E-09 workload under the compatible v2 contract. Protected-merge a versioned Release-1 evidence artifact named by an accepted Dev evidence plan; both words and characters must be `<= floor(E-09 * 70 / 100)`. | Revert the failing owner candidate and remeasure. Never lower the target implicitly; stop for a plan revision if the operator declines S-03 and Dev/Skills cannot meet it. |

### Release 1.1 — Reduce capability discovery

Release 1.1 remains the accepted scope-first capability-discovery program. It
does not reuse M-01–M-04 IDs; the `D-*` identifiers below are the historical
Release 1.1 task IDs.

| ID | Root / owner | Dependencies and GO | Required result and evidence | Rollback / stop |
|---|---|---|---|---|
| D-01 | Dev/program | E-01/E-02/E-03 merged; Release 1 evidence stable; accepted Dev inventory plan | Inventory the actual injected/discovered catalog by client/root, including unique ID, owner source, exposure, installed path/digest, normalized description size, and eligibility. Source-file counts alone are insufficient. | Evidence-only candidate may be reverted. Stop on malformed YAML, unknown owner, or inability to distinguish installed files from client injection. |
| D-02 | Skills / KleinPerkins | D-01 accepted evidence; accepted Skills plan; implementation GO | Scope first, then shorten only remaining Skills-owned auto-discovery descriptions. Enforce valid YAML 1.2 normalization, no exact duplicates, warning over 300, failure over 600, and migration failure over 1,024; prove routing and eligible-client canaries. | Revert source/exposure and reconcile through Skills. Stop on out-of-root routing loss, parser fallback, or manual-only conversion without existing authority. |
| D-03 | CPP / governed LD owner | D-01 accepted evidence; accepted CPP `Class: control-plane` plan; LD implementation GO | Test project scoping for CPP-local skills, then shorten only globally necessary descriptions. Prove CPP-root discovery plus non-CPP `agent-route → CPP → skill` handoff and all remaining budgets. | Governed CPP revert and installer reconcile to prior global exposure. Stop on access loss, hand-vendoring, or CPP control-plane widening. |
| D-04 | Skills/orchestrator/CPP owners | D-02 merged; D-03 merged if activated; normal WF1/WF2/orchestrator approvals | Reconcile global capability projections only through the standard lifecycle; prove lockkit parity, owner-source/CPP payload consistency, and client projection parity. | Use orchestrator/owner rollback paths. Stop on manual CPP vendoring, generated-lock editing, or a second installer channel. |

If CPP project scoping fails its ordinary-language/client-parity canary, D-03
retains global exposure and performs description-only reduction. No new router
or registry is authorized.

### Release 2 — Prove clients and close the program

| ID | Root / owner | Dependencies and GO | Required result and evidence | Rollback / stop |
|---|---|---|---|---|
| C-01 | Dev/program | Releases 1 and 1.1 merged/reconciled; accepted Dev closure plan | Run the full projection-specific matrix for fresh Cursor Desktop/Cloud/background/multi-root, Claude, and Codex surfaces that are eligible; each ineligible row cites a current product constraint. | Reopen the owning release task on regression. Stop on stale current-chat evidence or blanket cohort claims. |
| C-02 | Dev/program | C-01 green; explicit operator closure review | Protected-merge the versioned final evidence and built-versus-planned record named by the closure plan: exact owner refs/digests, static result, catalog result, residuals, rollback refs, and no unresolved P0/P1. | Revert unaccepted evidence; after acceptance supersede, never rewrite. Stop on unknown owner, stale ref, or unproved rollback. |
| C-03 | Each owner repository | Corresponding implementation merged; owner docs proven stale; owner-local plan/GO | Update only owner documentation/policy made stale by implementation, remove superseded process residue, and pass owner governance. C-03 may run per owner after its last implementation, but program closure waits for all applicable owners. | Governed owner revert. Stop on duplicate authority or unrelated documentation cleanup. |

Only C-02/C-03 evidence supports a later operator decision that the program is
complete. E-09 alone supports only a frozen Release 0 denominator.

## 8. Verification matrix

| Layer | Command/evidence | Pass rule |
|---|---|---|
| Docs | `_ops/bin/doc-warden.sh check .`; `bash _ops/checks/doc-warden-verify.sh --sandbox`; `bash _ops/checks/doc-warden-verify.sh` | New docs indexed/valid; accepted v1 bytes unchanged |
| Measurement focused | `python3 _ops/context-measurement/test_kp_context_measure.py -v` | All tests pass; no bytecode residue |
| Remote Dev | exact-head sandbox-script blob + recipe/validated-lock binding + `pr-automation / job:repo.dev.m3-verify` and aggregate Check | Bound exact-head entry point includes focused suite; both Checks match head and succeed; no stdout/count claim |
| Correction handoff | protected-merged `correction-dogfood-v1.json` + closed validator | canonical closed PASS record; no content/free-form fields |
| Content safety | sentinel table across unknown keys/values/markers/malformed JSON | no sentinel or source text in stdout/stderr/receipt |
| Exit contract | CLI/manifest/path/region/receipt table | external outcomes only `0/2/3/4` with ADR 0005 meaning |
| Determinism | two processes + two working directories | byte-identical canonical receipts |
| Immutability | pre/post stat and digest | measured inputs unchanged |
| Full Dev | `make worktree-verify`; `make verify-ci` | green, or exact base/head differential recorded for pre-existing failure |
| Owner repos | each accepted plan’s focused/full/remote gates | exact merged artifacts and receipts |
| Private gate | E-07 explicit GO + content-free private receipt | no learned data crosses boundary |
| Freeze | E-09 isolated duplicate run + validator before atomic receipt promotion | exits exactly `0`; seven `OK` rows; failed run cannot create/truncate tracked receipt |
| Releases 1/1.1 | owner evidence + fresh-client canaries | 30% static target met, discovery reduced without routing/access loss |
| Release 2 | C-01 matrix + C-02/C-03 protected evidence | no unresolved P0/P1, stale authority, or unproved rollback |

## 9. Gate reporting

At every owner/operator gate, report only:

1. requested decision in plain language;
2. repository/root, branch, and exact head;
3. authorized file/data/machine scope;
4. passed/failed commands with exits and remote Check names;
5. known pre-existing failures separated by base/head differential;
6. rollback command/artifact and proof status;
7. forbidden actions still in force; and
8. the exact next step if approved.

Do not imply that an accepted plan is implementation GO, that a green label
proves an unbound suite, that Check API exposes stdout when `output.text` is
null, that a PR is durably accepted before protected merge, that synthetic
dogfood is E-09, or that E-09 completes Releases 1, 1.1, or 2.

## 10. Completion criteria

This program is complete only when:

- ADR 0005 and this plan are protected-merged and v1 artifacts remain byte-identical;
- M-01–M-04 are green on exact merged Dev main, including the protected-merged
  correction evidence record;
- E-01/E-03, E-02, and E-04 are implemented and protected-merged;
- E-04 has an immutable qualified release;
- E-05 pins it and E-06 proves installed thin-overlay behavior;
- E-07 has an explicit private authorization and content-free successful evidence;
- E-08 is either merged from a reproduced defect or explicitly `NOT_ACTIVATED`;
- E-09 has one operator-approved, independently reproduced v2 seven-payload receipt and its protected-merged `static-context-manifest/v1`; and
- Release 1 meets the 30% word and character targets without protected
  regression;
- Release 1.1 completes the scope-first capability-discovery reduction and
  standard lifecycle reconciliation;
- Release 2 completes the fresh-client matrix, final evidence, and applicable
  owner documentation closure; and
- every temporary writer tree, fixture, process, and retained clone is either governed-cleaned or deliberately retained with a named reason and recovery artifact.

Before E-09 protected-merges its accepted evidence, no denominator is frozen.
After E-09, the seven-payload Release 0 denominator may be described as frozen
while the broader program remains in progress. No broader context-reduction
completion claim is allowed until the applicable Release 1, Release 1.1, and
Release 2 gates above pass; the program is complete only when every criterion
in this section passes.
