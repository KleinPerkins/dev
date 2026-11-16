# `~/dev` Operating-Model Policy (`_ops/POLICY.md`)

> **Canonical policy for the `KleinPerkins/dev` repo** (the home/`~/dev` layer).
> The per-tool agent rules (Cursor `.mdc`, the Codex/Claude managed blocks) and the root
> `AGENTS.md` are thin pointers; this document and the verify check win when they disagree.
> The broader narrative SOT for the whole `~/dev` tree is **`OPERATING-MANUAL.md`**.

This repo version-controls the **home operating model**: the operating manual, the agent-rule
wiring that makes every tool aware of it, and the bootstrap + checks that keep it durable and
reproducible. It deliberately **mirrors the cpp (`Affirm/card-platform-product`) conventions**
(`_ops/` control surface, a POLICY doc, read-only checks, CI, an `AGENTS.md` entrypoint) but kept
**proportional to a solo operator** with automated independent review, meaningful CI and App-owned delivery. Human technical review is not required.

---

## 1. What is tracked vs ignored (the allow-list contract)

`.gitignore` is an **allow-list**: it ignores everything (`/*`) and then re-includes only the paths
below. To track anything new you must add an explicit `!`-rule. This guarantees work code, personal
code, nested git repos, IDE workspaces, and secrets can never be committed by accident.

| Tracked | Why |
|---|---|
| `OPERATING-MANUAL.md` | the home docs we want durable + multi-machine |
| `README.md`, `AGENTS.md`, `Makefile`, `bootstrap.sh` | repo entrypoints + new-machine flow |
| `_ops/**` | the control plane (policy, rules SOT, bin, checks, hooks) |
| `.planning/doc-warden.json`, `.planning/artifacts/*.md`, `.planning/artifacts/*.governance.json` | doc-warden v2 repository identity and canonical semantic records/plan sidecars; transient authoring and runtime state remain ignored |
| `docs/runbooks/awa-integrity-host-wiring.md` | governed M1 live-activation/UAT/rollback procedure |
| `docs/runbooks/gsd-core-lock-requalification.md` | governed re-qualification procedure for doc-warden's GSD Core lock |
| `docs/runbooks/dev-repo-removal.md` | method and observed failure modes for retiring whole local checkouts (`/dev-remove-repo`) |
| `.github/**`, `scripts/**`, `tests/**`, named delivery/bootstrap docs | repository-owned CI, automatic review and App delivery |
| `capabilities/{bootstrap.sh,mcp-bootstrap.sh,mcp-pins.env,Makefile,verify-capabilities.sh}` | capability bootstraps plus immutable LD-host MCP pins (never operator values) |

| Never tracked (ignored) | Why |
|---|---|
| `affirm/` | Affirm work; lives in its own repos. **Also: a concurrent agent may be writing here — leave it alone.** One narrow exception (§7): `/dev-remove-repo` may remove an entire retired checkout once its preflight proves nothing is writing there. |
| `personal/` | personal `KleinPerkins/*` repos; their own remotes |
| `capabilities/skills/`, `capabilities/mcp/` | independent git repos (`KleinPerkins/skills`, the MCP monorepo) |
| `*.code-workspace`, `.DS_Store`, `.env*`, `*.pem`, `*.key`, `id_rsa*` | IDE cruft / OS cruft / secrets |

The verify check asserts `git ls-files` never reports anything under `affirm/`, `personal/`,
`capabilities/skills/`, or `capabilities/mcp/`.

## 2. Git identity (personal repos use LOCAL noreply)

Set **per-repo, never `--global`** (mirrors `OPERATING-MANUAL.md` §6):

```
git -C ~/dev config --local user.name  "KleinPerkins"
git -C ~/dev config --local user.email "49759187+KleinPerkins@users.noreply.github.com"
```

- Work / Affirm repos keep the global default `laurence.duggan@affirm.com` — do not override there.
- The GitHub **noreply** email avoids **GH007** email-privacy push rejections and keeps the work
  email out of personal commit history. `origin` is **SSH** (`git@github.com:KleinPerkins/dev.git`).

## 3. Agent rules — one SOT, three tools, drift-detected

- **Single source of truth:** `_ops/rules/agent-context.md` — the tight, tool-agnostic operating
  context. Edit *only* this file to change what agents are told.
- **Cursor:** `_ops/rules/dev-operating-model.mdc` (`alwaysApply: true`) is **generated** from the
  SOT (frontmatter + body). `~/.cursor/rules/dev-operating-model.mdc` is an absolute **symlink** to
  it, so edits propagate with no copy step.
