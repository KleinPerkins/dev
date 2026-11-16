# Context Efficiency E-06 v2 — close the bootstrap external-owner gap

**Version:** v2
**Status:** ACCEPTED — 2026-08-18
**Date:** 2026-08-18
**Owning repository:** `KleinPerkins/dev` (`~/dev`)
**Owner:** Laurence Duggan
**Program milestone:** Context Efficiency Program v2 `E-06`
**Plan-type:** standard
**Supersedes:** [E-06 Dev host-overlay v1](context-efficiency-e06-dev-host-overlay-v1.md), which remains byte-identical history
**Review provenance:** Live Dev main, accepted ADR 0005 and Program v2, immutable E-06 v1, the preserved local implementation checkpoint, the root/capabilities bootstrap call path, live Skills main and unchanged AWA shelf blobs, and published AWA v1.5.2.

**Goal:** Close the one-file scope gap in E-06 v1: Dev’s root `bootstrap.sh` must select AWA external hook ownership before its capabilities bootstrap can invoke the Skills AWA installer, so only Dev’s overlay performs the host hook transaction.

**Architecture:** E-06 v1 remains binding except for the explicit deltas in this successor. Skills remains the Global Capability Binding (GCB) that installs the standalone AWA runtime. Dev adds only bootstrap orchestration to its existing host policy literals, thin delegators, and complete `~/.cursor/hooks.json` transaction. Dev gains no AWA runtime, kernel, engine, contract, or hook implementation bytes.

> **Authority boundary:** This plan creates no implementation GO. The prior E-06 implementation GO
> was bounded by v1, which explicitly excluded `bootstrap.sh`; it cannot authorize this v2-only
> surface. After protected merge, a fresh explicit E-06 v2 implementation GO must name the
> `bootstrap.sh` scope delta and checkpoint pickup in §4. Acceptance does not authorize a real-home
> install or hook mutation, E-07, E-08, or E-09. A real-machine candidate still requires the
> separate exact machine GO defined by E-06 v1 §5.

---

## 1. Exact authority and preserved checkpoint

| Authority | Exact binding | Required fact |
|---|---|---|
| Dev planning base | `d3942643ceb0e60534238f142c71cd2e818c65ee`; tree `686d10a864b17f5ce678afca99ceb4a17720ba5b` | Live Dev main when this successor was authored; E-06 v1 is accepted there. |
| Active decision/program | ADR 0005 + Context Efficiency Program v2 | Distributed ownership, thin Dev host overlay, explicit machine gates, and E-06-before-E-07/E-09 sequencing remain unchanged. |
| Immutable E-06 v1 | blob `a2fdf79146c8d8d1a48c2f9455b5766bcfdd6306` | Accepted plan stays byte-identical; this file and the plans index record supersession. |
| Root bootstrap | `bootstrap.sh` blob `fc3ab3bf9461075da8274b98f25260f36c73820d` | Calls `capabilities/bootstrap.sh` before `install-dev-awa-overlay.sh`. |
| Dev capabilities bootstrap | `capabilities/bootstrap.sh` blob `defdf6494818f775d8fb34e4853ce2fe64b4179e` | Delegates to Skills `bootstrap.sh --reconcile` and exits when the normal Skills bootstrap is present; it does not select AWA hook ownership. This file remains unchanged. |
| Skills bootstrap | `bootstrap.sh` blob `bc6d8e4a1ff73272aea14e592963e603097bcca0` at E-05 and live Skills main | `--reconcile` runs the shelf manifest pass, which invokes the Flavor-2 AWA `install.sh` and inherits caller environment. This file remains unchanged. |
| Preserved implementation checkpoint | local commit `aed42b011cca0cbc1c45871af866321712ef0d64`; parent `d3942643ceb0e60534238f142c71cd2e818c65ee`; tree `17f06bb129c1fec4ba10d75a5bc0ecff13a67e8d` | Clean branch `impl/context-efficiency-e06-host-overlay`; four v1-authorized files only; intentionally unpushed and not a PR. |
| Qualified AWA release/contract | v1.5.2 at `a2b13f7e7feb47f53ebb63ee59b4c61eb1e38fc3`; contract SHA-256 `408e271e9f55269d276e6d34e2aa3bb2bbc072fea3b6c8a841ede1912978c4d9` | `direct` is the fresh default; `external` promises zero selected-hook-file access and exposes the accepted five roles. |
| Skills E-05 implementation | `c6e94f424898ba37ae12cbc264b138294564fa8b` | Qualified AWA v1.5.2 GCB pin. |
| Live Skills main at authoring | `fd3e2b46efae5702de2faffb801744923d9416b7`; tree `88665d11bf1a03f6707a161bf00f203f3ad0efff` | E-05 is an ancestor. The later continual-learning change leaves AWA `meta.yml`, `tool.yml`, and `install.sh` blobs unchanged at `bd7cf42d…`, `efad28b0…`, and `a829b5b…`. |

