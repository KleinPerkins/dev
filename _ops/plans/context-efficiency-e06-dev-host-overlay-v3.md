# Context Efficiency E-06 v3 — make bootstrap an AWA transaction barrier

**Version:** v3
**Status:** ACCEPTED — 2026-08-18
**Date:** 2026-08-18
**Owning repository:** `KleinPerkins/dev` (`~/dev`)
**Owner:** Laurence Duggan
**Program milestone:** Context Efficiency Program v2 `E-06`
**Plan-type:** standard
**Supersedes:** [E-06 Dev host-overlay v2](context-efficiency-e06-dev-host-overlay-v2.md), which remains byte-identical history
**Review provenance:** Live Dev main, accepted ADR 0005 and Program v2, immutable E-06 v1/v2 plans, preserved v1 and v2 implementation checkpoints, exact base/head clean-room differentials with Skills E-05, the root bootstrap and clean-room call paths, and the published AWA v1.5.2 external-owner contract.

**Goal:** Remove the interruption window between a successful external-owner AWA runtime install and Dev’s host-hook reconciliation. Root bootstrap must resolve the AWA runtime/host pair immediately after capabilities bootstrap, before any unrelated step can fail, while clean-room must exercise a genuinely offline, deterministic AWA lane.

**Architecture:** Skills remains the only AWA Global Capability Binding (GCB) and AWA remains the standalone runtime owner. Dev adds no runtime or behavior bytes. Dev’s root bootstrap becomes the transaction coordinator: it invokes capabilities with external ownership, immediately resolves the one Dev host transaction regardless of the capabilities child’s exit, and only then either proceeds or returns the original failure. A complete external runtime is inert with respect to the selected hook file until Dev atomically installs the exact five-role host projection.

> **Authority boundary:** This plan creates no implementation GO and no machine-install GO. The
> accepted v2 implementation GO cannot authorize the new bootstrap ordering or clean-room harness
> surface. After protected merge, a fresh explicit E-06 v3 implementation GO must name the
> checkpoints and pickup in §4. Acceptance never authorizes real `HOME` or hook mutation, E-07,
> E-08, or E-09.

---

## 1. Exact authority and preserved implementation state

| Authority | Exact binding | Required fact |
|---|---|---|
| Dev planning base | `bf34ba54c493f7bd12b130736602e8cfd9ea843c`; tree `4e01956da909e137477862110bff01f679187835` | Live Dev main; v2 plan protected-merged through PR #278. |
| Active decision/program | ADR 0005 + Context Efficiency Program v2 | Distributed source authority, thin Dev host overlay, separate real-machine gate, and E-06-before-E-07/E-09 sequencing remain binding. |
| Immutable E-06 v1 | blob `a2fdf79146c8d8d1a48c2f9455b5766bcfdd6306` | Historical plan remains byte-identical and `SUPERSEDED`. |
| Immutable E-06 v2 | blob `95eb1e7c8ee24bc1e062af8b1f1f9f0568120043` | Accepted plan remains byte-identical until this v3 successor is accepted. |
| Original implementation checkpoint | `aed42b011cca0cbc1c45871af866321712ef0d64`; tree `17f06bb129c1fec4ba10d75a5bc0ecff13a67e8d` | Clean, local, unpushed v1 checkpoint on `impl/context-efficiency-e06-host-overlay`. |
| Applied v1 checkpoint | `22748cd83836a1d9598a42bd9f431789738a8a76` | Clean cherry-pick of the four v1-authorized paths onto v2 main. |
| Preserved v2 WIP checkpoint | `a0bd67e42b278fc9ae837e7a6163a404c29bdf7b`; parent `22748cd83836a1d9598a42bd9f431789738a8a76`; tree `d8dfe2fd609f226972f9a1175c664594eaed2a35` | Clean, local, unpushed branch `impl/context-efficiency-e06-host-overlay-v2`; adds only `bootstrap.sh`, the offline overlay branch, and focused tests. |
| Qualified AWA release | v1.5.2 at `a2b13f7e7feb47f53ebb63ee59b4c61eb1e38fc3` | Contract SHA-256 `408e271e9f55269d276e6d34e2aa3bb2bbc072fea3b6c8a841ede1912978c4d9`; external mode has zero selected-hook-file access and exposes exactly five roles. |
| Skills E-05 | `c6e94f424898ba37ae12cbc264b138294564fa8b` | Exact integration source and AWA v1.5.2 pin. |

