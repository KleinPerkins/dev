# Agent Worktree Automation (AWA): verified end-state architecture — v2.1

**Version:** v3
**Status:** DRAFT — AWA end-state architecture (v2.1 content; v1/v2 preserved under `archive/`)
**Date:** 2026-07-03
**Owning repository:** `KleinPerkins/dev` (`~/dev`)
**Plan-type:** standard

> **Status.** This is the hardened **v2.1** planning deliverable. It **layers on top of** v2
> (`archive/agent-worktree-automation-end-state-v2.md`, kept intact for diffing) and v1
> (`archive/agent-worktree-automation-end-state-v1.md`), folding in a completed **5-persona adversarial
> pre-mortem swarm**. It is a **planning document**, not an implementation: no daemon/engine is
> built here, and the shipped-defect fixes below are recorded as Phase-0 work items, not executed.
>
> **What changed from v2.** v2 corrected v1 against the real Cursor/OS/git surface. v2.1 does three
> things v2 did not: (1) closes the **promise↔mechanism honesty** gap (v2 re-blessed operator copy
> that promises protections the mechanism cannot deliver); (2) re-verifies every **dependency /
> rollout** claim against disk and finds several **stale** (the cpp `tool` gate is already flipped);
> (3) adds a **security verification ledger** and an **evidence-reproducibility** path, and demotes
> two "verified sound" claims to explicitly gated. It also freezes the **kernel-first architectural
> principle** (below). Each change cites `path:line` or command output.
>
> **Verification date / environment.** 2026-07-03 on macOS 26.5.1 (Darwin 25.5.0, arm64),
> git 2.50.1, python 3.14.2 / sqlite 3.53.2. Evidence re-derived by direct Read of the shipped shims
> and the governance ground-truth (cpp reconciler, ecosystem-orchestrator config) on this date.
> Cursor hook-API facts are snapshotted in `_ops/plans/evidence/hooks-doc-2026-07-03.md`.

## v2.1 architectural principle (frozen): kernel-first, engine off the safety-critical path

The USER's non-negotiable goal is the **full** end-state (daemon/engine/watcher/lease/MCP/recovery).
v2.1 keeps that goal **and** encodes the valid core of the first-principles critique **without**
deferring or deleting the engine:

- **The kernel delivers the full safety guarantee standalone.** The safety kernel = policy resolver
  + `beforeShellExecution` gate + git/worktree adapter (publish/adopt/attest) + recovery manager +
  minimal local guard + CLI + durable state. It must guarantee **detection, recovery, cleanup
  refusal, and safe lifecycle decisions with the daemon/engine OFF the safety-critical path** — if
  the engine is down, dead, or never started, the kernel (via the local guard reading atomic policy
  snapshots + `.awa/lease.json`) still denies primary mutation, still refuses unsafe cleanup, and
  still preserves work. This matches v2's degraded-mode matrix (v2 "Engine unavailable" row) and is
  now elevated to a **design invariant**, not a fallback.
- **Kernel ships first; the engine layers on for detection/bookkeeping/UX.** The daemon/watcher/MCP
  add continuous observation, richer state, orphan discovery, and better operator ergonomics — never
  a *new* safety dependency. Nothing the engine adds may become load-bearing for the core guarantee.
- **Kernel contracts are frozen before the engine is built.** The shim CLI + `awa-worktree/v1` JSON
  + guard `permission` schema + `.awa/lease.json` shape are pinned by a contract test (v2 Phase 0);
  the engine may only back them, never change them without a versioned bump. This is what lets the
  engine be added *behind* the kernel without regressing the green verifiers (v2 L25).

Framing: **"engine off the safety-critical path"** is the reconciliation of "build the whole thing"
with "don't make the guarantee depend on the most complex, least-proven layer."

## Changelog v2 → v2.1

Each row folds in one swarm finding as concrete plan text below. Severity mirrors the swarm.
Evidence is what was re-verified on 2026-07-03 (or marked **NEEDS RE-VERIFICATION** where a live
check — e.g. `gh`, a Desktop agent, or the unbuilt engine — is required).

