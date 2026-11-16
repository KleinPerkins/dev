# ~/dev — Home Operating Model

`~/dev` is the `KleinPerkins/dev` master developer root. `OPERATING-MANUAL.md` is the full source of truth; `_ops/POLICY.md` is the enforceable repo policy; this file is the compact context installed into Cursor/Codex/Claude.

## Layout And Ownership

- `affirm/src/` is authoritative work: contribute, push, and open PRs there.
- `affirm/vendor/` is read-mostly reference. Promote a clone to `src/` before active contribution.
- Personal/work target paths are `<container>/<src-or-vendor>/<git-owner>/<repo>`; the work container is employer-specific, currently `affirm`. Existing paths remain until separately migrated. `capabilities/` contains reusable capabilities and ecosystem-maintenance repositories.
- Most subtrees are their own repos and are not tracked by `KleinPerkins/dev`; this repo tracks the home operating model only.
- Auth, secrets, client config, generated memories, and work/personal repo contents stay out of this repo.

## Identity And Placement

- Work/Affirm repos use global `laurence.duggan@affirm.com`. Do not set a local override unless that repo's own `_ops` requires it.
- Personal/KleinPerkins repos, capabilities, and this repo use local, never global, `KleinPerkins <49759187+KleinPerkins@users.noreply.github.com>`.
- `affirm/src/card-platform-product` (`cpp`) is separately governed; read and follow its own `AGENTS.md` and `_ops/POLICY.md`. cpp's local noreply identity is intentional.
- New reusable tooling belongs under `capabilities/`; new product code belongs in `affirm/src` or `personal/` according to ownership. `affirm/vendor` remains reference-only until promoted.

## Capability Lifecycle

See `OPERATING-MANUAL.md` §10 for the complete ecosystem model. Preserve these invariants inline:

- Global capabilities are enrolled by `config/registry.yml` plus `meta.yml`; lockkit/reconcile own registry parity. Registration never auto-triggers sync.
- `KleinPerkins/ecosystem-orchestrator` is the only sanctioned writer of the ld↔cpp edge. Never hand-vendor into `affirm/`; the orchestrator creates governed cpp PRs.
- cpp keeps real vendored capability copies, not live symlinks. Enforce byte consistency through orchestrator checks, not by collapsing source and payload.
- Global artifacts must contain zero cpp references and cpp payloads zero ld references; the relationship exists only in orchestrator metadata.
- MCP capabilities are discoverability-only when runtime bytes cannot be vendored safely.
- Do not flip new cpp `enabled_kinds` until the cpp-owned reconciler/bootstrap support has merged under cpp governance.

## Worktrees, Sessions, And Guards

- One writer per working tree. If parallel work is needed, use a separate git worktree; never share an index.
- For Codex, inspect native attachments and create/attach the appropriate worktree; verify the returned root, branch, Git directories and writer before mutation. A printed helper path is not native attachment or AWA protection. Respect policy exclusions (`cpp`, `affirm/vendor/*`, the `~/dev` umbrella repo, and foreign hook frameworks). Preserve owner exclusions and separate indexes.
- If the primary tree is dirty, do not relocate, clean, reset, or overwrite it silently.
- Use `_ops/bin/dev-worktree.sh status|doctor|list|clean` for AWA diagnosis/cleanup.
- Set `DEV_SESSION_ID` per agent/session so session-lock can distinguish concurrent writers.
- Commit-time guards for personal/capability repos are session-lock, identity-guard, and data-guard. Never use `--no-verify`; use `DATA_GUARD_ALLOW=1` only for intentional data fixtures, and inspect `~/dev/_ops/bin/session-lock.sh status|release|steal` if blocked.
- AWA host details live in `OPERATING-MANUAL.md` §11 and the cross-repo authority pointer below. Local shim verification: `make worktree-verify`, `make verify-ci`.

## Repo Control And PR Automation