Plan work must not move, rebase, amend, delete, push, or open a PR from either implementation
branch. Record their refs, parents, trees, status, and path sets before and after every plan commit.
The v3 documentation branch starts from exact live Dev main and contains no implementation commit.

A harmless Dev or Skills advance requires refreshed ancestry and relevant-blob comparison. A
material change to the bootstrap, overlay, clean-room, AWA shelf/pin/contract, ADR 0005, Program v2,
or an E-06 plan stops implementation and requires another successor.

## 2. Proven failure and scope decision

### 2.1 Exact clean-room differential

With the candidate bytes later checkpointed as `a0bd67e`, exact Skills E-05, isolated `HOME`, and
the existing `make eco-cleanroom` command:

1. root bootstrap step 1 invoked Skills with `AWA_HOOK_OWNER=external`;
2. the AWA GCB acquired and installed a complete external runtime;
3. root bootstrap then failed in the pre-existing agent-rules/continual-learning path;
4. step 7 never ran, so Dev never reconciled the host hook projection; and
5. clean-room’s final overlay check correctly rejected the complete runtime plus absent host matrix.

The exact base at `bf34ba5` had the same unrelated clean-room failures, but its AWA overlay static
check passed. The candidate added one failure:

```text
FAIL dev AWA overlay --check
FAIL installed external-owner host hook projection drifted
```

This is candidate-owned and v2 correctly required a stop. It also exposed a pre-existing harness
claim mismatch: `_ops/eco/clean-room.sh` says its bootstrap lane has no network, but it only sets
`ECO_BOOTSTRAP_OFFLINE=1`; the Skills AWA GCB does not consume that variable and may still clone.

### 2.2 Transactional decision

Root bootstrap must treat capabilities bootstrap plus Dev AWA reconciliation as one ordered barrier:

```text
capture capabilities exit without triggering top-level set -e
  -> capabilities bootstrap with external owner + Dev policy/root
  -> immediately invoke the Dev overlay exactly once
       absent runtime: honest offline deferral, no host write
       complete validated external runtime: atomic exact five-role reconciliation
       invalid/incomplete runtime: refuse, preserve hook preimage
  -> resolve both exits before any non-AWA root step
       overlay failure: root exits nonzero
       capabilities failure: root exits with that failure after AWA resolution
       both success/defer: continue ordinary bootstrap
```

The existing late step-7 overlay call is removed; there is one host transaction, not an early call
plus a later repair. The overlay is attempted even when capabilities bootstrap returns nonzero,
because that child may have installed AWA successfully before an unrelated capability failed.

`bootstrap.sh` keeps `set -euo pipefail`, so the executor must use an explicit guarded capture—not a
bare child command:

```bash
capabilities_rc=0
AWA_HOOK_OWNER=external \
AWA_POLICY="$ROOT/_ops/policy/worktree-policy.yml" \
AWA_GOVERNED_ROOT="$ROOT" \
  bash "$ROOT/capabilities/bootstrap.sh" || capabilities_rc=$?

overlay_rc=0
bash "$ROOT/_ops/bin/install-dev-awa-overlay.sh" || overlay_rc=$?

if [ "$overlay_rc" -ne 0 ]; then exit "$overlay_rc"; fi
if [ "$capabilities_rc" -ne 0 ]; then exit "$capabilities_rc"; fi
```

Equivalent code is allowed only if both commands are syntactically protected from `set -e`, the
overlay always runs after the child returns, overlay failure has exit precedence, and capabilities
failure is returned before any later step. The three AWA bindings are inline assignments to the
capabilities child only; `capabilities/bootstrap.sh` and its Skills manifest children inherit the
exact values, while the root shell environment is byte-for-byte unchanged afterward. Tests seed
caller sentinels and require they are restored rather than merely absent.

Dev does not roll back or delete SSP runtime bytes. A complete external runtime left after an overlay
validation failure is a safe staged candidate: AWA has not accessed the selected hook file, Dev’s
hook preimage and backup set are unchanged, root reports failure, and no later bootstrap step runs.
It is not reported as installed host state. Deleting or restoring runtime behind Skills/AWA would
cross the thin-host boundary and is rejected. A successful barrier has only two allowed outcomes:

