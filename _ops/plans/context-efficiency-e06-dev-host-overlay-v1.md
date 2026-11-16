# Context Efficiency E-06 — consume AWA v1.5.2 through Dev’s thin host overlay

**Version:** v1
**Status:** ACCEPTED — 2026-08-18
**Date:** 2026-08-18
**Owning repository:** `KleinPerkins/dev` (`~/dev`)
**Owner:** Laurence Duggan
**Program milestone:** Context Efficiency Program v2 `E-06`
**Plan-type:** standard
**Review provenance:** Authored from live Dev main, accepted ADR 0005 and Program v2, protected-merged M-04 evidence, the published AWA v1.5.2 release and exact `awa-hook-owner/v1` contract, protected-merged Skills E-05 plan and pin, current Dev overlay/installers/tests, and doc-warden policy. The operator requested this plan’s governed delivery while explicitly withholding E-06 implementation and real-machine installation.

**Goal:** Make Dev’s existing host overlay consume the Skills-pinned AWA v1.5.2 runtime in external hook-owner mode and atomically project the contract’s exact five logical roles into the host-owned Cursor user hook file.

**Architecture:** Skills remains the Global Capability Binding (GCB) that installs the independently released AWA Standalone System Package (SSP). Dev keeps only host policy literals, thin policy-injecting delegators, and the complete `~/.cursor/hooks.json` transaction. Dev reads and validates the installed AWA contract and release pointer; it does not copy the contract, kernel, engine, or hook behavior.

> **Authority boundary:** Acceptance of this plan authorizes no implementation, no real `HOME` or
> hook mutation, no AWA/Skills change, and no E-07 or E-09 work. E-06 implementation requires a
> separate explicit GO after this plan merges. A real-machine candidate then requires another GO
> naming the exact machine, commits, hook path, backup, and rollback command.

---

## 1. Exact authority and dependency binding