- The installed PR controller is retired. PAC mini actions is planned work; it supplies no current review or delivery service. Legacy controller mutation commands must refuse instead of restoring dead checks.
- The explicit cohort in `_ops/baseline/delivery-policy.json` selects Actions/App, private/no-CI and retired dispositions. A name is a routing hint; settings changes require the observed immutable repository identity. Unknown repositories remain unenrolled.
- Public cohort delivery requires complete meaningful sharded GitHub Actions CI on bounded standard hosted runners. Self-hosted runners remain forbidden. Private/no-CI exceptions remain private and receive no CI enrollment.
- The authoring agent automatically initiates one fresh independent review from the PR-creation Codex account. Cloud is preferred; a qualified same-account local adapter is allowed. Never substitute the other account or a human reviewer. Re-review after a changed head, base or policy.
- The qualified Chaos Scheduler App alone approves and performs native squash immediately when merge-ready, or enables native auto-merge when blocked. Agents maintain eligible PRs through verified merge, but never bypass protections or call merge/auto-merge APIs themselves. Sensitive CI/governance changes follow the same review/check gates.
- Initial source admission, external settings and host installation require their concrete accepted administrative gates. Source tests, seed presence and copied receipts are not runtime qualification.
- `chaos-scheduler` will converge on the shared framework while retaining its public release process. Its source/runtime changes remain outside this bounded Dev replacement preparation; preserve its held WIP.

## This Repo

- `_ops/rules/agent-context.md` is the source for the generated Cursor `dev-operating-model.mdc` and managed Codex/Claude blocks. After editing it, run `_ops/bin/install-agent-rules.sh --gen-only` before source review. Run `make install-rules` only under the separately released host-installation step.
- The installer mirrors always-apply Cursor behavioral rules plus conditional MCP-safety rules; global home rules are versioned in `_ops/rules/global/`, reusable global rules in `capabilities/skills/global/rules/`.
- `.gitignore` is an allow-list so nested repos and secrets cannot be committed accidentally.
- Search reliability: in linked Cursor worktrees, use the shell `rg` executable for task-critical searches and to confirm every absence claim. Positive native Grep/`rg` matches are usable, but an empty result is unverified because native search can return false-empty. Inside a repository/worktree, use plain shell `rg`. Only from the `~/dev` umbrella root, search the actual subrepository or add `--no-ignore`: its allow-list intentionally hides nested repositories. Do not misdiagnose the native-search bug as ignore behavior.
- Verify source with `make verify-ci`; use `make verify` for the separately released installed-host check. Hosted readiness requires observed current-main CI and App qualification.
- Follow the released host bootstrap/reconstruction plan. Never replace populated `~/dev` or its shared Git metadata without exact path preservation and linked-worktree reconciliation.

<!-- doc-warden:cross-repo-authority:awa-dev-overlay:begin -->
## Cross-repo authority pointer — awa-dev-overlay

**Canonical owner:** [`KleinPerkins/awa`](https://github.com/KleinPerkins/awa) — `docs/adr/0002-awa-dev-overlay.md`

This section is a **pointer only**. Canonical prose for this authority boundary lives in the
owning repository above. Do not duplicate governed statements here; link and defer.

**Profile:** poc3d · **Topic:** ssp-product-location,host-overlay-role,kernel-first-invariant,no-duplicated-contract,operator-copy-honesty,host-policy-literals · **Recorded:** 2026-08-06

<!-- doc-warden:cross-repo-authority:awa-dev-overlay:end -->

<!-- doc-warden:cross-repo-authority:awa-integrity:begin -->
## Cross-repo authority pointer — awa-integrity

**Canonical owner:** [`KleinPerkins/awa`](https://github.com/KleinPerkins/awa) — `docs/adr/0020-awa-integrity-surveillance-and-lifecycle.md`

This section is a **pointer only**. Canonical prose for this authority boundary lives in the
owning repository above. Do not duplicate governed statements here; link and defer.

**Profile:** awa-integrity · **Topic:** integrity-sot,integrity-invariants,runnerless-surveillance,host-trigger-wiring,safe-workspace-entry,operator-interface · **Recorded:** 2026-08-24

<!-- doc-warden:cross-repo-authority:awa-integrity:end -->