- no runtime and no host mutation, explicitly deferred; or
- exact qualified external runtime plus the exact Dev five-role matrix.

No successful or continuing path may expose complete external runtime with a missing, duplicate,
stale, direct-owner, or partial Dev host projection.

### 2.3 Deterministic clean-room decision

The clean-room bootstrap lane must enforce its existing offline claim rather than merely label it.
Its `run()` wrapper supplies fixture-local `HOME`, `XDG_DATA_HOME`, `XDG_CONFIG_HOME`,
`XDG_STATE_HOME`, and an intentionally unavailable `AWA_CLONE_URL` to **every** child command,
including both root-bootstrap runs, the GCB static check, the overlay static check, and repo-only
verification. It never inherits an operator-exported XDG or AWA clone path. It proves:

```bash
AWA_OFFLINE_CLONE="$TMP/offline/awa-unavailable"
test ! -e "$AWA_OFFLINE_CLONE"
run() {
  local n="$1"
  shift
  if
  HOME="$CRHOME" \
  XDG_DATA_HOME="$TMP/xdg-data" \
  XDG_CONFIG_HOME="$TMP/xdg-config" \
  XDG_STATE_HOME="$TMP/xdg-state" \
  AWA_CLONE_URL="$AWA_OFFLINE_CLONE" \
    "$@" >"$TMP/out" 2>&1
  then
    ok "$n"
  else
    bad "$n"
    sed 's/^/        | /' "$TMP/out" | tail -12
  fi
}
```

The override is nonempty and names an absent fixture-local path. Skills GCB therefore tries only
that local URL and cannot fall back to its SSH/HTTPS remotes. A git network sentry must additionally
fail the test if any clone/fetch URL has a network scheme or SCP-like remote syntax.

- no network AWA acquisition can occur;
- no AWA runtime, pointer, owner selection, hook backup, or partial hook matrix appears;
- overlay static deferral remains green and read-only; and
- the second run is byte-identical for the AWA-owned isolated paths.

The exact-release install/repair/doctor and rollback lanes remain separate disposable tests using
exact local AWA clones. Clean-room must not silently become a second release installer.

The overall clean-room currently has unrelated base failures. E-06 requires its dedicated AWA
assertions to pass and the complete base/head failure set to gain no candidate-owned row. It must
not relabel, suppress, or repair the unrelated continual-learning/doc-warden/manifests failures in
this PR. A new E-06 failure or a changed unrelated failure is a stop.

## 3. Exact implementation surface and tests

### 3.1 In scope

The complete v3 implementation surface is:

1. `bootstrap.sh` — immediate one-time transaction barrier and exit precedence;
2. `_ops/bin/install-dev-awa-overlay.sh` — preserved v2 offline validated-runtime behavior only;
3. `_ops/bin/install-worktree-hooks.sh` — preserved v1 atomic five-role transaction;
4. `_ops/tests/awa-host-overlay.sh` — transaction-order and interruption regressions;
5. `_ops/checks/worktree-verify.sh` — existing focused-test entrypoint; and
6. `_ops/eco/clean-room.sh` — deterministic isolated XDG roots and enforced no-network AWA lane.

No operator prose changes unless a pre-edit claim audit proves current copy false. The plan PR
itself changes only this file and `_ops/plans/README.md`.

### 3.2 Required focused regressions

Extend the existing hermetic root-bootstrap fixture before production edits:

- capabilities succeeds after installing external runtime: overlay completes before the first
  non-AWA step;
- capabilities returns nonzero after installing external runtime: overlay still completes, then
  root returns the captured capabilities failure without running a non-AWA step;
- overlay validation or hook transaction fails: root returns nonzero, no non-AWA step runs, and
  selected-hook existence/inode/mode/bytes/mtime plus backup inventory equal the preimage;
- a failure injected at every later root step sees an already-complete exact five-role matrix;
- offline with no runtime defers without any AWA host/runtime state;
- offline with a complete validated external runtime converges locally before later steps;
- direct owner, SSP selected-hook access, malformed hook JSON, pointer/contract drift, partial
  matrix, duplicate/stale role, candidate-write failure, and replace failure all fail closed;