| Authority | Exact binding | Required fact |
|---|---|---|
| Dev planning base | `5bf8c65b093b7d240870a37a6821b5d4384642bb` | Live `KleinPerkins/dev` main when this plan was authored; tree `b3fcc7f3a9444c2693cd428502cb18232b0109e8`. |
| Dev active decision/program | ADR 0005 blob `8a031abff3fa3f17bba8e1606071e4414b5a1025`; Program v2 blob `d452a49a1f4e0eac579947a9a853637138966706` | E-06 scope, sequencing, evidence, rollback, and GO boundaries. |
| Dev M-04 | PR [#274](https://github.com/KleinPerkins/dev/pull/274), squash `4f1599137658f55cb0a065c505608cd3119d00bc` | Protected-merged correction evidence exists at `_ops/evidence/context-efficiency/correction-dogfood-v1.json` with `PASS` and `CORRECTION_PROVEN_NOT_E09`. |
| AWA E-04 implementation | PR [#112](https://github.com/KleinPerkins/awa/pull/112), squash `a2b13f7e7feb47f53ebb63ee59b4c61eb1e38fc3` | External hook ownership is implemented and its exact-head required Checks passed. |
| Qualified AWA release | [v1.5.2](https://github.com/KleinPerkins/awa/releases/tag/v1.5.2), lightweight tag → `a2b13f7e7feb47f53ebb63ee59b4c61eb1e38fc3` | Published 2026-08-17; non-draft, non-prerelease. |
| AWA hook-owner contract | `contracts/awa-contract.v1.json` at v1.5.2; SHA-256 `408e271e9f55269d276e6d34e2aa3bb2bbc072fea3b6c8a841ede1912978c4d9` | Canonical `awa-hook-owner/v1`, direct default, external zero-hook-file-access, and exact five roles. |
| AWA rollback release | v1.5.1 at `f4b3c9b85ea1cce83d00ab9eb9f26bf3be900342` | Last qualified direct-owner runtime and isolated prior-runtime rollback target. |
| Skills E-05 plan | PR [#142](https://github.com/KleinPerkins/skills/pull/142), squash `017b25b66604cf4fcf77826a1bcf930318f63b9c` | Accepted narrow pin plan. |
| Skills E-05 implementation | PR [#143](https://github.com/KleinPerkins/skills/pull/143), head `6cab54e50c7c8a1cb99322c6186a8496cde11a30`, squash/live main `c6e94f424898ba37ae12cbc264b138294564fa8b` | `global/tools/awa/meta.yml` and `tool.yml` bind exact AWA v1.5.2 commit; only the three pointer docs plus generated AWA lock row changed. |
| Current Dev overlay blobs | `install-dev-awa-overlay.sh` `9687dfbdb2373166e1afe698ff13ce538ad0d4e3`; `install-worktree-hooks.sh` `eb87455d18add2b3f2303b53639f94a36711a21c` | No diff on the overlay/install/test/operator-doc surfaces from M-04 merge through the planning base. |

Before implementation, fetch live Dev and Skills main and re-prove every row. The implementation
branch starts from then-live Dev main, not from the planning commit by assumption. A harmless Dev
advance requires rebase and full re-verification. A material change to the two installers, host
policy/delegators, AWA v1.5.2 tag/contract, Skills GCB pin, Program v2, or this plan requires a
successor plan.

Minimum dependency preflight:

```bash
set -euo pipefail
DEV_ROOT="$(git rev-parse --show-toplevel)"
test "$(git -C "$DEV_ROOT" remote get-url origin)" = \
  "git@github.com:KleinPerkins/dev.git"
git -C "$DEV_ROOT" fetch --no-tags origin \
  refs/heads/main:refs/remotes/origin/main
git -C "$DEV_ROOT" merge-base --is-ancestor \
  4f1599137658f55cb0a065c505608cd3119d00bc origin/main

test "$(gh api repos/KleinPerkins/skills/commits/main --jq .sha)" = \
  c6e94f424898ba37ae12cbc264b138294564fa8b
test "$(gh api repos/KleinPerkins/awa/git/ref/tags/v1.5.2 \
  --jq '.object.type + " " + .object.sha')" = \
  "commit a2b13f7e7feb47f53ebb63ee59b4c61eb1e38fc3"
test "$(gh api repos/KleinPerkins/awa/releases/tags/v1.5.2 \
  --jq '(.draft == false and .prerelease == false)')" = true
```

Use a clean exact Skills clone/worktree at `c6e94f…` and an exact AWA v1.5.2 clone for integration
evidence. The dirty or stale primary Skills/AWA checkouts are never cleaned, switched, stashed, or
used as candidate authority.

## 2. Verified gap, scope, and non-goals

### 2.1 Current gap

At the bound Dev base:

- `_ops/bin/install-dev-awa-overlay.sh` redirects the SSP’s hook destination to a throwaway file but
  does not select `AWA_HOOK_OWNER=external`; v1.5.2 can therefore persist `direct` while Dev later
  assumes external ownership.
- The overlay tolerates a failed GCB install and can continue to host-hook wiring without a
  validated runtime, release pointer, or owner selection.
- `_ops/bin/install-worktree-hooks.sh` projects only the three worktree policy roles. It does not
  install `recovery.maintenance` or `finish.prompt-recall`.
- Its `--check` accepts a completely absent AWA projection, and its install path recognizes rows
  by broad script basename instead of proving the stable role/event mapping.
- Malformed hook JSON is replaced with an empty object instead of being refused, and the final
  destination write is not a same-directory atomic replace.

The result is not jointly convergent with AWA v1.5.2: direct and Dev-delegated variants can coexist,
or the two product-owned roles can be absent.

### 2.2 In scope

Expected implementation files:

1. `_ops/bin/install-dev-awa-overlay.sh`
2. `_ops/bin/install-worktree-hooks.sh`
3. `_ops/tests/awa-host-overlay.sh` — new focused hermetic fixture and lifecycle test
4. `_ops/checks/worktree-verify.sh` — invoke the focused test from the existing owner gate

The implementation may update operator documentation only if a pre-edit exact-claim audit proves
that the implementation makes current copy false. The only eligible operator sources are
`OPERATING-MANUAL.md` §11 and the AWA host-binding paragraph in
`_ops/rules/agent-context.md`; changing the latter also requires its generated
`_ops/rules/dev-operating-model.mdc`. Current inspection found those statements accurate, so the
expected documentation diff is empty. Script comments are implementation documentation and may be
corrected within the two installer files.

### 2.3 Required unchanged surfaces

- `_ops/policy/worktree-policy.yml` and `_ops/policy/worktree-modes.yml` remain the Dev-owned host
  literals; no value change is required.
- `_ops/bin/dev-worktree.sh`, `_ops/cursor-hooks/worktree-guard.sh`, and
  `_ops/cursor-hooks/worktree-session.sh` remain thin policy-injecting delegators.
- Dev gains no `kernel/`, `engine/`, `consumer/`, runtime hook, contract, release-pointer, GCB
  metadata, or AWA source copy.
- Skills remains the only GCB/pin owner. Dev does not edit Skills, `.eco-registry.lock`, WF1/WF2,
  CPP, or the immutable AWA release.
- `bootstrap.sh`, PR-automation files, MCP wiring, dashboard behavior, AWA modes, generated memory,
  and private operator data remain unchanged.

### 2.4 Non-goals

This plan does not authorize:

- E-06 code, tests, install, repair, doctor, or rollback execution;
- any write to the real `~/.cursor/hooks.json`, real AWA XDG state, or real client configuration;
- changing AWA hook semantics, fail-open policy, finish authorization, recovery behavior, Git
  classification, or contract schema;
- a second runtime, contract copy, installer channel, registry, daemon, service, dependency, or
  generalized hook framework;
- installing directly from AWA instead of through the exact Skills GCB;
- E-07, E-08, E-09, static-context measurement, generated-memory access, or context reduction.

## 3. Binding five-role projection

The implementation consumes the installed contract and requires this ordered role set:

| Stable role ID | Event | Dev external projection | Exact required fields |
|---|---|---|---|
| `worktree.session-context` | `sessionStart` | Dev `_ops/cursor-hooks/worktree-session.sh` delegator | `type: command`; `timeout: 5`; `failClosed: false` |
| `worktree.shell-guard` | `beforeShellExecution` | Dev `_ops/cursor-hooks/worktree-guard.sh` delegator | `type: command`; `timeout: 20`; `failClosed: false` |
| `worktree.file-observer` | `afterFileEdit` | Dev `_ops/cursor-hooks/worktree-guard.sh` delegator | `type: command`; `timeout: 20`; `failClosed` absent |
| `recovery.maintenance` | `sessionStart` | installed AWA `kernel/hooks/awa-recovery-maintenance.sh` | `type: command`; `timeout: 5`; `failClosed: false` |
| `finish.prompt-recall` | `beforeSubmitPrompt` | installed AWA `kernel/hooks/before-submit-prompt.sh` | `type: command`; `matcher: UserPromptSubmit`; `timeout: 20`; `failClosed: false` |

Binding rules:

1. The installed contract must have schema `awa-hook-owner/v1`, mode set
   `["direct","external"]`, default `direct`, and
   `external_real_hook_file_writes:false`.
2. The installed contract’s raw SHA-256 must equal the installed
   `awa-release-pointer/v1.hook_owner_contract_sha256`; the release pointer commit and GCB pointer
   ref must equal the exact pin read from the Skills `meta.yml`.
3. The persisted selection and release pointer must both report `external` before Dev attempts the
   host hook transaction.
4. Dev derives entry fields and installed command roles from the installed contract. It hardcodes
   only the five accepted stable role IDs and the two Dev delegator mappings needed to inject host
   policy. It does not embed a contract JSON/prose copy.
5. Role identity is stable ID plus event, not command spelling. Direct installed-path,
   current/stale Dev-delegator, and duplicate variants of one role converge to one target row.
   Unrelated hook rows are preserved byte-for-data and in their existing relative order.
6. The candidate hook object must be valid `version:1` JSON with a `hooks` object and list/object
   entry shapes. Malformed input is a refusal with zero destination, backup, selection, or pointer
   mutation by the hook transaction.
7. A changed transaction creates one collision-safe backup, writes a same-directory candidate,
   validates it, atomically replaces the destination, preserves the prior file mode, and
   post-validates exact five-role inventory. An unchanged transaction writes no destination and
   creates no backup.

## 4. Implementation sequence

This entire section is zero-context executor pickup material for a later session. Do not run any
subsection unless the operator has separately and explicitly authorized E-06 implementation against
this accepted plan and a freshly reported dependency preflight. Plan acceptance, merge, or approval
does not supply that GO.

### 4.1 Create the safe writer branch

Only after that implementation GO, start from a clean Dev checkout:

```bash
_ops/bin/dev-worktree.sh ensure
```

Follow any printed Cursor root-move instruction before mutation. If Dev reports its umbrella-root
exclusion, remain in the dedicated clean checkout. Fetch live main, create a fresh E-06
implementation branch from that exact ref, verify the canonical noreply identity, and prove this
accepted plan’s merge is an ancestor. One writer uses this tree.

### 4.2 Add focused failing tests first

Create `_ops/tests/awa-host-overlay.sh` using only temporary Dev copies, temporary `HOME`/XDG roots,
local fixture repositories, and synthetic hook JSON. No test may read or write the operator’s real
home. Add it to `_ops/checks/worktree-verify.sh`.

Required expected-red cases:

- overlay passes explicit `AWA_HOOK_OWNER=external` through the Skills GCB on install and repair;
- GCB failure, missing runtime, malformed pointer, contract digest mismatch, or non-external owner
  leaves the hook file and backup set unchanged and exits nonzero outside the documented offline
  deferral;
- malformed hook JSON is refused without replacement;
- empty hooks, current three-role Dev state, direct five-role AWA state, mixed
  direct+delegated+product duplicates, stale Dev checkout paths, and already-converged host state
  all produce the exact five-role matrix;
- unrelated hooks, including unrelated commands on the same events, survive;
- no direct and delegated variant of one role coexists after convergence;
- changed install creates one valid backup and atomically replaces; injected candidate/rename
  failure leaves the original unchanged;
- install → doctor → second install → repair → doctor is byte-identical after the first successful
  convergence and creates no second backup;
- offline bootstrap/static check with no runtime remains a non-mutating honest deferral;
- `--check`/doctor fail on missing, duplicate, stale, wrong-field, wrong-event, or wrong-path role
  projection whenever external ownership is installed.

The synthetic fixture lane may model the GCB/runtime interface but may not contain copied AWA
kernel, engine, contract, or hook implementation bytes.

### 4.3 Make SSP ownership explicit and fail before host mutation

In `_ops/bin/install-dev-awa-overlay.sh`:

1. retain the Skills shelf as the only install entrypoint;
2. run its static `--check`;
3. invoke install/repair with `AWA_HOOK_OWNER=external`, `AWA_POLICY` pointing at Dev’s policy, and
   `AWA_GOVERNED_ROOT` pointing at Dev;
4. do not redirect the SSP to a throwaway live-hook substitute as the ownership mechanism;
5. outside explicit offline mode, treat any GCB/SSP failure as a stop before host hook wiring;
6. validate exact GCB pin, installed runtime/release/contract digests, owner selection, and external
   doctor state; then call the Dev hook transaction;
7. make overlay doctor require both AWA external-owner doctor success and exact host five-role
   inventory.

AWA in external mode must not read, stat, create, back up, chmod, rewrite, or remove the selected
hook file during install, repair, doctor, or uninstall. The integration evidence checks inode,
mode, bytes, mtime, and backup-set equality around each SSP lifecycle call.

### 4.4 Reconcile one complete host-owned matrix

In `_ops/bin/install-worktree-hooks.sh`:

1. load and validate the installed release pointer and installed contract;
2. build the five intended rows from §3;
3. parse the existing hook file strictly, preserving unrelated rows;
4. remove only proven variants of the same five stable role/event pairs;
5. stage, validate, back up, atomically replace, and post-check as §3 requires;
6. keep `beforeShellExecution` and `beforeSubmitPrompt` fail-open, keep
   `afterFileEdit` observation-only with no `failClosed`, and preserve exact timeouts/matcher;
7. make `--check` exact when an external owner/runtime exists while retaining a no-write,
   no-runtime static/fresh-machine result for CI and offline bootstrap.

No generic hook registry, embedded AWA behavior, or second contract parser is introduced. One
small stdlib parser/reconciler inside the existing host hook installer is sufficient.

### 4.5 Run exact-release integration and rollback rehearsal

Use disposable local clones only:

- Dev implementation candidate;
- Skills exactly at `c6e94f424898ba37ae12cbc264b138294564fa8b`;
- AWA v1.5.2 exactly at `a2b13f7e7feb47f53ebb63ee59b4c61eb1e38fc3`;
- prior AWA v1.5.1 exactly at `f4b3c9b85ea1cce83d00ab9eb9f26bf3be900342`;
- fresh temporary `HOME`, `XDG_DATA_HOME`, `XDG_CONFIG_HOME`, and `XDG_STATE_HOME`.

Required candidate lane:

```text
overlay --check
overlay install
overlay --doctor
overlay install
overlay --repair
overlay --doctor
```

Require exact checkout/GCB/release/contract identity, persisted external mode, SSP zero-hook-file
access, exact five roles, unrelated-row preservation, no stale/duplicate role, and second-run byte
identity.

Required rollback lane:

1. capture the pre-candidate hook bytes/mode/digest, GCB/release/selection pointers, checkout
   commit, and backup set;
2. use v1.5.2’s accepted non-live staging interface:

   ```bash
   AWA_HOOK_OWNER=direct \
   AWA_HOOKS_JSON="$STAGED_HOOKS" \
   "$AWA_HOME/kernel/hooks/install-hooks.sh"
   AWA_HOOK_OWNER=direct \
   AWA_HOOKS_JSON="$STAGED_HOOKS" \
   "$AWA_HOME/kernel/hooks/install-hooks.sh" --check
   ```

3. make the complete verified direct projection live atomically;
4. only then retire external ownership and reinstall/repair the captured prior runtime commit in
   direct mode;
5. restore the prior GCB pointer where one existed and require prior-runtime doctor plus exact
   role inventory;
6. prove the final hook/pointer/runtime state equals the captured pre-candidate state by semantic
   identity and required byte digests.

Never remove the active owner first. Never move or delete published v1.5.2.

### 4.6 Verify and deliver one later implementation PR

After separate implementation GO, the implementation PR must run:

```bash
bash -n _ops/bin/install-dev-awa-overlay.sh
bash -n _ops/bin/install-worktree-hooks.sh
bash -n _ops/tests/awa-host-overlay.sh
bash _ops/tests/awa-host-overlay.sh
_ops/bin/doc-warden.sh check .
bash _ops/checks/doc-warden-verify.sh --sandbox
make worktree-verify
make eco-cleanroom
make verify-ci
git diff --check
```

Run the exact-release integration and rollback lane separately with explicit exact clone roots.
`make eco-cleanroom` must use a clean candidate-aware Skills source, not the unrelated dirty primary
Skills checkout. If a full gate is red on head, run the identical command/environment at the exact
merge base and accept only an identical pre-existing differential; candidate-owned failures block.

The implementation PR body records exact base/head/tree, changed-file hashes, exact dependency
refs, contract digest, expected-red/green cases, static/offline result, isolated lifecycle
inventory, idempotence, rollback, doc audit, scope, and remote Check results. Open it draft, run
Bugbot, fix applicable findings, run verification-before-completion, then mark ready. The reviewer
App alone may approve or arm native auto-merge; the agent never approves, merges, bypasses, or arms
auto-merge.

## 5. Real-machine gate and receipt

Real-machine installation is a separate post-merge operation. Before asking for GO, the executor
must fetch exact merged Dev main, exact Skills main, and the immutable AWA tag; perform read-only
inventory; create no backup or candidate; and report:

1. exact machine identity in operator-recognizable terms;
2. Dev merge commit, Skills `c6e94f…`, AWA `a2b13f…`, and contract SHA-256;
3. real hook path and current file digest/mode, current five-role inventory, unrelated-row count,
   current runtime/checkout/pointer/owner state, and whether a prior rollback commit is locally
   resolvable;
4. proposed collision-safe backup path and verified rollback command sequence;
5. commands that will run and the exact allowed write roots; and
6. explicit exclusions: no Skills/Dev source edit, no generated memory, no E-07/E-09.

GO must name that exact machine, candidate commits, hook path, backup path, and rollback command.
A generic “go”, this plan’s acceptance, PR merge, or approval click is insufficient.

The exact-head rollback rehearsal must already have passed in the isolated lane from §4.5. Do not
execute a rollback against real home merely to prove it.

After GO, run one candidate transaction and one idempotent second pass. Produce a mode-0600,
machine-local, content-safe receipt under
`${XDG_STATE_HOME:-$HOME/.local/state}/awa/dev-overlay/` containing only:

- schema `dev-awa-overlay-install-receipt/v1`, status `PASS`, UTC time;
- exact Dev, Skills, and AWA commits plus contract digest;
- pre/post hook and backup SHA-256 values, with no hook rows or commands;
- `hook_owner_mode: external`;
- the ordered five stable role IDs;
- booleans for unrelated-row preservation, no duplicates, SSP zero-hook-file access,
  second-run byte identity, doctor pass, and exact-head isolated rollback rehearsal pass.

The receipt is private machine evidence, not a tracked artifact, registry, E-09 receipt, or
authorization for later tasks. A failed transaction emits no PASS receipt and immediately uses the
approved rollback.

## 6. Rollback

### Plan-only rollback

Before this plan is accepted, close or revert its two documentation files. After acceptance, this
v1 plan is byte-identical forever; a material correction requires
`context-efficiency-e06-dev-host-overlay-v2.md` plus an index update.

### Implementation-source rollback

Before implementation merge, close or revise the candidate branch. After merge but before any
real-machine install, revert the implementation PR through a normal governed Dev PR. No machine
state changed.

### Installed-state rollback

Use the exact staged-direct ordering in §4.5: verify a complete direct owner, atomically make it
live, then retire external ownership and restore the prior runtime/GCB pointer. Finally run prior
runtime doctor, exact five-role inventory, and pre/post digest checks. If no prior runtime existed,
restore the exact hook preimage first, uninstall the external candidate without hook-file access,
and prove the previously absent pointer/runtime state.

Rollback failure is a stop: preserve the current complete owner, retain all backups and state, and
do not continue, uninstall, or start E-07/E-09.

## 7. Stop conditions

Stop before commit, push, or any machine write if:

- an exact dependency in §1 is missing, moved, unmerged, or materially superseded;
- the Skills checkout is not exactly `c6e94f…` for integration, or its GCB pin differs from
  `a2b13f…`;
- AWA’s tag, version, contract schema, contract digest, role set, or external zero-write promise
  differs;
- implementation requires any file outside §2.2 without proven operator-doc staleness;
- Dev would gain AWA kernel, engine, consumer, runtime hook, contract, or GCB bytes;
- the SSP touches the selected hook file in external mode;
- malformed input, failed GCB/doctor/validation, or incomplete runtime can reach host hook mutation;
- exact five-role convergence, unrelated-row preservation, atomicity, idempotence, or rollback
  cannot be proven in isolated roots;
- `make eco-cleanroom`, a candidate-owned gate, Bugbot, or exact-head remote Checks remain red;
- the real machine, hook path, backup, write roots, or rollback command are not named exactly; or
- any step would access generated memory, private operator data, E-07, E-08, or E-09.

## 8. Acceptance criteria

- This plan and its index row are protected-merged before implementation begins.
- E-06 implementation remains limited to the two installers, one focused test, one existing test
  gate invocation, and only proven-stale operator docs.
- Skills GCB is the only AWA install path; exact v1.5.2 pin/contract identity is verified.
- AWA persists/reports external ownership and performs zero selected-hook-file access.
- Dev atomically owns one complete five-role projection while preserving unrelated hooks.
- No direct/delegated duplicate, stale AWA path, malformed rewrite, owner gap, or partial matrix is
  possible through the tested paths.
- Static/offline, isolated install/repair/doctor, exact inventory, second-run byte identity,
  candidate-aware clean-room, prior-runtime rollback, owner gates, and remote Checks pass.
- No real-home mutation occurs without the separate exact machine GO and content-safe receipt.
- No AWA/Skills/CPP source, generated memory, E-07, E-08, or E-09 work is performed.

Acceptance of this plan clears only E-06’s planning prerequisite. It does not authorize the E-06
implementation or real-machine installation.