The original checkpoint is preservation evidence, not remote authority. Until this plan merges:

- do not switch, reset, rebase, amend, delete, push, or open a PR from
  `impl/context-efficiency-e06-host-overlay`;
- require its branch ref, commit, parent, tree, status, and four-path diff to match the table above;
- keep plan work in a separate clean checkout/branch from exact Dev main; and
- do not cherry-pick implementation into this documentation PR.

A harmless Dev or Skills advance requires re-fetch and exact relevant-blob comparison. A material
change to `bootstrap.sh`, `capabilities/bootstrap.sh`, the E-06 surfaces, the AWA shelf/pin,
v1.5.2 tag/contract, ADR 0005, Program v2, or either E-06 plan stops implementation and requires
another successor.

## 2. Proven contradiction and minimal scope delta

### 2.1 Call-path evidence

On the bound Dev base:

1. root `bootstrap.sh` step 1 runs `bash "$ROOT/capabilities/bootstrap.sh"`;
2. Dev capabilities bootstrap delegates to
   `capabilities/skills/bootstrap.sh --reconcile` and exits;
3. Skills `--reconcile` runs its shelf manifest pass, which invokes the Flavor-2
   `global/tools/awa/install.sh`;
4. no caller has set `AWA_HOOK_OWNER=external`, so AWA uses its contract default `direct`; and
5. only later does root bootstrap step 7 run `install-dev-awa-overlay.sh`.

The SSP can therefore read or write the selected Cursor hook file before Dev’s external-owner
overlay is invoked. E-06 v1 requires zero SSP hook-file access behind the overlay but lists
`bootstrap.sh` as unchanged, so the implementation cannot honestly satisfy both clauses.

### 2.2 In scope

The complete implementation surface becomes:

1. `bootstrap.sh` — the only new v2 surface;
2. `_ops/bin/install-dev-awa-overlay.sh`;
3. `_ops/bin/install-worktree-hooks.sh`;
4. `_ops/tests/awa-host-overlay.sh`;
5. `_ops/checks/worktree-verify.sh`; and
6. operator docs only if the v1 pre-edit claim audit proves current copy false.

`bootstrap.sh` changes only enough to pass Dev’s exact external-owner selection and existing host
policy/root bindings into the capabilities bootstrap invocation before any AWA installer can run.
The later overlay step remains the only complete host-hook transaction.

### 2.3 Required unchanged surfaces and non-goals

- `capabilities/bootstrap.sh`, the Skills repository, AWA, CPP, WF1/WF2, and generated lock
  authority remain unchanged.
- Dev gains no AWA runtime, kernel, engine, consumer, contract, release-pointer, GCB metadata,
  hook implementation, second installer, registry, service, dependency, or generic hook framework.
- Root bootstrap does not select `direct`, write AWA hook rows itself, or weaken AWA/overlay
  failures into a successful installed-state claim.
- Existing non-AWA capability bootstrap behavior and environment remain unchanged; the AWA
  owner/policy/root values are scoped to the capabilities-bootstrap child process.