- a second successful root run is byte-identical and creates no additional backup; and
- the exact external owner/policy/root values reach the Skills manifest’s AWA installer; and
- inline transaction bindings leave the caller’s pre-existing AWA owner/policy/root environment
  exactly restored before later non-AWA steps.

The clean-room regression must prove its unavailable local clone override was actually consumed,
that no network fallback occurred, that every child observed only fixture-local HOME/XDG roots,
and that all AWA isolated paths remain absent/unchanged across both runs. No test may read or write
the operator’s real home or any operator-exported XDG root.

### 3.3 Required unchanged surfaces and non-goals

- `capabilities/bootstrap.sh`, Skills, AWA, CPP, policy literals, delegators, GCB metadata/pin,
  contract, WF1/WF2, PR automation, and generated lock authority remain unchanged.
- Dev gains no AWA runtime, kernel, engine, consumer, contract, hook implementation, release
  pointer, second installer, registry, service, dependency, or generalized transaction framework.
- Root bootstrap never writes hook JSON, selects direct owner, claims an overlay failure succeeded,
  or continues into unrelated steps before the AWA barrier resolves.
- Clean-room does not change production install semantics, access private data, or repair unrelated
  base failures.
- No real `HOME`, `~/.cursor/hooks.json`, AWA XDG state, generated memory, E-07, E-08, E-09,
  static measurement, or context reduction is authorized.

## 4. Zero-context implementation pickup after acceptance

Do not execute this section until v3 is protected-merged and a fresh explicit E-06 v3
implementation GO names the two preserved checkpoints, the new transaction/clean-room surfaces,
and the unchanged real-home exclusion.

### 4.1 Re-prove both preserved branches

Require:

```text
impl/context-efficiency-e06-host-overlay
  = aed42b011cca0cbc1c45871af866321712ef0d64
  tree 17f06bb129c1fec4ba10d75a5bc0ecff13a67e8d

impl/context-efficiency-e06-host-overlay-v2
  = a0bd67e42b278fc9ae837e7a6163a404c29bdf7b
  parent 22748cd83836a1d9598a42bd9f431789738a8a76
  tree d8dfe2fd609f226972f9a1175c664594eaed2a35
```

Both trees must be clean and both refs absent from the remote. Any ref/tree/path/status mismatch is
a stop. Do not rebase, amend, reset, delete, or push either preservation branch.

### 4.2 Start a v3 successor branch

From a separate clean writer checkout:

```bash
git fetch --no-tags origin refs/heads/main:refs/remotes/origin/main
git merge-base --is-ancestor <v3-plan-merge> origin/main
_ops/bin/dev-worktree.sh ensure
git switch -c impl/context-efficiency-e06-host-overlay-v3 origin/main
git cherry-pick 22748cd83836a1d9598a42bd9f431789738a8a76
git cherry-pick a0bd67e42b278fc9ae837e7a6163a404c29bdf7b
```

Before v3 edits, compare all five resulting implementation blobs with the preserved v2 branch and
require no extra path. Then write the new focused regressions red-first, implement only §3.1, and
run the full verification below.

### 4.3 Verification and delivery

Required candidate evidence:

```bash
bash -n bootstrap.sh
bash -n _ops/bin/install-dev-awa-overlay.sh
bash -n _ops/bin/install-worktree-hooks.sh
bash -n _ops/tests/awa-host-overlay.sh
bash -n _ops/eco/clean-room.sh
bash _ops/tests/awa-host-overlay.sh
make worktree-verify
make eco-cleanroom
_ops/bin/doc-warden.sh check .
bash _ops/checks/doc-warden-verify.sh --sandbox
bash _ops/checks/doc-warden-verify.sh
make verify-ci
git diff --check
```

Run exact AWA v1.5.2 isolated install/repair/doctor, SSP zero-hook-access, five-role inventory,
second-run identity, and v1.5.1 staged-direct rollback exactly as required by v1/v2. Run exact
base/head differentials for every pre-existing full-gate failure. Candidate-owned failures block.