- **Codex / Claude:** `_ops/bin/install-agent-rules.sh` injects a **managed block** delimited by
  `<!-- BEGIN dev-operating-model (managed by KleinPerkins/dev) -->` … `<!-- END … -->` into
  `~/.codex/AGENTS.md` and `~/.claude/CLAUDE.md` (created if missing). Existing user content is
  **never clobbered** — only the marked block is replaced in place. The block embeds the SOT's
  `sha256`, so staleness is detectable.
- **Repo entrypoint:** the root `AGENTS.md` is auto-read by Cursor/Codex when working in `~/dev`.
- **Staying current:** editing `agent-context.md` then running `bash _ops/bin/install-agent-rules.sh`
  (or `make install-rules`, or `bash bootstrap.sh`) regenerates the `.mdc` and refreshes both blocks.
  The installer is **idempotent** — a re-run with nothing changed writes nothing.

## 3a. Bounded native Codex instruction activation (INT-007B)

The accepted ADR 0012 permits a separate, explicit Codex instruction path through
`install-agent-rules.sh --codex-native preview|apply|verify|rollback`. It renders
only the three existing Codex managed blocks from owner sources; installed Cursor
configuration is not its authority. Native entry/routing slots are dev-owned host
instructions; shared stewardship remains the skills-owned rule, and conditional
service policies retain their applicability. The active Codex assessment reference
is pinned to the qualified Skills ADR0011
implementation and payload digest. Skills owns the rubric, model/effort policy and
native lifecycle; dev owns only the thin caller and projection. A current passing
MOD-03 assessed-native-dispatch observation with exact host/build/source binding
is required before apply. Historical INT-009/base/economy observations cannot
qualify this successor. The approved Codex-first release includes local activation
and fresh-session proof; it does not expand MCP, AWA, other-host or downstream scope.

Preview captures exact source and target preimages, affected sessions and protected
local rollback bytes. Apply requires the preview's exact action digest and rechecks
source, evidence and target; rollback refuses later user edits. Keep operation
artifacts private and outside Git. The caller still obtains applicable consequence
approval; the digest is not proof of human consent. Native checks establish only
observed workspace/dispatch behavior, never AWA registration or model execution
identity. A legacy full install preserves the native Codex selection and verifies it
against owner sources while continuing Cursor/Claude reconciliation. Native drift
requires a new explicit preview/apply rather than silent replacement.

This opt-in path supports the bounded INT-007B canary. It does not change Cursor or
Claude, copied hooks, MCP registrations, AWA authority, or default bootstrap selection.
Broader durable host rollout remains INT-021 after its dependencies and approvals.
The execution ledger records source delivery, canary outcome and exception expiry
separately; the existence of this interface proves none of them.

### Personal Codex work-assessment caller

