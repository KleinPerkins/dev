> HISTORICAL CONTROLLER REFERENCE. The installed controller is abandoned; the
> mutation commands described below are retired and must refuse. This material
> supplies compatibility/parser/test provenance, not operational instructions or
> authority to resume a service. Current policy: `_ops/POLICY.md` and
> `_ops/baseline/README.md`. PAC mini actions is planned development.

# Runnerless PR automation v3

This directory is the active central control plane for local, zero-Actions PR automation.
The v1/v2 files one directory above remain frozen only for compatibility cleanup and rollback.

## Authority

- `kleinperkins-verify-bot` (`4274739`) owns the stable `pr-automation / verify` Check.
- `kleinperkins-review-bot` (`4269364`) may arm native squash auto-merge and approve an exact
  ordinary head only after verification. Protected paths remain owner/admin-only.
- GitHub rulesets are the merge authority. The controller has no direct-merge operation.
- Missing/offline local verification leaves the required Check absent or pending.
- The managed default-branch ruleset is classified independently; unrelated branch and tag
  rulesets are never mutated and their IDs, targets, enforcement, and fingerprint remain attested.

**D1(b) (2026-07-30): `kleinperkins-review-gate` was excised fleet-wide.** The human/CODEOWNER
review requirement it enforced is retired — `kleinperkins-merge-safety` is now the *sole* managed
ruleset, since the reviewer App exclusively arms/approves squash auto-merge and a required human
review would block that automation. `merge-safety` alone still carries every real protection:
deletion + non-fast-forward blocked, linear history, resolved conversations, squash-only merges,
and the required `pr-automation / verify` Check. `review-gate.ruleset.json.tmpl` was deleted from
this directory; nothing under `v3/` can regenerate it. (The frozen Phase A/Phase B implementation
one directory above still contains its own copy of the template and ruleset-mutation code — see
that directory's own docs for its explicitly out-of-scope, compatibility-only status.)

**M4-B2 (2026-08-08): `kleinperkins-review-gate` was DELETED fleet-wide** (all 18 repos, not merely
disabled) — per-repository recreate-evidence committed first to `review-gate-evidence/{repo}.json`
(restorable in one call; see that directory's README). The stray `review-gate.placeholder.
ruleset.json.tmpl` (inert — nothing in `profile.py` ever read it) was removed from this directory as
part of the same cleanup, so the "nothing under `v3/` can regenerate it" claim above now holds
without exception.

## Runtime

- Controller host: the always-on **Linux VM (Hetzner)**. The Mac is **decommissioned as a controller
  host**. Sole-driver invariant: exactly **one** controller host runs the controller at a time.
- Release version, commit, controller digest, lock-compiler digest, lock-contract epoch, images, and
  fingerprint authority: verified `controller.json`. Do not duplicate rotating literals in prose.
  Policy `controller_release_digest` remains the separate binary-integrity binding; it is not lock
  payload provenance.
- Fetch: disposable networked Colima/VZ VM, one-repository contents-read token through stdin.
- Execute: a distinct credential-free VZ VM, no network, no host mounts, read-only root,
  non-root user, bounded tmpfs/resources, closed controller-owned modes.
- No GitHub-hosted or self-hosted Actions runner, workflow controller, repository App secret, or
  repository-local executable is part of v3.

## Files

- `fleet.json` / `fleet.schema.json` — target IDs, cohorts, exclusions, rollout state. **15 enrolled
  targets** at present; the fleet grows only by **enrollment** — add a target here, canary-qualify it,
  then explicit post-canary remote activation. The authoritative count lives only in `fleet.json`
  (not hardcoded in prose elsewhere), so it never drifts.
- `controller.json` / `controller.schema.json` — Apps, release, digest-covered lock-contract epoch,
  image, base fingerprints, and repository-ID-keyed fingerprint overrides. The committed override
  map is empty until a separately gated repository assignment and its pins land atomically.
- `repository-policy.schema.json` — closed `.github/pr-automation.json` contract.
- `verification-manifest.schema.json` — closed `.github/pr-verification.json` contract.
- `merge-safety.ruleset.json.tmpl` — the sole required ruleset (see D1(b) above:
  `review-gate.ruleset.json.tmpl` was excised, not just deactivated).
- `coverage-assignments.json` / `coverage-assignments.schema.json` — the v2 sole mutable assignment
  authority. `profile.py` projects it deterministically into each live repository's
  `coverage_assignment`; the optional closed `required_checks` manifest is absent from every
  committed assignment in this task, so the seam remains inert.
- `profile.py` — local `stage`/`verify`, the read-only remote policy/lock gate
  `verify-fleet-remote`, and the M2 coverage verbs below.
- `canary-evidence.json` — generation-1 rollback and generation-2 promotion evidence.
- `rollout-evidence.json` — exact-head Check/approval/merge/ruleset evidence plus blockers.

Run `python3 _ops/baseline/profiles/pr-automation/v3/profile.py verify-control-plane` (local), then
`python3 _ops/baseline/profiles/pr-automation/v3/profile.py verify-fleet-remote
--lock-compiler <qualified-path>` (read-only live policy parity plus current-default-branch recipe
binding and exact Rust lock recompilation).

## Coverage operator verbs

- `view` — reads dev, box, and assigned-repository parity; hard exclusions are shown as permanently
  un-promotable.
- `plan` — reads only merged default-branch state and prints exactly the next state-specific diff:
  recipe, lock, assignment, mode, or covered-semantics/epoch relock. It never guesses a future merge
  SHA or pins an unmerged/deleted recipe branch. A bare release-only change remains a policy
  rebind/deploy obligation but is not a relock trigger.
- `sync` — after a per-operation owner GO and a clear `make bind-guard`, stages exactly one
  `recipe | lock | assignment | relock` phase in one linked worktree. Combined recipe+lock or
  stale-base staging is refused.
- `activate` — `--phase stage` authors only the next monotonic mode assignment PR;
  `--phase transcribe` separately proves that exact assignment is merged, retains a `0600`
  prior-config rollback asset on the box, and performs the reversible generation-preserving
  transcription.
- `doctor` — requires exact box/dev parity, runtime-equivalent artifact validation, and an intact
  content-addressed qualified controller/compiler release manifest.
- `rollback` — maps only to the controller's `roll-back --json` S30 path. It verifies the real receipt
  is generation-preserving, monotonic, and resumed at `manual_only`; the controller's structural
  regression proves that exact Rust path has no GitHub/network dependency. It never calls
  `direct-operation roll-back-controller`.

`sync` and `activate` require `--operation-id <id> --owner-go <same-id>`. Each operation ID is
persistently claimed once; recipe authorization cannot be replayed for lock/assignment/mode staging
or box transcription. `qualification-ledger.json` is the exact-image disposition authority for M3
custom commands; failed/divergent candidates stay canned-only. `chaos-scheduler` is always refused.

<!-- doc-warden:cross-repo-authority:controller-required-node-authority:begin -->
## Cross-repo authority pointer — controller-required-node-authority

**Canonical owner:** [`KleinPerkins/pr-automation-controller`](https://github.com/KleinPerkins/pr-automation-controller) — `docs/adr/0008-controller-owned-required-node-authority.md`

This section is a **pointer only**. Canonical prose for this authority boundary lives in the
owning repository above. Do not duplicate governed statements here; link and defer.

**Profile:** pr-automation-required-checks · **Topic:** controller-required-node-authority,generated-lock-authority-boundary,per-repository-ruleset-projection · **Recorded:** 2026-08-13

<!-- doc-warden:cross-repo-authority:controller-required-node-authority:end -->

## Private unqualified candidate preparation

`python3 _ops/baseline/profiles/pr-automation/v3/prepare_candidate_tuple.py
--input REQUEST.json --out ABSOLUTE_FRESH_PRIVATE_DIRECTORY` prepares the accepted
CW06 forward/fallback pair without modifying a Git worktree, operation receipt,
installed configuration, assignment authority, or GitHub resource. The output must
be outside Git worktrees and installed-state directories. Existing output refuses.

The closed request schema `pr-automation-private-candidate-request/v1` requires
`lifecycle_state: unqualified`, an explicit nondecreasing activation generation,
bound live-config, complete eligible-fleet preimages and final candidate source/build evidence, exactly forward then
fallback candidate source/build/artifact identities, and only the accepted
Orchestrator stdlib profile change. Every file reference binds an absolute path
and SHA-256. The preimage inventory is the source preparation
`f3-fleet-preimages/v1`; each eligible repository needs one consistent observed
default ref and exact recipe, lock, policy and manifest bytes with Git blob hashes.
Remote freshness is a caller-observed prerequisite, never inferred from a hash.

The only executed artifacts are hash-bound native macOS lock compilers with their
exact successful source-build evidence. Linux controller/compiler bytes are
hashed and format-checked, never executed. Their role, source commit/tree, catalog and both target digests must match the explicitly bound final candidate source record; swapped or stale artifacts refuse. Each compiler produces and validates
every affected lock. Existing owner validation checks observed policy/config
parity; candidate policies change only the explicit generation and binary digest.
The existing qualified-release validator and activation commands are unchanged.

Outputs include both candidate configs, controller bindings, unqualified release
input records, all policies and compiled locks, one shared assignment, and a
forward-to-fallback restoration map. `PREPARATION.json` is explicitly unqualified
and cannot satisfy a qualified-release manifest gate. A failure leaves private
diagnostic output with no completion manifest. No journal is copied or restored.

This tool does not establish source delivery, Linux compiler consumption, runtime
qualification, timed restoration, or active owner publication. Those accepted
gates remain required. Private generation does not select the live cutover
generation or authorize a maintenance window.