The implementation PR body records exact base/head/tree, changed-file hashes, both WIP checkpoint
refs, dependency refs, contract digest, red→green tests, transaction exit matrix, clean-room AWA
assertions, full failure differential, exact-release/rollback results, scope, and real-machine
exclusion. Open draft, run Bugbot, fix every applicable finding, run verification-before-completion,
mark ready, and steward through normal runnerless automation. The reviewer App alone may approve or
arm native auto-merge. Use normal owner merge only when the protected `_ops` gate requires it and
all Checks/comments are green; never admin-bypass a failure or comment.

Stop after the implementation merge and report the still-pending exact real-machine GO. Do not
perform real-home installation or start E-07/E-09.

## 5. Plan delivery and acceptance

This documentation PR changes only:

```text
_ops/plans/context-efficiency-e06-dev-host-overlay-v3.md
_ops/plans/README.md
```

While v3 is draft, the v2 index row remains `ACCEPTED`. Run:

```bash
_ops/bin/doc-warden.sh check .
bash _ops/checks/doc-warden-verify.sh --sandbox
bash _ops/checks/doc-warden-verify.sh
make worktree-verify
make verify-ci
git diff --check
```

For known base failures, require exact base/head differential and no candidate-owned row. Prove the
v1/v2 plan blobs and both implementation refs/trees remain unchanged after every plan commit. Open
draft, run Bugbot, and fix applicable findings while v3 remains `DRAFT`.

After Bugbot and verification-before-completion, set the v3 header exactly to
`**Status:** ACCEPTED — 2026-08-18`, set its index row to `ACCEPTED`, and change only the v2 index
row from `ACCEPTED` to `SUPERSEDED` with a link to v3. The v1 and v2 plan files themselves remain
byte-identical. Commit that immutable candidate, mark ready, and steward through normal Dev
runnerless automation/owner gate.

## 6. Rollback and stop conditions

### Plan rollback

Before protected merge, close or governed-revert this two-file documentation candidate. No
implementation or machine state changes. After acceptance, v3 is immutable; a material correction
requires v4 plus an index update.

### Implementation rollback

Before implementation merge, close or governed-revert the v3 candidate while retaining both local
checkpoints. After implementation merge but before machine install, use a normal governed revert PR.
Installed-state rollback remains E-06 v1 §6 and requires the separate exact machine authorization.

### Stops

Stop before implementation commit, push, PR, or machine write if:

- either immutable plan blob or preserved implementation ref/tree/path set changes;
- any exact dependency or relevant source blob drifts materially;
- any later root step can run before the AWA transaction barrier resolves;
- capabilities failure can bypass immediate overlay resolution after installing external runtime;
- a successful/continuing path has runtime/host ownership mismatch or an inexact five-role matrix;
- overlay failure mutates the selected-hook preimage or is softened into successful bootstrap;
- clean-room can reach an AWA network remote or leaves runtime/pointer/owner/hook residue;
- exact five-role convergence, atomicity, interruption safety, idempotence, offline truthfulness,
  exact-release integration, rollback, or base/head differential cannot be proven;
- a fix requires Skills, AWA, CPP, `capabilities/bootstrap.sh`, policy, delegator, PR-automation, or
  any file outside §3.1;
- Bugbot or any candidate-owned local/remote gate remains red; or
- any step would mutate real home/hooks, private/generated data, E-07, E-08, or E-09.

## 7. Acceptance criteria

- E-06 v1/v2 and both implementation checkpoints remain unchanged, clean, local, and unpushed
  during plan delivery.
- v3 and its `ACCEPTED` index row protected-merge while v2’s index row becomes `SUPERSEDED`.
- A fresh explicit E-06 v3 implementation GO is required after merge.
- Root bootstrap resolves the AWA runtime/host pair exactly once, immediately after capabilities,
  before unrelated work.
- Capabilities failure cannot skip AWA resolution; overlay failure cannot continue or mutate the
  hook preimage.
- Clean-room’s AWA lane is genuinely offline, deterministic, residue-free, and green; the complete
  failure differential gains no candidate-owned row.
- Skills remains the only runtime GCB and Dev remains a thin host overlay.
- No real-machine install occurs without the separate exact machine GO.
- E-07, E-08, and E-09 remain blocked.

Protected merge accepts only this scope decision. The exact resume step is a fresh explicit E-06 v3
implementation GO to create `impl/context-efficiency-e06-host-overlay-v3` from live main, cherry-pick
`22748cd` then `a0bd67e`, and execute §4 without real-home mutation.