| # | Change (swarm finding) | Severity | Lands in | Evidence (verified 2026-07-03) |
|---|---|---|---|---|
| H1 | **Copy-honesty gate** + rewrite of protection copy/invariant to true capability | CRITICAL | §H1 | v1:70,72 ("nothing lost"/"pristine"); v1:103 ("before local changes"); v2:211 ("saved a recovery patch"); mechanism gap v2 C4/L4; recovery unbuilt = v2 Phase 3 |
| H2 | **Agents-Window native = SOLE default relocation**; publish-then-move demoted to print-only fallback (never an automated push in the default flow); quarantine-ref + CI-skip + cleanup loop if ever pushed | CRITICAL | §H2 | v2 C2/L5 (`move_agent_to_root` fetch+ff-merge); live shim defect `_ops/bin/dev-worktree.sh:220,222` (`-b`) + `:244-252` (prints move, no push) |
| H3 | **Disable repo-controlled setup execution by default**; per-repo opt-in; never in included/foreign repos; threat model | CRITICAL | §H3 | `_ops/bin/dev-worktree.sh:225` (call) + `:255-263` (reads repo `.cursor/worktrees.json`) + `:264-338` (executes, incl `shell=True` `:307-311`); violates v1:868 ("no execution of repo-controlled hooks/config") |
| H4 | **Cluster D — Security** verification ledger; gate Phases 2/3/6; replaces self-referential "posture verified sound" | HIGH | §H4 | replaces v2:95-96; rows cite `.gitignore:40-75`, v1:859-860,864,867,869 |
| H5 | **Evidence reproducibility**: vendored hooks-doc snapshot + committed hook-probe harness; reclassify L3/L4/L9/L10 NEEDS RE-VERIFICATION | HIGH | §H5 | doc-only rows v2 L4/L9/L10; snapshot added `_ops/plans/evidence/hooks-doc-2026-07-03.md` |
| H6 | **Concurrency demoted** from "verified sound" to **gated on R-C**; fallback identity (path+branch+common-dir+boot-id, not bare pid); per-common-dir lock = collision boundary; daemon single-instance; WAL not on synced/network paths | HIGH | §H6 | v1:71 ("concurrent work is safe"); v2 R-C (no durable session id); v2 L17 (WAL) |
| D1 | **cpp `enabled_kinds` already flipped** — DELETE flip/await-reconciler steps; PR #170 = NEEDS RE-VERIFICATION | DEP | §D1, §R | `personal/ecosystem-orchestrator/config/relationship.yml:30` (`tool` present) + `:29` ("enabled after cpp PR #170 merged green"); reconciler on disk `affirm/src/card-platform-product/_ops/bin/eco-capability-reconcile.sh` |
| D2 | **`tool` kind vendors record-only to cpp** — re-scope cpp delivery as discoverability-only unless a cpp-OWNED tool-runtime installer is authored | DEP | §D2, §R | `eco-capability-reconcile.sh:65` (`tooling\|tool\|\|record`), `:52-56` (record=no native home), `:333-335` (record→continue, no install) |
| D3 | **Zero-link blocker** — global master must exclude cpp **generically** via governed-marker detector, never by literal; keep cpp/affirm literals in machine-local `_ops`; add `orchestrator zero-link --mode global` gate at packaging | DEP | §D3, §R | shim literals `dev-worktree.sh:121,125,140`, `worktree-guard.sh:83,87`, `awa-dashboard-data.py:38,88-91`; tokens `forbidden-cpp.txt:3-8`; detector `_ops/policy/worktree-policy.yml:33-36`; gate `ecosystem-orchestrator/bin/orchestrator.sh:169-173` |
| D4 | **Shelf timing** — create `capabilities/skills/global/tools/awa` shelf (meta.yml/install.sh) in **Phase 1**, not late packaging | DEP | §D4, §R | `ls capabilities/skills/global` → only `skills/` (no `tools/`); shelves per `_ops/POLICY.md:155-157`; `.eco-registry.lock` present, no `awa` enrolled |
| X | **Phase-0 shipped-defect fixes** (failClosed drift, afterFileEdit no-op, `clean` discards ignored, dashboard copy) | SHIPPED | §X | see per-defect citations in §X |
| R | **Corrected dependency-ordered rollout table** (folds D1–D4; pulls failClosed reconcile to Phase 0; native-adopt-primary to de-risk R-A) | DEP | §R | supersedes v2 rollout Phases 6,10,13 |

## §H1 — Copy-honesty gate + true-capability rewrite (CRITICAL)

**Problem (verified).** v2 preserved v1's operator promises as "verified sound" while v2's own
ledger says the mechanism cannot deliver them for the agent's **native** file edits, and the
recovery manager that would make "nothing lost" true is **unbuilt** (v2 Phase 3):

- "Primary checkout **stays pristine**" / "**Nothing gets lost**" (v1:70,72) — but v2 C4/L4 prove
  there is **no `beforeFileEdit`** and `afterFileEdit` is observation-only, so a native edit to
  primary **cannot be prevented**, only detected after the fact.
- "before local changes" (v1:103, the `ON`/Automatic mode copy) — implies pre-write prevention that
  does not exist for native edits.
- "I saved a recovery patch" (v2:211 degraded-matrix copy; v1:954 "save a patch") — asserts a
  recovery artifact whose manager is not yet built (v2 Phase 3), so the copy would lie until Phase 3.

**Fix — add a Copy-honesty gate to the rollout.** No operator-facing string containing a
**protection verb** may ship until the capability behind it passes a **named verifier**. The gated
verb set (case-insensitive, substring): `pristine`, `nothing lost` / `nothing gets lost`,
`saved a patch` / `saved a recovery patch`, `before local changes`, `can't be lost`, `protected`.

| Protection verb | Capability that must pass first | Named verifier gate | Until then, honest copy |
|---|---|---|---|
| "pristine" / "before local changes" (primary untouched) | shell-mutation gate live **and** native-edit detection wired | `worktree-verify` guard-behavior + hook-probe (§H5) | "I keep git/install commands out of your main folder, and I flag it if a file there changes." |
| "nothing lost" / "saved a recovery patch" | recovery manager builds + verifies a bundle/patch | recovery suite (v2 Phase 3) green | "I preserve committed work on a branch; uncommitted-file recovery is coming." |
| "protected" (unqualified) | kernel guarantee proven in target env | degraded-mode tests + env matrix | "Protection is active for shell commands here; native file edits are detected, not blocked." |

Mechanically: the dashboard/skill/rule copy strings live in one source table; a
`copy-honesty-check` (new `_ops/checks/` verifier, added when the copy table exists) greps the
operator-copy table for gated verbs and fails if the paired capability's verifier is not yet green.
This is a **rollout gate**, not runtime code.

**Rewrite the affected invariant + mode label.**

- v2 invariant "Primary-checkout **shell** mutation is denied … primary **file edits** are detected
  and recovered" is kept, but the operator-facing restatement becomes: *"AWA blocks mutating shell
  commands in your main folder and detects native file edits there; it cannot pre-block a native
  edit, and file-content recovery is available only once the recovery manager ships."*
- Relabel `ON` from "**Automatic** … before local changes" to "**Automatic (shell-gated)** — mutating
  commands enter a Safe Workspace; native edits to main are **detected**, not pre-blocked." The word
  "Automatic/ON" must not claim "before local changes" for the native-edit path.

**Status.** Copy defects **Verified** against v1/v2 text + v2 C4/L4. The gate + rewrites are new
plan requirements; the `copy-honesty-check` verifier is a Phase-0/6 work item (**NEEDS
IMPLEMENTATION**, not run here).

## §H2 — Agents-Window native as the SOLE default relocation (CRITICAL)