The successor caller for the Skills-owned [Codex work-assessment decision](https://github.com/KleinPerkins/skills/blob/main/docs/adr/0011-codex-work-assessment.md)
uses the same explicit transaction entrypoint with `--work-source <absolute-export>`.
This opt-in selects `_ops/rules/hosts/codex-work-dispatch.md` as the Dev-owned caller
source and publishes only its `codex-work-dispatch` managed block. It reads no mixed
home context, installed client mirror, worktree overlay or MCP policy. Existing
INT-007B rendering and qualification remain a separate interface; neither route is
a fallback for the other. A preexisting managed legacy routing selection refuses
this projection and requires a separate owner transition.

`_ops/interoperability/evidence/codex-work-activation-bindings.json` is the closed
Dev-owner activation registry. Its initial empty list authorizes no source/build.
Add an entry only after accepted Skills source, a passing exact current-profile
native screen and independent owner review. Bind accepted source revision, the
three-file payload digest, exact native tool, host build and native host bytes,
and the SHA-256 of the single closed qualification observation. Source tests and
a native screen for another ABI cannot populate that binding by inference.
Qualification remains evidence, never permission. Model execution identity may
remain explicitly unknown; fixture-only, pending-source or unobserved-native
records cannot qualify activation.

The source export is private, immutable and separate from the approved migration
primary checkout. Its `.source-export.json` uses
`interoperability/codex-work-source-export/v1` with exactly repository, revision,
accepted and files (the exact three relative runtime paths mapped to SHA-256).
The registry is the accepted owner binding; an export's accepted flag alone grants
nothing. Recheck source, Python interpreter, template, registry, qualification,
host and target bytes at apply. Use the existing private preview, exact consequence
approval, publication and preimage rollback contract; preserve unmanaged bytes and
later owner edits. Hashes and caller records are drift hygiene, not a security
boundary against same-user fabrication.

Once this personal work profile is present, a broad legacy instruction install
refuses before any mutation. Explicit bounded operations and source-only
`--gen-only` remain distinct. File projection verification does not establish
fresh-session discovery or native use; those observations and exact activation
consent remain required. This route supplies routing only, not full personal Dev
distribution, worktree/writer qualification, AWA registration or migration
completion. Existing source pins, legacy evidence, and other clients stay separate.

## 3b. Cross-tool parity — behavioral rules + MCP (Cursor → Codex/Claude)

The home context (§3) is one of three things mirrored to every tool. Two more mirrors give Codex
and Claude the same *behavior* and *tooling* as Cursor, not just the same operating-model context:

- **Behavioral rules — deterministic, verify-enforced.** `install-agent-rules.sh` injects a SECOND
  managed block — `<!-- BEGIN cursor-rules-mirror (managed by KleinPerkins/dev) -->` … `<!-- END … -->` —
  into `~/.codex/AGENTS.md` and `~/.claude/CLAUDE.md`, below the home-context block in a fixed order.
  It contains every `~/.cursor/rules/*.mdc` flagged `alwaysApply: true` (today: `terse-output`,
  `subagent-orchestration`, `worktree-default`), frontmatter-stripped, blank-trimmed, and sorted so
  the block is byte-stable.
  `dev-operating-model` is excluded (it is the first block). The source of truth is the **deployed
  Cursor rules** (now backed by the versioned `_ops/rules/global/` SOT, see below); intent-scoped /
  agent-requestable rules (the MCP-safety, analytics, numenor rules)
  are not in *this* always-on block (see the MCP-safety block below). `make verify` (and so the full
  local check) rebuilds the block from source and diffs it — drift or hand-edits **fail**.
- **MCP-safety guardrails — conditional, verify-enforced.** A THIRD managed block,
  `<!-- BEGIN cursor-mcp-safety-mirror … -->`, mirrors every `~/.cursor/rules/*-mcp-safety.mdc`
  (today: `Notion`, `jira`, `slack`, `snowflake`) into **both** Codex and Claude, each prefixed with
  its gating `description:` ("apply only when using the named MCP"). It is kept third in the fixed
  block order and is verify-enforced the same way. These are conditional (not always-on) guardrails,
  so an agent applies one only when that MCP is actually in use — harmless where the MCP is absent.
- **Reproducible sources.** Home-operating rules and MCP guardrails are version-controlled in
  `_ops/rules/global/`; reusable global rule capabilities live in
  `capabilities/skills/global/rules/<id>/`. Bootstrap prepares the skills hub first, then
  `install-agent-rules.sh` deploys both source sets as **symlinks** into `~/.cursor/rules` (a
  byte-identical pre-existing file is adopted; anything else is backed up) before mirroring to
  Codex/Claude. It also prunes retired symlinks that still point into either managed source.
  `make verify` asserts each present SOT resolves correctly. (The MCP **servers** are still sourced
  from machine-local `~/.cursor/mcp.json`, which has no committed SOT — see below.)
- **MCP servers — advisory, backed-up, non-destructive.** `_ops/bin/install-mcp.sh` mirrors
  `~/.cursor/mcp.json` → **Claude** (`~/.claude.json`: all servers; Claude uses the same `mcpServers`
  JSON schema and supports http/sse/stdio) and → **Codex** (`~/.codex/config.toml`: **command/stdio**
  servers only, emitted as `[mcp_servers.<name>]` TOML; remote `url` servers are **skipped** because
  Codex's MCP client is stdio-first). It only **adds** servers the target is missing (never deletes;
  `MCP_MIRROR_FORCE=1` overwrites a differing Claude entry), writes a timestamped `.bak` before any
  change, and is idempotent (`--dry-run` previews). It is **not** part of `make verify` — MCP auth and
  availability vary per tool, so it stays advisory; run it via `make install-mcp` or `bootstrap.sh`.
  Like all per-tool config it lives under `~` and is **never committed**, so no secret reaches git.

## 4. Bootstrap contract (released host installation only)

The commands below affect host configuration and capabilities. Run them only for
a separately authorized, compatible empty host. Personal-only reconstruction uses
its bounded portability route. Populated Dev roots require the exact preserved
path/linked-worktree transaction; copying `.git`, pulling old lineage or resetting
a populated root is not an accepted replacement procedure. During source preparation
use isolated tests and `--gen-only`, never the broad installer.

```
git clone git@github.com:KleinPerkins/dev.git ~/dev
cd ~/dev && bash bootstrap.sh
```

`bootstrap.sh` (1) runs `capabilities/bootstrap.sh` (clones `KleinPerkins/skills` if missing and
relinks capabilities; conservative, never clobbers), (2) installs/refreshes the agent rules for all
three tools from both managed rule sources and builds the cursor-rules + mcp-safety mirrors (§3b),
(3) mirrors shareable MCP servers Cursor→Codex/Claude (`install-mcp.sh`, best-effort),
(4) runs `capabilities/mcp-bootstrap.sh`, which
installs snow-kit from the tracked immutable tag+SHA pin into an XDG runtime and reconciles a
fail-closed read-only registration without opening a browser, (5) surfaces the `/dev-*` skills,
then (6) runs the verify check. It is safe to re-run.

Snow-kit operator values remain only in mode-0600
`${XDG_CONFIG_HOME:-~/.config}/snow-kit/config.env`; `capabilities/mcp-pins.env` contains only the
private source pointer, immutable release tag, and full commit SHA. Interactive activation is an
explicit `capabilities/mcp-bootstrap.sh install snow-kit --activate` step and is never part of
no-argument bootstrap.

## 5. Enforcement — source, hosted delivery and installed host

The installed PR controller is abandoned and must not resume. PAC mini actions is
planned development, with no assumed launch date or current operational role.
GitHub Actions/App delivery is the durable standard for the explicitly enrolled
public cohort, not a temporary bridge waiting for PAC. Historical controller
schemas and tests may remain inert; legacy mutation paths must refuse restoration.

- **Local source:** `make verify-ci` runs the complete source-check union, including
  meaningful subsystem suites and the capability-discovery test. `make gen`
  regenerates source instructions without changing installed clients. Commit-time
  identity, writer and data guards remain mandatory; never bypass hooks.
- **Hosted source:** `.github/ci-contract.json` and the closed shard inventory own
  coverage. Every required nonempty shard runs on bounded standard hosted runners,
  contents-read only, pinned actions and no secrets. The aggregate admits only the
  exact current run/attempt/commit and complete successful shard set. No self-hosted
  runner or synthetic success check substitutes for source verification.
- **Automatic review:** the authoring agent initiates a fresh independent agent
  review using the account context captured when the PR is created. One qualifying
  review suffices. Cloud is strongly preferred; the qualified same-account local
  adapter is permitted. Personal review cannot cover work-origin changes or vice
  versa. Missing, stale, conflicting or self-authored evidence blocks admission.
  The accepted local adapter is trusted tooling, not protection against a malicious
  agent with the same machine/GitHub access. No human technical reviewer is required.
- **Delivery:** the qualified Chaos Scheduler App owns approval and native squash
  delivery. It may squash an already merge-ready PR or enable auto-merge for an
  eligible blocked PR. GitHub protections and current head/base/policy/review/CI
  checks remain mandatory. Sensitive workflow/governance changes may use the same
  automated review-and-check path. Agents never bypass rules, manufacture approval,
  or manipulate auto-merge themselves.
- **Installed host:** actual guards, generated client context, bootstrap, runtime
  and capability registrations require their applicable installation/recovery gates.
  `make verify` checks installed state. Source fixtures prove only source behavior;
  absent runtime checks remain explicit gaps. Never run a live installer as a test.

## 6. Repository dispositions and admission

The exact cohort is declared in `_ops/baseline/delivery-policy.json`. Public CI/App
targets are `kp-pr-bot-canary`, `kp-mcp`, `intent-router`, `awa`, `local-jobs`,
`ecosystem-orchestrator`, `skills`, `pr-automation-controller`, `dev`,
`operator-voice`, `sterling.io`, `machine-monitor`, `shadow-sync`, and
`doc-warden-canary`, all owned by KleinPerkins. Publication of each repository
requires its accepted content/history checks and admission gates; inclusion alone
never changes visibility or installs controls.

`chaos-labs`, `ai-analytics-context`, `server-guard`, `operator-voice-profile`, and
`cpp` remain private with no CI. `sterling` is excluded and its obsolete controller
enrollment is retired through the accepted preservation/retirement procedure.
Unknown repositories remain unenrolled; creating a private repository must never
silently enroll it with the retired controller. A pending scaffold is not CI-ready.

`chaos-scheduler` converges on the shared framework while preserving its public
release process. Its source changes and held WIP are outside this bounded Dev
replacement preparation. Using its installed GitHub App is a separate existing
capability and grants no scheduler-source or runtime modification authority.

Names route discovery; mutations must bind the observed immutable GitHub ID.
The Dev successor is ID `1459458379`, first named `dev-temp`, then `dev` under the
released transition. No alias admits predecessor ID `1278387789`. Each operation
must use one coherent observed name/ID phase. Old-name receipts become stale after
rename. Old PRs, commits, frozen approvals and runtime receipts do not become new
repository authority by copying or changing a name.

Fresh-repository bootstrap has a separate exact administrative gate: independently
review the complete public-safe seed and its new-ID producer/account enrollments,
then release only that seed to empty private main with Actions and App writer OFF.
Source upload, publication, controls, trusted-main read-only qualification, writer
activation, names and host cutover are distinct observed steps. A seed review is
not an ordinary PR receipt. Empty enrollments cannot approve their own enrollment.
See `docs/bootstrap-review.md`, `docs/github-delivery.md` and
`docs/runbooks/dev-successor-adoption.md` for the source contracts.

Required checks/reviews, history protection, resolved conversations, squash-only
merge and current-base validation remain repository-owned. Baseline tools must not
remove or weaken them. New repository foundations record sharding requirements;
activation needs complete nonempty coverage and the fail-closed aggregate.
Generic legacy `enforce` or controller `reconcile` cannot substitute for the exact
successor settings release. Existing accepted owner emergency authority remains
administrative and is never permission for an agent to bypass delivery gates.

## 6b. Uniform repo control baseline — pointer

`_ops/baseline/README.md` owns the minimal local-file floor and bounded scaffold
behavior. `list`/`verify` observe; `apply` is a local mutation, not a read-only action.
Any GitHub settings operation needs its concrete accepted target/payload and must
preserve stronger repository controls. The future repo-platform capability is a
separate post-migration effort; this transition does not implement that framework.

## 7. Relationship to other operating models

- **`OPERATING-MANUAL.md`** is the narrative SOT for the entire `~/dev` tree; this repo makes it
  durable and version-controlled. (It supersedes that file's historical "not committed to any repo"
  note.)
- **cpp** (`affirm/src/card-platform-product`) is a separately governed repo with its **own** heavier
  `_ops/` model (deterministic integrity engine, bot, branch protection). This repo intentionally
  does **not** govern cpp; it only references it. Never write under `affirm/` from here, except as the
  next bullet narrowly allows.
<!-- policy:dev-remove-repo-affirm-exception/v1 -->
- **Whole-checkout removal under `affirm/` (the one exception).** The home removal utility
  (`/dev-remove-repo`, `_ops/bin/dev-remove-repo.sh`) may remove an **entire** retired checkout at
  `affirm/src/<name>` or `affirm/vendor/<name>`, and only after its preflight proves that no process,
  editing-session lock, AWA lease or Git lock is active in that checkout and that no concurrent agent
  is writing there. It never writes *inside* a checkout, never follows symlinks, never infers authority
  from a repository name, and never removes `affirm/src/card-platform-product`. Detaching cpp or any
  other separately governed repo from a removed checkout stays a governed change in that repo's own PR
  path, merged first. When the preflight cannot prove that nothing is writing, or this exception is not
  in force, an `affirm/` target remains an operator gate. The exception does not weaken the allow-list
  (§1), the concurrent-writer rules (`OPERATING-MANUAL.md` §9d), cpp governance, or the reference-only
  rule for `affirm/vendor` contribution.

## 8. Ecosystem operating model (reorg-v2)

The capability ecosystem (designation, sync, the ld↔cpp edge) is documented in
**`OPERATING-MANUAL.md` §10**; this is the enforced-policy summary.
- **Designation = directory + kind shelf:** scope is `…/global/` (shared) vs `…/local/`; kind shelves are
  `skills|rules|sub-agents|tools`; each capability carries a flat `meta.yml` (`kp-capability/v1`) +
  paired idempotent `install.sh`. `meta.kind` must agree with the shelf. Engines live in `_ops/eco/`
  (`manifest.sh`, `sync.sh`, `self-heal.sh`, `clean-room.sh`, `verify-manifests.sh`,
  `verify-zero-link.sh`, `regression-suite.sh`) and as `make eco-*` targets.
- **WF1 registration is metadata governance, not sync:** `personal/ecosystem-orchestrator/config/registry.yml`
  is the sole enrollment SoT (`enrolled|excluded|demoted`); `meta.yml` remains the per-capability config
  and exposure SoT (`expose:`). A registry edit never auto-triggers cpp sync.
- **Lockkit is the only normalizer lineage:** the orchestrator owns the single
  `templates/eco-lock/eco-lock.sh` master and `lockkit check|write|diff`; `make eco-lockkit-*` wrappers
  delegate to it. Capability repos carry vendored `.github/scripts/eco-lock.sh` copies plus their
  `.eco-registry.lock`. Lockkit locks normalized `meta.yml` fields only; it is not payload byte
  integrity, enrollment authority, or a cpp manifest generator.
- **WF1 enforcement strength is explicit:** local checks and CI workflow parity are the required gate of
  record. GitHub branch protection for the private capability repos is intentionally not assumed on the
  current account plan. The pre-commit `registration-guard` is advisory fast feedback only: it self-disables
  without both `.eco-registry.lock` and executable `.github/scripts/eco-lock.sh`, runs only when staged
  `meta.yml` changes exist, invokes `bash .github/scripts/eco-lock.sh write`, stages the lock if that
  succeeds, and always exits 0. It never reimplements normalization. Orchestrator `reconcile` is the
  registry↔lock authority because it sees both `registry.yml` and each repo's committed lock.
- **WF2 cpp-sync is independent and governed:** `orchestrator cpp-sync` is registry-driven, preflights WF1
  lock/reconcile state, `enabled_kinds`, zero-link, cpp integrity, and flavor-2 approvals, then opens
  governed cpp data-plane PRs. It generates the atomic cpp manifest only after payload work; recovery uses
  governed `rollback` / `quarantine`, not hand edits.
- **Two invariants:** **INV-master + consistency** — one canonical master (locally consumed via symlink);
  the cpp-team payload is a deliberate **REAL second copy** (teammates lack private-repo access), so the old
  strict single-physical-copy rule is **relaxed to two copies**, reconciled by sync-time master↔payload
  consistency verify (`make eco-consistency`; Decision A — the symlink-dedup is **abandoned**). And
  **INV-zero-link** — global artifacts carry zero cpp refs, cpp payloads carry zero ld refs; the gate scans
  **ALL managed roots, case-insensitively** (`make eco-zero-link`; Decision C).
- **The cpp edge is orchestrator-only:** `KleinPerkins/ecosystem-orchestrator` is the **single** sanctioned
  writer into cpp — `vendor`/`delete` land an ld-agnostic copy in `cpp/quiver/<cat>/<id>` via an LD-authored
  governed PR, gated on cpp's integrity engine, landed by **GitHub NATIVE auto-merge** (`gh pr merge --auto
  --squash`; bot CODEOWNER approval + required server checks — **no human reviewer, no `--admin`** on the
  routine path; `--admin` is **break-glass only**, Decision B). It never touches cpp's control plane.
- **Intentional absences:** this `~/dev` repo does not carry `registry.yml`, `.eco-registry.lock`, or
  `eco-lock.sh`; `registration-guard` is not blocking; lockkit does not vendor payloads; the orchestrator
  does not edit cpp `_ops/` / `.github/`; branch protection is not a claimed capability-repo gate; and
  generated mirrors are refreshed only when their rule source changes. The predecessor
  reorganization dossier is privately preserved; the retained source contract is §10.

## 9. Uniform documentation governance — pointer

`_ops/doc-warden/POLICY.md` is the **SOT** for canonical documentation-governance policy
(artifact taxonomy, trigger catalog, templates, lifecycle/archival rules) applied by default to
new repos (`dev-new-repo.sh`) and rolled out deliberately to existing KleinPerkins-owned repos
(`_ops/bin/doc-warden.sh check|repair`). See `_ops/plans/doc-warden-execution-plan-v1.md` for the
full historical design and rollout plan. Frozen `_ops/adr/` records retain predecessor
identity and bytes; successor ADR discovery uses `docs/adr/` through `.doc-warden.yml`.
The fresh adoption record determines retained policy relationships; old records do not
become new-ID approvals by copying them. `dev-doctor.sh` surfaces documentation-conformance as a non-blocking advisory, the
same way it already does for the repo-baseline floor.