- No real `HOME`, `~/.cursor/hooks.json`, AWA XDG state, private data, generated memory, E-07,
  E-08, E-09, static measurement, or context reduction is authorized.

## 3. Corrected bootstrap contract

The implementation must establish this order:

```text
Dev root bootstrap
  -> capabilities bootstrap with AWA_HOOK_OWNER=external
       + AWA_POLICY=<Dev host policy>
       + AWA_GOVERNED_ROOT=<canonical Dev root>
  -> Skills manifest invokes AWA GCB/SSP in external mode
  -> SSP installs/repairs runtime with zero selected-hook-file access
  -> Dev overlay validates GCB/release/contract/external selection
  -> Dev host transaction atomically reconciles the exact five-role matrix
```

Required behavior:

1. The first possible AWA GCB/SSP invocation receives `AWA_HOOK_OWNER=external`; relying on a later
   repair from `direct` is forbidden.
2. `AWA_POLICY` points to Dev’s tracked worktree policy and `AWA_GOVERNED_ROOT` points to the
   canonical root of the Dev checkout running bootstrap.
3. The scoped values do not leak into later non-AWA bootstrap steps.
4. During the capabilities-bootstrap AWA lifecycle, the selected hook file’s existence, inode,
   mode, bytes, mtime, and backup set remain unchanged.
5. Only the later Dev overlay may create a backup/candidate or replace the selected hook file.
6. Online completion requires the v1 external-owner validations and exact five-role projection.
7. Offline with no complete runtime remains an honest, non-mutating deferral. Offline with a
   complete, validated external runtime may perform the local Dev hook reconciliation without
   network; it must not be falsely classified as “no runtime.”
8. A failed or incomplete path never reports a passing overlay doctor/receipt and never permits a
   partial, duplicated, stale, or direct-owner final projection.

## 4. Zero-context implementation pickup after acceptance

Do not execute this section until this v2 plan is protected-merged and a fresh explicit E-06 v2
implementation GO names `bootstrap.sh`, checkpoint `aed42b0`, the successor implementation branch,
and the unchanged real-home exclusion. Plan acceptance or merge alone never supplies implementation
GO. The prior v1-bounded implementation GO cannot be reused because v1 forbids changing
`bootstrap.sh`. The request for this successor plan authorizes only plan delivery.

### 4.1 Re-prove and preserve the checkpoint

Locate the dedicated checkout that owns
`refs/heads/impl/context-efficiency-e06-host-overlay` (at authoring time,
`/Users/laurence.duggan/.cursor/dev-context-efficiency-20260809`) and run read-only checks:

```bash
set -euo pipefail
CHECKPOINT_ROOT="/Users/laurence.duggan/.cursor/dev-context-efficiency-20260809"
CHECKPOINT="aed42b011cca0cbc1c45871af866321712ef0d64"
test "$(git -C "$CHECKPOINT_ROOT" rev-parse \
  refs/heads/impl/context-efficiency-e06-host-overlay)" = "$CHECKPOINT"
test "$(git -C "$CHECKPOINT_ROOT" rev-parse "$CHECKPOINT^")" = \
  d3942643ceb0e60534238f142c71cd2e818c65ee
test "$(git -C "$CHECKPOINT_ROOT" rev-parse "$CHECKPOINT^{tree}")" = \
  17f06bb129c1fec4ba10d75a5bc0ecff13a67e8d
test -z "$(git -C "$CHECKPOINT_ROOT" status --porcelain)"
```

If the checkout moved, discover it read-only by its exact branch/commit; do not assume a new path.
Any missing object, moved ref, dirty tree, parent/tree mismatch, or extra checkpoint path is a stop.

### 4.2 Start the successor implementation branch and apply the checkpoint

Fetch Dev main and prove this plan’s merge commit is an ancestor. From a separate clean writer
checkout, run `_ops/bin/dev-worktree.sh ensure` and follow any root-move instruction. If Dev reports
its umbrella-root exclusion, remain in the dedicated clean checkout. Then:

```bash
git fetch --no-tags origin refs/heads/main:refs/remotes/origin/main
git switch -c impl/context-efficiency-e06-host-overlay-v2 origin/main
git cherry-pick aed42b011cca0cbc1c45871af866321712ef0d64
```

Do not rebase, amend, move, delete, or push the original checkpoint branch. The cherry-pick must
apply only these four paths:

```text
_ops/bin/install-dev-awa-overlay.sh
_ops/bin/install-worktree-hooks.sh
_ops/checks/worktree-verify.sh
_ops/tests/awa-host-overlay.sh
```

Compare each path’s post-cherry-pick blob with `aed42b0:<path>`; all four must match exactly before
adding v2 work.

### 4.3 Write the bootstrap regression first

Extend the existing hermetic fixture before changing production code. Run the actual root
`bootstrap.sh` from a temporary Dev fixture with:

- temporary `HOME`, `XDG_DATA_HOME`, `XDG_CONFIG_HOME`, and `XDG_STATE_HOME`;
- stubbed non-AWA bootstrap steps;
- the capabilities-bootstrap → Skills AWA shelf call shape;
- a hook-access sentry that records lifecycle order, owner/policy/root values, hook stat/digest,
  and backup inventory without copying AWA kernel/engine/contract/hook bytes.

Required expected-red assertions:

- the first AWA call currently observes absent/default-direct owner selection;
- the SSP can currently reach the selected hook file before the overlay;
- the corrected flow must instead observe external owner plus exact Dev policy/root;
- the selected hook preimage is unchanged through the SSP lifecycle;
- only the Dev overlay transaction changes it and produces the exact five roles;
- second root-bootstrap run is byte-identical with no additional backup;
- offline/no-runtime is non-mutating; offline/validated-external-runtime converges locally; and
- a direct owner, SSP hook touch, GCB failure, contract/pointer drift, malformed hook file, or
  partial final matrix fails closed.

No test may read or write the operator’s real home.

### 4.4 Make the smallest production correction

In `bootstrap.sh`, scope `AWA_HOOK_OWNER=external`, Dev’s policy path, and canonical Dev root to the
step-1 capabilities-bootstrap child process. Keep step 7 as the existing overlay entrypoint. Do not
special-case Skills internals, skip the AWA capability, duplicate the GCB, or write hook JSON in
root bootstrap.

If the new offline/validated-runtime case proves the checkpoint’s overlay defers incorrectly,
correct only that branch in `_ops/bin/install-dev-awa-overlay.sh`: network absence may defer runtime
acquisition, but it must not hide a complete local external runtime or bypass local validation.
No other checkpoint refactor is authorized.

### 4.5 Re-run v1 evidence and deliver one implementation PR

All E-06 v1 §§3–6 tests, exact-release integration, rollback, stop conditions, PR evidence, and
real-machine gate remain binding. Add:

```bash
bash -n bootstrap.sh
bash _ops/tests/awa-host-overlay.sh
make eco-cleanroom
```

The candidate-aware clean-room must exercise the actual offline root-bootstrap chain to green and
remain idempotent in isolated `HOME`. The focused hermetic root-bootstrap fixture—not clean-room's
static AWA checks—proves the first AWA lifecycle receives external ownership and performs zero
selected-hook-file access. Run the complete v1 verification matrix, exact base/head differential
for any pre-existing failure, `git diff --check`, data guard, and scope checks. The implementation
diff is limited to §2.2 and contains no accepted-plan edits.

Open a draft implementation PR only after this v2 plan is merged. Run Bugbot, fix every applicable
finding, run verification-before-completion, mark ready, and steward through normal runnerless
automation. The reviewer App alone may approve or arm native auto-merge. Use the repository’s
ordinary owner merge only when the `_ops` gate requires it and every required Check/comment is
resolved; never admin-bypass a failure or comment.

Stop after the merged implementation and report the still-pending exact real-machine GO. Do not
perform real-home installation or start E-07/E-09.

## 5. Plan delivery, verification, and acceptance

This documentation PR changes only:

```text
_ops/plans/context-efficiency-e06-dev-host-overlay-v2.md
_ops/plans/README.md
```