**Problem (verified).** v2's C2 fix made the agent-created default path *publish the branch to origin
before* `move_agent_to_root` (v2:138: `git push -u origin <branch>`). Forcing a push into the
**default** flow is harmful: it creates a surprise remote branch, triggers CI/webhooks/branch-
protection, breaks offline work, pollutes `origin` with no garbage-collection, and depends on the
still-open **R-A** (exact fetch/ff-merge trigger of the move). The live shim already exhibits the
underlying defect: `ensure` creates a local-only `-b` branch (`_ops/bin/dev-worktree.sh:220,222`)
and prints the `move_agent_to_root` instruction **without any push** (`:244-252`), so an agent that
follows the printed instruction hits the "Remote branch not found on origin" failure (v2 L5).

**Fix — reorder the relocation strategy so no automated push is in the default path.**

1. **Default (and strongly preferred): Cursor-native Agents-Window Worktree dropdown.** Cursor
   creates *and* moves into the worktree with no `origin` push; AWA **adopts** it (records lease,
   verifies, attests). This is now the **sole default** relocation path — it entirely avoids the
   `move_agent_to_root` fetch problem (v2 L5/L6) and the publish side effects.
2. **Fallback (rare, print-instructions-only): agent-created worktree.** When a mid-session move is
   unavoidable and the native dropdown is not available, AWA creates the worktree + branch off the
   pinned base and **prints** the exact steps for the operator/agent to follow. The default fallback
   **never performs an automated `git push`**; it surfaces `RELOCATION_MANUAL` with a copy-paste
   block and keeps the worktree. Relocating via `move_agent_to_root` on an unpublished branch is
   **not attempted** in the default fallback (it would fail per R-A/L5).
3. **Publish-then-move is opt-in only.** If — and only if — the operator explicitly opts into
   publishing to enable the move, AWA:
   - pushes to a **quarantine ref namespace** `refs/awa/<repo-key>/<lease>` (not a normal
     `refs/heads/*` branch), so it does **not** appear as a PR-able branch and does not trip
     branch-protection on `main`;
   - sets a **CI-skip** marker (`[skip ci]` trailer on the tip commit **and** documents the repo's
     CI path filter) so the quarantine push does not launch pipelines;
   - registers the pushed ref in an **origin-branch cleanup/retention loop** (watcher job: delete
     the quarantine ref once the lease is retired/landed, with a max-age retention cap);
   - shows **operator consent copy** before the push: *"To move this session I need to publish a
     temporary copy to the server (a hidden `awa/*` ref, no PR, no CI). Delete it automatically when
     done? Default: yes."*
   - on push failure (offline / no remote / remote down) surfaces `REMOTE_UNAVAILABLE`, keeps the
     worktree, and **never** reports a completed move.

**Environment-matrix consequence.** The v2 environment matrix row "Desktop, local repo → agent-
created (publish-then-move) **or** native dropdown" is replaced by: **native dropdown (adopt) is the
default; agent-created is a print-only fallback; publish-then-move (quarantine ref) is explicit
opt-in.** The Agents-Window row stays **preferred/default**. Cloud is unchanged (branch already on
origin).

**Shipped-code note (Phase-0/2).** The `dev-worktree.sh` `ensure` verb is the concrete site of the
C2 defect: it must (a) stop implying a working relocation from a local-only `-b` branch, and (b)
either adopt-native or emit the print-only fallback. Recorded as a Phase-0/2 code fix in §X, not
executed here. Cite: `_ops/bin/dev-worktree.sh:220,222,244-252`.

**Status.** Shim defect **Verified** (`dev-worktree.sh:220-252`). `move_agent_to_root` exact
fetch/ff-merge trigger remains **R-A (Unverifiable-now)** — which is *why* the default path must not
depend on it.

## §H3 — Repo-controlled setup config is code execution: disable by default (CRITICAL / security)

**Problem (verified — this is an RCE/worm vector).** `dev-worktree.sh ensure` calls
`run_worktree_setup "$top" "$path"` (`_ops/bin/dev-worktree.sh:225`). That function reads a
**repo-committed** config file — `$root/.cursor/worktrees.json` or `$wt/.cursor/worktrees.json`
(`:255-263`) — and **executes** its `setup-worktree` / `setup-worktree-unix` commands via
`subprocess.run(...)`, including a `shell=True` path when the config says
`{"shell": "...", "allowShell": true}` (`:307-311`, executed at `:319-337`). Because the config is
**inside the repo being worked on**, any repo that AWA operates on can run arbitrary commands on the
operator's machine the moment a worktree is created. Once AWA ships to other PMs, a single poisoned
`.cursor/worktrees.json` in any cloned repo becomes a **worm** — it executes on every teammate who
runs `ensure`. This directly violates v1's own security requirement **"no execution of
repo-controlled hooks/config during policy resolution"** (v1:868).

**Fix — repo-controlled setup execution is OFF by default.**

- **Default: do not execute repo-committed setup config at all.** `ensure` creates/adopts the
  worktree and stops; any setup is the operator's explicit action.
- **Opt-in is per-repo and operator-owned, stored OUTSIDE the repo.** Enabling setup execution for a
  given repo requires a machine-local allow entry (e.g. under `${XDG_CONFIG_HOME:-~/.config}/awa/`
  keyed by repo-key + a hash of the setup config), never a flag inside the repo. Changing the
  committed setup config **re-arms** the prompt (the stored hash no longer matches) so a malicious
  edit cannot silently ride an old approval.
- **Never auto-run in included/foreign/advisory repos.** Setup execution is refused outright for any
  repo classified `advisory` or `exclude`, for foreign-hook-framework repos, and for any repo the
  operator has not explicitly allow-listed — even if `include`.
- **When executed, it runs with a documented, least-privilege contract:** argv-only by default (no
  `shell=True` unless the operator opted into that repo *and* the specific `allowShell` entry),
  bounded timeout (existing `DEV_WORKTREE_SETUP_TIMEOUT`), no network unless the operator allows it,
  and full command text shown for consent.

**Threat model (documented in-plan).** Assets: the operator's machine + credentials + other repos.
Adversary: anyone who can land a commit in any repo AWA touches (incl. a compromised dependency or a
malicious PR branch a PM checks out). Vector: `.cursor/worktrees.json` → `run_worktree_setup` →
arbitrary code, amplified across PMs when AWA is a shared capability. Mitigation: default-off +
out-of-repo per-repo opt-in + re-arm-on-change + argv-only + classification refusal. Residual risk:
an operator who opts a repo in and then pulls a malicious setup edit is re-prompted (mitigated, not
eliminated). This threat model is a required section of the AWA security doc before Phase 6.

**Status.** **Verified** against `dev-worktree.sh:225,255-263,264-338` (esp. `shell=True` at
`:307-311`) and v1:868. Recorded as a Phase-0/2 code fix in §X (not executed here). Note: the shipped
`worktree-verify.sh:140-172` UATs currently *exercise* setup execution as expected behavior; those
UATs must be reframed to assert **default-off + opt-in** once the fix lands.

## §H4 — Cluster D: Security verification ledger (HIGH)

**Problem.** v2's only security statement is a **self-referential** bless: the "Preserved from v1"
bullet "Security & privacy posture … reinforced by L12" (v2:95-96) and the recommendation to trust
v1's security section. "Verified sound" cannot cite itself. v2.1 **replaces** that bullet with a
security ledger whose rows are individually verifiable, and gates the security-touching phases on it.

**Cluster D — Security ledger.** Status legend as in v2 (**Verified** / **Refuted** /
**NEEDS RE-VERIFICATION** = needs the unbuilt engine, a live probe, or a design decision).

| ID | Security assertion | Status | Evidence / method to close |
|---|---|---|---|
| S1 | Recovery bundles that capture untracked/ignored files won't leak **secrets/PII** into a source-tracked location. | **Verified (by construction) / gated (content capture)** | Bundles live under `${XDG_STATE_HOME:-~/.local/state}/awa` (outside any repo) and the allow-list `.gitignore` ignores `*.db/*.sqlite/*.env/*.pem/*.key/credentials*` etc. (`.gitignore:40-75`) so a bundle path can't be committed. **Open:** ignored-file **content** capture (v1:793,866) can still archive `.env`/keys *into the bundle file*; requires explicit consent (v1:866) **plus** a redaction/denylist pass mirroring `.gitignore:40-75` before archiving. Close: recovery-suite test that a seeded `.env`/`*.key` is refused or redacted. |
| S2 | **Symlink traversal** on worktree/recovery paths cannot escape the intended root. | **NEEDS RE-VERIFICATION** | v1:867 requires "path canonicalization and symlink traversal protection" but no shim enforces it today; `run_worktree_setup` and `clean` operate on caller-supplied paths. Close: canonicalize (`realpath`, reject paths whose real root ≠ expected) + a UAT with a symlinked worktree path and a symlinked file inside a bundle. |
| S3 | **GitHub token scope split** (read vs write) for push/PR. | **NEEDS RE-VERIFICATION** | v1:869 asks for least-privilege read/write split; unbuilt (no remote adapter yet). Close: remote adapter uses a read-scoped token for status/poll and a write-scoped token only for push/PR, verified in the apply-back suite. Interacts with §H2 quarantine-ref push (write path must be minimal). |
| S4 | **Socket + file permissions**: state/config/recovery dirs `700`, files `600`, Unix socket `600`. | **NEEDS RE-VERIFICATION** | v1:859-860 specify the modes; unbuilt. Close: engine sets umask + explicit `chmod` on create; doctor asserts modes; test on a fresh state dir. |
| S5 | **Audit-log PII**: no prompt/transcript/file-content in audit or command logs; secret/PII redaction. | **NEEDS RE-VERIFICATION** | v1:862-864 require no transcript capture + redaction; unbuilt. Close: audit writer runs a redaction pass; test that a seeded token in a command string is redacted in the audit record. |
| S6 | **Repo-controlled config is not executed** during policy resolution / worktree setup. | **Refuted (shipped) → fix in §H3** | `dev-worktree.sh:225,255-338` executes repo-committed `.cursor/worktrees.json`. Close: §H3 default-off + opt-in; UAT asserts default-off. |

**Gating.** Phase 2 (git/worktree lifecycle) is gated on **S2, S6**; Phase 3 (recovery manager) on
**S1, S5**; Phase 6 (Cursor hook adapters + any remote touch) on **S3, S4, S5** and the §H1
copy-honesty gate. No security-touching phase may be marked done while its Cluster-D rows are
NEEDS RE-VERIFICATION.

**Status.** S1/S6 **Verified**; S2–S5 **NEEDS RE-VERIFICATION** (each has a concrete close method).
This ledger **replaces** v2:95-96.

## §H5 — Evidence reproducibility: vendored hooks-doc + hook-probe harness (HIGH)

**Problem.** The load-bearing hook-capability rows (**L4**: no `beforeFileEdit`, `afterFileEdit`
observation-only, `stop` can't block, `loop_limit`; **L9/L10**: `beforeSubmitPrompt` Desktop-only,
user hooks/`stop`/MCP absent in cloud) are **doc-only** — their sole source was the live
`cursor.com/docs/hooks` page, which is **not vendored in-repo** and can drift silently. A plan that
gates enforcement on these facts must be able to reproduce them from the repo.

**Fix — two artifacts.**

1. **Vendored dated snapshot (added in this change):**
   `_ops/plans/evidence/hooks-doc-2026-07-03.md` captures the exact event/permission/cloud facts
   L2–L4/L9/L10 depend on, framed honestly as doc-derived (not a probe), with a supersede-on-change
   rule. This makes the plan's evidence readable without a network fetch.