Before acceptance:

```bash
_ops/bin/doc-warden.sh check .
bash _ops/checks/doc-warden-verify.sh --sandbox
bash _ops/checks/doc-warden-verify.sh
make worktree-verify
make verify-ci
git diff --check
```

Prove the plan branch is not `impl/context-efficiency-e06-host-overlay`, the v1 plan blob is still
`a2fdf79146c8d8d1a48c2f9455b5766bcfdd6306`, the original checkpoint branch/ref/tree are unchanged
and unpushed, and the PR contains only the two paths above. Re-prove the checkpoint branch ref after
every documentation commit. Open draft, run Bugbot, fix applicable findings while this plan is
still `DRAFT`, and run verification-before-completion. Then set the plan header exactly to
`**Status:** ACCEPTED — 2026-08-18`, set its index row to `ACCEPTED`, change only the v1 index row
from `ACCEPTED` to `SUPERSEDED` with a link to v2, commit that immutable candidate, mark ready, and
steward through normal Dev runnerless automation. The accepted v1 file itself remains
byte-identical.

The agent does not approve, arm auto-merge, or bypass. A normal owner merge may be used only if the
protected `_ops` acceptance gate requires it after all exact-head Checks and comments are green.

## 6. Rollback and stop conditions

### Plan-only rollback

Before protected merge, close or revert this two-file documentation candidate; runtime and the
preserved checkpoint are unchanged. After acceptance, this v2 file is byte-identical forever; a
material correction requires v3 plus an index update.

### Implementation rollback

Before implementation merge, close or governed-revert the successor candidate while retaining the
original `aed42b0` branch. After implementation merge but before real-home install, use a normal
governed revert PR. Installed-state rollback remains exactly E-06 v1 §6.

### Stops

Stop before commit, push, merge, or machine write if:

- the v1 plan or original checkpoint ref/commit/tree/path set changes;
- the root call path or AWA default no longer matches §2.1;
- an exact dependency or relevant source blob drifts materially;
- a fix requires changing `capabilities/bootstrap.sh`, Skills, AWA, CPP, policy literals,
  delegators, PR automation, or any file outside §2.2;
- external selection is not present at the first AWA invocation;
- the SSP accesses the selected hook file in external mode;
- root bootstrap directly owns hook rows or Dev gains AWA runtime/contract/behavior bytes;
- exact five-role convergence, unrelated-hook preservation, atomicity, idempotence, offline
  truthfulness, candidate-aware clean-room, exact-release integration, or rollback cannot be proven;
- Bugbot or a candidate-owned local/remote gate remains red; or
- any step would mutate real home/hooks, private data, generated memory, E-07, E-08, or E-09.

## 7. Acceptance criteria

- E-06 v1 and checkpoint `aed42b0` remain unchanged and unpushed during plan delivery.
- This v2 plan and its `ACCEPTED` index row protected-merge while the v1 index row changes to
  `SUPERSEDED`; the immutable v1 file remains unchanged.
- A fresh explicit E-06 v2 implementation GO is required after merge; the prior v1-bounded GO does
  not authorize `bootstrap.sh`.
- `bootstrap.sh` is the only added implementation surface.
- The first possible Skills AWA install is explicitly external and has zero selected-hook-file
  access; only Dev’s overlay performs the complete host transaction.
- Skills remains the only runtime GCB; Dev remains a thin host overlay with no AWA behavior copy.
- The exact five-role, offline, idempotence, exact-release, rollback, verification, Bugbot, and
  normal runnerless delivery requirements pass on the successor implementation head.
- No real-home install occurs without the separate exact machine GO.
- E-07, E-08, and E-09 remain blocked.

Protected merge accepts the scope correction. The exact resume step is to request a fresh explicit
E-06 v2 implementation GO naming `bootstrap.sh`, checkpoint `aed42b0`, the successor branch, and
the unchanged real-home exclusion. Only after that GO may §4 resume. Plan merge does not supply
implementation GO or authorize real-machine installation.