2. **Committed hook-probe harness (work item):** a minimal **logging project hook**
   (`.cursor/hooks.json`-registered command hook) that, for each event it is wired to, records the
   event's **stdin payload** and — for gating events — **whether a returned `permission` is actually
   honored** by Cursor. Running it on a disposable Desktop agent (and a cloud agent) is the
   **reproducible evidence** that promotes L3/L4/L9/L10 from doc-claim to observed fact. It also
   closes **R-B** (does `afterFileEdit` fire for Write/Edit/apply-model, and its latency) as a
   byproduct. The harness lives with the AWA package tests; it is read-only (logs only, never
   blocks) and self-cleaning.

**Reclassification (until the probe runs).** The following v2 rows are downgraded in v2.1:

| Row | v2 status | v2.1 status | Promotes to Verified when |
|---|---|---|---|
| L3 (hook set + `beforeSubmitPrompt` shape) | Verified | **NEEDS RE-VERIFICATION** | probe logs each event's stdin on Desktop |
| L4 (`afterFileEdit` obs-only; `stop` can't block; no `beforeFileEdit`) | Refuted | **NEEDS RE-VERIFICATION** | probe shows a returned `permission` on `afterFileEdit` is ignored, and a `stop` `followup` does not block |
| L9 (`beforeSubmitPrompt` Desktop-only, DIY intent) | Refuted (scope) | **NEEDS RE-VERIFICATION** | probe present on Desktop, absent in cloud |
| L10 (user hooks absent in cloud) | Refuted | **NEEDS RE-VERIFICATION** | cloud project-hook probe confirms which events fire |

These reclassifications **do not** change v2.1's design (it already assumes the pessimistic reading —
only `beforeShellExecution`/`beforeMCPExecution`/`beforeReadFile` truly block); they make the
*evidence* honest. The snapshot file is committed with this plan; the probe harness is a Phase-6
work item (**NEEDS IMPLEMENTATION**).

## §H6 — Concurrency: demote to gated-on-R-C; real identity + collision boundary (HIGH)

**Problem.** v2 preserved v1's "**Concurrent work is safe**" (v1:71) as verified sound. It is not
yet provable: v2's own **R-C** is open — *there is no documented, durable, cross-surface session/
agent id* (Desktop / Agents Window / Cloud), and cloud omits `sessionStart` entirely. Lease
ownership keyed on a weak/absent id can mis-attribute or collide. So concurrency safety is **gated**,
not verified.

**Fix — specify the fallback identity and the real collision boundary.**

- **Demote the guarantee.** "Concurrent work is safe" moves from "verified sound" to **gated on
  R-C**; the operator-facing promise is qualified until R-C closes (per §H1 copy-honesty).
- **Fallback identity (never a bare pid).** Lease ownership identity =
  `hash(worktree_path + branch + git_common_dir + boot_id)`. Rationale: a bare pid is reused across
  reboots and across processes; `boot_id` (macOS: `kern.boottime` / a per-boot nonce) disambiguates
  reboots; `git_common_dir` ties the lease to the actual repo; `worktree_path + branch` make it
  unique per Safe Workspace. When Cursor *does* expose a stable session id (to be confirmed by the
  §H5 probe across surfaces), it is added as a **stronger** signal but the derived identity remains
  the floor.
- **The per-`--git-common-dir` advisory lock is the real collision boundary.** Two agents can only
  collide by mutating the **same** git object store; serialize all state-mutating lease operations on
  a lock keyed by the canonical `git rev-parse --git-common-dir` (the shim already resolves this:
  `dev-worktree.sh:61-70`; emitter `awa-dashboard-data.py:172-182`). Branch/path uniqueness is
  necessary but the common-dir lock is what actually prevents index/ref races.
- **Daemon single-instance.** The engine must guarantee one writer: bind an **exclusive Unix socket**
  (or hold an **flock’d pidfile**) at startup and refuse to start a second instance; **all** state
  writes go **through the daemon** (or, when the daemon is off, through the local guard holding the
  same per-common-dir lock — never a second concurrent writer). This is the concurrency counterpart
  to the §-principle "engine off the safety-critical path": the guarantee holds whether writes go via
  daemon or guard, but never both at once for one common-dir.
- **SQLite WAL placement.** WAL requires the `-wal`/`-shm` sidecars to share a filesystem with real
  POSIX locking; they **must not** live on a cloud-synced (iCloud/Dropbox) or network path or WAL
  corrupts. Pin `state.db` (and sidecars) under `${XDG_STATE_HOME:-~/.local/state}/awa` on local
  disk and have `doctor` refuse/warn if that path resolves onto a synced/network mount. (v2 L17
  confirmed WAL works; v2.1 adds the placement constraint.)

**Status.** Concurrency safety **gated on R-C (Unverifiable-now)**; identity/lock/daemon/WAL specs
are new design requirements. Shim common-dir resolution **Verified** (`dev-worktree.sh:61-70`,
`awa-dashboard-data.py:172-182`).

## §D1 — cpp `enabled_kinds` for `tool` is ALREADY flipped: delete the gate steps (DEP)

**Re-verification (refutes v2 C8/L14).** v2 said cpp `enabled_kinds` for `tool`/`rule`/`sub-agent`
are "**not yet flipped** (blocked on the cpp-governed reconciler PR)." On disk, 2026-07-03:

- `personal/ecosystem-orchestrator/config/relationship.yml:30` →
  `enabled_kinds: skill mcp rule sub-agent tool` — **`tool` is present** (so are `rule`,
  `sub-agent`). This file is the SoT for `enabled_kinds` (its header: "THE ld↔cpp relationship …
  Read by bin/orchestrator.sh"; `_ops/POLICY.md:175-176`).
- `relationship.yml:29` comment: *"Phase-2 routing kinds were enabled after cpp PR #170 merged
  green."*
- The cpp-governed reconciler is **present and built** at
  `affirm/src/card-platform-product/_ops/bin/eco-capability-reconcile.sh`, with routing for
  `skill|mcp|sub-agent|rule|tool` (`:61-65`) and a test `_ops/tests/test_eco_reconcile.sh`.

**Fix.** DELETE the "flip `enabled_kinds` / await the cpp-governed reconciler PR" steps from the cpp
rollout phase (v2 Phase 13). The `tool` kind is enabled and the reconciler exists, so cpp vendoring
of AWA-as-`tool` is **no longer gated on that flip** (it remains gated on §D2 runtime routing, WF1
enrollment, zero-link §D3, and cpp integrity).

**Status.** `enabled_kinds` value **Verified** (`relationship.yml:30`) and reconciler presence
**Verified** (on disk). The *live GitHub merge state of PR #170* is **NEEDS RE-VERIFICATION** — `gh`
was not run in this planning pass; the config comment + on-disk reconciler are strong but indirect
evidence. Verify later with `gh pr view 170 --repo Affirm/card-platform-product`.

## §D2 — `tool` kind vendors **record-only** to cpp: re-scope delivery as discoverability-only (DEP)

**Re-verification.** The cpp reconciler's routing table maps the `tool` kind (category `tooling`) to
link-shape **`record`**:

- `eco-capability-reconcile.sh:65` → `tooling|tool||record|||cursor claude codex`
- `:52-56` comment: `record -> no native home managed this round`
- install loop `:330-341` → `case "$link_shape" in … record) continue ;;` — a `record` item is
  **never** symlinked into a tool runtime home; it is logged for discoverability only
  (`:429-431`: "record-only for <tool> (no native home managed)").

So even though `tool` is in `enabled_kinds` (§D1), an AWA `tool` vendored into cpp lands as a
**discoverability descriptor**, not an installed runtime, on a teammate's laptop.

**Fix.** Re-scope cpp delivery of AWA as **discoverability-only** (a README/descriptor in
`cpp/quiver/tooling/awa`, mirroring how `kind: mcp` is vendored source-free) **unless and until a
cpp-OWNED tool-runtime installer is authored** to actually install/run the AWA engine on a cpp PM's
machine. That installer is **cpp control-plane, cross-org, and outside LD's authority** — it cannot
be written by the orchestrator or from `~/dev`; it is a cpp-team dependency. Until it exists,
teammate rollout means "AWA is discoverable in cpp," not "AWA runs for cpp PMs."

**Status.** **Verified** (`eco-capability-reconcile.sh:52-65,330-341,429-431`).

## §D3 — Zero-link: exclude cpp generically, never by literal (DEP)

**Re-verification.** A global capability master must contain **zero** cpp/affirm tokens
(**INV-zero-link**, `_ops/POLICY.md:182-184`), enforced by `orchestrator zero-link --mode global`
(`personal/ecosystem-orchestrator/bin/orchestrator.sh:169-173`; `lib/common.sh:121-140`) against the
token list `config/forbidden-cpp.txt:3-8` (`card-platform-product`, `affirm/(src|vendor)`, bare
`cpp`, `cpp-stuff`). **The shipped shims hard-code exactly these forbidden tokens:**

- `_ops/bin/dev-worktree.sh:121` (`affirm/vendor/*`), `:125`
  (`affirm/src/card-platform-product` + `affirm/card-platform-product`), `:140` (`affirm/src/*`).
- `_ops/cursor-hooks/worktree-guard.sh:83` (`$HOME/dev/affirm/src`), `:87`
  (`card-platform-product`, `affirm/vendor`).
- `_ops/bin/awa-dashboard-data.py:38` (`affirm/src`), `:88-91`
  (`affirm/vendor/`, `affirm/src/card-platform-product`, `affirm/card-platform-product`).

A global AWA master built by lifting these shims verbatim would **trip `zero-link --mode global`**
and could never be vendored.

**Fix.** The global AWA master must decide cpp-exclusion **generically**, never by literal:

- Exclude a repo when it carries a **governed-marker** — the detector already exists in policy:
  `_ops/policy/worktree-policy.yml:33-36` (`detectors.governed_markers: _ops/POLICY.md,
  _ops/ci/cpp-integrity-engine`). A repo that has its **own** `_ops/POLICY.md` (or the cpp integrity
  engine marker) is self-governed and AWA leaves it alone — this captures cpp **without naming it**.
- Keep **all** cpp/affirm literals in the **machine-local `_ops` policy** (this repo, never
  vendored) — `worktree-policy.yml:25-32` `exclude:`/`include:` may name `affirm/...` because `_ops`
  is not a global master. The generic detector lives in the master; the literal allow/deny list is a
  local override layer.
- Add an **`orchestrator zero-link --mode global`** gate to the AWA **packaging** phase (the moment
  the engine/CLI/hook source is assembled into `capabilities/skills/global/tools/awa`), so a literal
  can never slip into the master.

**Status.** **Verified** — forbidden tokens (`forbidden-cpp.txt:3-8`), the gate
(`orchestrator.sh:169-173`), the generic detector (`worktree-policy.yml:33-36`), and the shim
literals (cited above) all confirmed on disk.

## §D4 — `tools/` shelf must be created in Phase 1, not late packaging (DEP)

**Re-verification.** `capabilities/skills/global/` currently contains only `skills/` (plus a
third-party notices file) — **no `tools/` shelf** (`ls capabilities/skills/global` → `skills`,
`THIRD_PARTY_NOTICES-anthropic-skills.md`; no `global/tools` tracked in the skills repo per
`git -C capabilities/skills ls-files`). Kind shelves are `skills|rules|sub-agents|tools` and
`meta.kind` must match the shelf (`_ops/POLICY.md:155-157`). `.eco-registry.lock` exists at
`capabilities/skills/.eco-registry.lock` and enrolls **no** `awa` id.

**Fix.** Move "create `capabilities/skills/global/tools/awa` shelf + skeleton (`meta.yml`
[`kp-capability/v1`, `kind: tool`, `scope: global`] + paired idempotent `install.sh`)" to **Phase 1**
— it is a **prerequisite of building the engine in its final home**, not a late packaging step. You
cannot author the engine into `global/tools/awa` until the shelf exists. (WF1 enrollment in
`registry.yml` stays later — it is metadata governance, not a build prerequisite.)

**Status.** **Verified** (shelf absence via `ls` + `git ls-files`; `POLICY.md:155-157`;
`.eco-registry.lock` present, no `awa`).

## §X — Phase-0 immediate shipped-defect fixes (recorded, NOT executed here)

These are concrete, evidence-cited fixes to the **already-shipped** shims. They are **Phase-0 work
items** in this plan — do not execute them as part of writing v2.1.

**X1 — `failClosed` deployment drift.** The deployed `~/.cursor/hooks.json` sets
`failClosed: false` for the guard on **both** `beforeShellExecution` (`hooks.json:29`) and
`afterFileEdit` (`:36`), while `install-worktree-hooks.sh` writes `failClosed: true` for both
(`:50`, `:55`). *Fix:* re-run `install-worktree-hooks.sh` so the deployed value matches intent, **and
add a verify check** that asserts `deployed == intended` (parse `~/.cursor/hooks.json`, compare the
AWA guard entries' `failClosed` to the installer's constants). Note `failClosed` only affects the
hook-**failure** path, and it is a no-op on `afterFileEdit` (no gate) — so the correct intended value
is `true` on `beforeShellExecution` and *irrelevant* on `afterFileEdit` (prefer removing it there
per X2). Cite: `~/.cursor/hooks.json:24-37`, `_ops/bin/install-worktree-hooks.sh:47-56`.

**X2 — `afterFileEdit` `ask` is a no-op.** The guard is wired to `afterFileEdit`
(`hooks.json:31-37`; `install-worktree-hooks.sh:52-56`) and emits `permission: ask`
(`worktree-guard.sh:64-78,137-140`), but `afterFileEdit` is observation-only and Cursor **ignores**
the permission (v2 L4 / §H5). So the guard on that event does nothing useful. *Fix:* either (a)
**remove** the `afterFileEdit` wiring, or (b) replace it with a **detection-only recovery-diff
writer** (record "you edited primary", write a recovery diff/receipt — no `ask`). Then change
`worktree-verify.sh:211-219` so it **asserts the recovery artifact** was written on a primary
file-edit payload, **not** that the guard returned `ask` (the current assertion tests a no-op).
Cite: `worktree-guard.sh:135-142`, `worktree-verify.sh:211-219`, `hooks.json:31-37`.

**X3 — `clean` discards untracked/ignored on pushed/merged branches.** `clean_worktree` refuses only
on `git status --porcelain` dirtiness (`dev-worktree.sh:408-409`), which **does not list ignored
files**; if the branch is merged/pushed (`branch_is_cleanup_safe`, `:416`) it runs
`git worktree remove [--force]` (`:422-426`), deleting ignored/untracked content (e.g. `.env`, local
`*.db`, build output) with **no recovery bundle**. Also the default worktree root is
`~/.cursor/worktrees` (`:13`; `worktree-policy.yml:15`) — a Cursor-managed path subject to Cursor's
count/size cleanup, conflicting with the no-lost-work guarantee. *Fix:* before removal, **bundle-or-
refuse** — enumerate ignored/untracked via `git status --porcelain --ignored`, and either create a
recovery archive (with the §H4-S1 consent/redaction rules) or refuse; and **move the default
worktree root off `~/.cursor/worktrees` to a durable path** (`${XDG_DATA_HOME:-~/.local/share}/awa/
worktrees`, matching v2's service-model paths). Cite: `dev-worktree.sh:13,408-409,416,422-426`,
`worktree-policy.yml:12-15`.

**X4 — Dashboard: operator outcomes + promise/scope/degraded/stale cards.** `worktreeAction`
(`awa-dashboard.canvas.tsx:179-189`) returns **raw git verbs** ("Run `git worktree prune`", "Push or
open a PR before cleanup", "Clean with `dev-worktree.sh clean --path ...`") — the exact
implementation vocabulary the operator contract says to hide (v1:90-97). The canvas has a stale
indicator (`:310,391-395`) but **no promise-state cards** and **no explicit scope/degraded
indicators**. *Fix:* (a) re-render "Next action" as **operator outcomes** ("I'll keep this until it's
safely saved", "Ready to bring into main", "Nothing to do") with raw git behind a "details"
disclosure; (b) add **promise-state cards** — "Main folder: pristine / edited-and-recovered",
"Nothing-lost: N items preserved", "Concurrency: isolated" — each showing the *honest* state per §H1
(e.g. "detected, recovery pending" until Phase 3); (c) add explicit **scope** ("Desktop / Cloud /
CLI"), **degraded** ("engine off — kernel guard active"), and **stale** badges as first-class cards,
not just the existing age line. Cite: `awa-dashboard.canvas.tsx:179-201,310,391-395`.

## §R — Corrected dependency-ordered rollout (supersedes v2 rollout table)

Changes vs v2: **Phase 0** absorbs the `failClosed` reconcile + verify (X1) and the shim-contract
freeze; **Phase 1** creates the `global/tools/awa` shelf (D4) *before* engine work and adopts the
kernel-first principle; **Phase 2** adopts **native-window-first** relocation to de-risk R-A (H2) and
disables repo-config execution (H3); the security ledger (H4) gates 2/3/6; the cpp phase drops the
`enabled_kinds` flip (D1) and re-scopes to discoverability-only + zero-link gate (D2/D3).

| Phase | Deliverable | Hard dependency / gate | Verifier that must stay green |
|---|---|---|---|
| 0 | **This v2.1 plan** + shim-contract freeze (`dev-worktree.sh` CLI + `awa-worktree/v1` JSON + guard `permission` schema + `.awa/lease.json`); **X1 failClosed reconcile + deployed==intended verify check**; hooks-doc snapshot committed. | — | `make verify`, `make worktree-verify` |
| 1 | **Create `capabilities/skills/global/tools/awa` shelf** (`meta.yml` `kind:tool,scope:global` + `install.sh`) **[D4]**; kernel skeleton in its final home; **kernel-first principle frozen** (engine off safety path). | `_ops/POLICY.md:155-157`; D4 shelf | worktree-verify (shims unchanged) |
| 2 | Engine core + SQLite WAL (local-disk, **not synced/network** [H6]) + policy resolver + **per-common-dir lock as collision boundary** [H6]; git/worktree lifecycle with **native-window-adopt as sole default relocation** [H2] + **repo-config execution OFF by default** [H3] + attestation + `.awa/lease.json`. | Phase 1; **S2,S6** [H4]; R-A **not on default path** [H2] | worktree-verify UATs (reframed for X3 bundle-or-refuse + H3 default-off) |
| 3 | Recovery manager (bundles/patches/quarantine/restore) — **before** any destructive cleanup; **X3 bundle-or-refuse** in `clean`; durable worktree root off `~/.cursor/worktrees`. | Phase 1; **S1,S5** [H4] | new recovery suite |
| 4 | Watcher/enforcer (bounded loops; event-first) + health to decisions; **daemon single-instance (flock/socket bind)** [H6]; quarantine-ref cleanup loop [H2]. | Phases 2-3 | new watcher suite |
| 5 | Minimal local guard + CLI fallback (delivers the kernel guarantee with engine OFF). | Phase 1 | degraded-mode tests |
| 6 | Cursor hook adapters — honest capabilities only (shell gate + `afterFileEdit` **detect-only, X2**); **copy-honesty gate + copy rewrites [H1]**; **hook-probe harness [H5]** reclassifies L3/L4/L9/L10. | Phases 1,5; **S3,S4,S5** [H4]; L2 | worktree-verify (guard behavior, X2 asserts recovery artifact) |
| 7 | AWA MCP server (local stdio in `mcp.json`) + `beforeMCPExecution` gate (Desktop-only). | Phase 6 | MCP contract tests |
| 8 | Engine-backed dashboard — **operator-outcome copy + promise/scope/degraded/stale cards [X4]**; render-only + agent-command refresh. | Phase 4 | worktree-verify seed/marker checks |
| 9 | PR + SHA-bound apply-back (preview-first; recovery before mutation); **read/write token split [S3]**. | Phases 2-4 | apply-back suite |
| 10 | Packaging into `global/tools/awa`: no-clobber install/repair/uninstall; **`orchestrator zero-link --mode global` gate [D3]**; clean-room. | D3, D4 | eco-verify / clean-room / zero-link |
| 11 | Dogfood on one governed `~/dev` repo, then expand. | Phases 1-10 | dev-doctor advisory |
| 12 | **Cloud**: committed project `.cursor/hooks.json` (shell + `afterFileEdit`) + PR-first. | R-E; L10 (probe [H5]) | project-hook test in cloud |
| 13 | cpp rollout: WF1 enrollment (`registry.yml`) → orchestrator `cpp-sync` (zero-link + integrity gated). **`tool` `enabled_kinds` already flipped — no flip step [D1]**; delivery is **discoverability-only** unless a cpp-OWNED tool-runtime installer exists **[D2]**. | L21; zero-link [D3]; cpp integrity | eco-regression / cpp integrity |

## Non-negotiable invariants (v2.1 additions to v2's list)

v2's invariants stand; v2.1 adds/tightens:

- **Kernel-first / engine off the safety-critical path.** The safety guarantee holds with the
  daemon/engine/watcher OFF; the engine only observes/bookkeeps/eases. Kernel contracts are frozen
  before the engine is built.
- **No protection verb ships ahead of its capability.** Operator copy may claim "pristine" /
  "nothing lost" / "saved a patch" / "before local changes" only after the named verifier for that
  capability is green (copy-honesty gate, §H1).
- **No automated push in the default relocation path.** Native-window-adopt is the default; any push
  to enable a move is explicit opt-in, to a quarantine ref, CI-skipped, with consent + auto-cleanup
  (§H2).
- **No execution of repo-controlled config by default.** Worktree setup config runs only under an
  out-of-repo, per-repo, re-armed-on-change operator opt-in; never in advisory/exclude/foreign repos
  (§H3).
- **Global master carries zero cpp/affirm literals.** cpp exclusion is by governed-marker detector;
  literals live only in machine-local `_ops`; a `zero-link --mode global` gate enforces it (§D3).
- **One writer per common-git-dir.** Lease identity = path+branch+common-dir+boot-id (not bare pid);
  the per-common-dir lock is the collision boundary; the daemon is single-instance; WAL sidecars stay
  on local disk (§H6).

## How v2.1 was verified (method)

Read-only re-derivation on 2026-07-03: direct Read of every shipped shim
(`_ops/bin/dev-worktree.sh`, `_ops/cursor-hooks/worktree-{guard,session}.sh`,
`_ops/bin/install-worktree-hooks.sh`, `_ops/checks/worktree-verify.sh`,
`_ops/dashboards/awa-dashboard.canvas.tsx`, `_ops/bin/awa-dashboard-data.py`,
`_ops/policy/worktree-policy.yml`) and the deployed `~/.cursor/hooks.json`; direct Read of the
governance ground-truth (`AGENTS.md`, `_ops/POLICY.md`, `.gitignore`) and the **nested-repo**
dependency sources (`personal/ecosystem-orchestrator/config/{relationship.yml,forbidden-cpp.txt,
registry.yml}`, `personal/ecosystem-orchestrator/bin/orchestrator.sh`,
`affirm/src/card-platform-product/_ops/bin/eco-capability-reconcile.sh`); and OS/git probes
(`ls capabilities/skills/global`, `git ls-files`, `rg --no-ignore enabled_kinds`). Each finding cites
the `path:line` or command output it rests on. Items requiring a live tool not run here
(`gh pr view 170`, a disposable Desktop/cloud agent for the hook probe, the unbuilt engine) are
explicitly marked **NEEDS RE-VERIFICATION**. No code was changed; no `move_agent_to_root` was
executed (R-A). `make verify` + `make worktree-verify` re-run green after adding this doc + the
evidence snapshot.

