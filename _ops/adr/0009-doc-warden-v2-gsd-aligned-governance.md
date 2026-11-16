# ADR 0009: `doc-warden` v2 in-boundary governance (GSD-aligned overlay; agentic-execution safety layer deferred)
Status: ACCEPTED — 2026-08-28. Scoped, per the operator's pre-acceptance scope decision, to the reviewer-cleared **in-boundary governance** layer: the split-system product boundary (a pinned GSD execution plane for authoring/context plus a local doc-warden governance overlay), per-repository authority, the typed artifact schema, referential integrity and code anchors, deterministic dynamic rigor, the canonical nontechnical PRD, migration of existing repositories, new-repository instantiation, NLP-first operator verbs, and Save-Game/continuity **for authoring**. The net-new **agentic-execution safety layer** — autonomous GSD execution plus its claimed hard-enforcement guarantees (OS/host-enforced consent trust root, gateway repository-lease, closed command allow-list and call-graph closure, tamper-evident event chain and head-anchor, fail-closed delivery-permit chokepoint, and network-egress quarantine) — is **removed from this ADR's scope and re-chartered under [ADR 0010](0010-agentic-execution-safety-layer-deferred.md)**, because three independent security/data-integrity/testing/governance reviews found those hard-enforcement claims unachievable in a same-user/in-repo/no-runners tool without a real external boundary (1 P0 + 13 P1, one root cause). This ADR retains **no** hard-enforcement claim. Accepted through the related plan's §0 transaction.

**Decider:** Laurence Duggan
**Owning repository:** `KleinPerkins/dev` (`~/dev`)
**Related plan:** [`doc-warden-execution-plan-v2.md`](../plans/doc-warden-execution-plan-v2.md) (slimmed to in-boundary scope)
**Related deferred decision:** [`ADR 0010`](0010-agentic-execution-safety-layer-deferred.md) — agentic-execution safety layer deferred (PROPOSED), carrying the complete finding inventory
**Supersedes:** ADR-0001's product/runtime boundary; ADR-0001 remains immutable history
**Reaffirms:** ADR-0002, ADR-0003, and ADR-0008

## Context

### Observed local state

`doc-warden` v1 is live as a Bash subsystem owned by `KleinPerkins/dev`:

- `_ops/doc-warden/POLICY.md` is policy version `1.3.0`.
- `_ops/bin/doc-warden.sh` and `_ops/bin/doc-warden-lib.sh` implement classification,
  structural repair, receipts, and cross-repository authority checks.
- `_ops/checks/doc-warden-verify.sh` is part of the local and runnerless verification path.
- `_ops/plans/doc-warden-execution-plan-v1.md` and ADRs 0001–0003 are accepted, frozen
  artifacts. Their pre-authoring SHA-256 values are recorded in the v2 plan and must remain
  unchanged.
- A live `repo-baseline.sh list` on 2026-08-25 reported 13 eligible checkout rows and 154
  excluded rows. Those 13 rows resolve to 12 unique GitHub repository identities because
  `KleinPerkins/ai-analytics-context` appears through two eligible checkouts. `~/dev` is an
  explicit doc-warden addition, and `KleinPerkins/chaos-scheduler` remains a documentation-only,
  on-demand carve-out. Checkout discovery is therefore not a stable logical fleet authority.
- The runnerless PR-automation fleet currently records 18 targets and five explicit exclusions.
  `KleinPerkins/chaos-scheduler` is excluded there and in
  `_ops/baseline/profiles/pr-automation/v3/controller.json`.
- GitHub Actions remains enabled at the platform level, but the fleet has no committed Actions CI
  workflows. Local guards plus runnerless `pr-automation / verify` are the verification path.

Four v1 defects are verified in current code:

1. A trigger-created plan or ADR skeleton receives a receipt content digest immediately. Once its
   authoring placeholders are replaced, `dwl_classify_plan_file` or `dwl_classify_adr_file`
   compares the authored bytes with the skeleton receipt and returns `DRIFTED`. Creation evidence
   is acting as an accidental accepted-freeze binding.
2. `dwl_write_receipt` emits `policy_version: "1.0.0"` while the active policy is `1.3.0`;
   `triggers.yml` separately says `1.1.0`.
3. `triggers.yml` claims to be the closed behavioral catalog, but the runtime reads only trigger
   IDs and implements targets/actions in a separate shell `case`. Catalog and runtime already
   disagree on ADR naming and pointer verification.
4. `DW-DEF-001` — classifier SIGPIPE false-`DRIFTED` on large agentic plans. Under `set -o pipefail`,
   `dwl_classify_plan_file`'s work-items marker probes used `printf '%s\n' "$workitems" | grep -qE`;
   when the work-items section exceeds the OS pipe buffer, `grep -q` exits on first match, `printf`
   is killed by SIGPIPE (141), `pipefail` propagates it, and a fully conformant plan mis-classifies
   `DRIFTED` — the exact reason this plan v2 mis-classified. **Resolved** by the Body-1 engine PR
   (here-string probes; regression Fixture 5). Full record: plan v2 §3.8.1.

These defects are not reasons to rewrite v1 history. Defects 1–3 are migration inputs for a
successor receipt lifecycle and a catalog/runtime parity contract; defect 4 was the §0 acceptance
precondition and is already fixed in the v1 engine ahead of v2.

### Observed upstream state

The latest stable GSD Core release verified on 2026-08-25 is
[`v1.11.0`](https://github.com/open-gsd/gsd-core/releases/tag/v1.11.0), published 2026-08-19
with `draft=false` and `prerelease=false`.

The v2 runtime pin is the conjunction of:

- npm package: `@opengsd/gsd-core@1.11.0`;
- Git commit:
  [`182f60b4c170785d96f1deb87fea8b108e9b985f`](https://github.com/open-gsd/gsd-core/commit/182f60b4c170785d96f1deb87fea8b108e9b985f);
- npm integrity:
  `sha512-z1RLWsQshYViJIk94SB0x9/AYPykj5LIuLxwjS0s+WgaCBgVtTknCsVR3x4itrBeqmiUEvGiN6cO/bOay0zOiQ==`.

The pristine local reference clone at `affirm/vendor/gsd-core` is clean and detached at
`v1.10.0` (`68a04ccf8ef74803bdb651e12c3b85b218bbccdf`). It contains the `v1.11.0` tag, but its
checkout is not the selected runtime and is not an implementation target.

GSD Core is MIT licensed, copyright 2026 Open GSD. The license permits use, modification, and
distribution, but copied or substantially copied source/templates must retain the copyright and
permission notice. Consuming the package does not authorize unattributed copying. Any future
adapted bytes must carry provenance and the required notice.

### Why v2 requires a new boundary decision

GSD Core already implements the phase loop, project and requirements context, technical specs,
UI specifications and review, roadmaps and milestones, mutable execution state, executable plans,
summaries, verification, UAT, debugging, handoffs, sketches, spikes, backlog, dependency waves,
must-haves, checker/verifier separation, capabilities, hooks, and multi-client installation.
Recreating those workflows inside `doc-warden` would make the local subsystem a partial,
fast-drifting GSD fork.

GSD does not, by itself, supply the local invariants this fleet needs:

- byte-identical accepted plans and ADRs with successor-only semantic change;
- canonical nontechnical PRDs before feature planning;
- one typed artifact/dependency graph spanning repositories, code, external design assets,
  releases, defects, and mutable fleet projections;
- deterministic dynamic documentation rigor;
- logical-repository fleet deduplication and the `chaos-scheduler` documentation-only carve-out;
- runnerless verification and draft-PR delivery constraints;
- strict external Figma/Quickhost revision, source-commit, and export-digest provenance;
- the existing preview/approval/digest/receipt reconciliation doctrine;
- optional Save-Game integration without taking ownership of Save-Game.

The product boundary must therefore separate upstream execution from local governance rather than
choosing either one as the whole system.

## Decision

### 1. Product boundary: split execution from governance

`doc-warden` v2 is a split system:

1. **Pinned per-repository execution plane.** GSD Core `v1.11.0` owns the phase execution loop and
   its upstream workflow/agent implementation in each governed repository.
2. **Local doc-warden governance overlay.** `KleinPerkins/dev` owns policy, typed artifact records,
   semantic freeze rules, deterministic rigor selection, receipts, reconciliation, fleet
   inventory/deduplication, migration, maintenance, operator CLI/skill, and generated fleet views.
3. **Per-repository authority.** Each governed repository owns its canonical roadmap and its
   semantic artifacts. `~/dev` never becomes a second author of another repository's roadmap,
   PRD, design, specification, ADR, or plan.
4. **Generated fleet projection.** `~/dev` may render a read-only fleet roadmap and governance
   dashboard from repository authorities. The projection always carries source revision and
   freshness and is never directly editable.

GSD is a dependency, not a copied workflow collection. `doc-warden` is an overlay, not a GSD fork.

The GSD package is installed through one source-tracked **dependency-locked `_ops` host-overlay
binding** owned by `KleinPerkins/dev` at `_ops/doc-warden/runtime/gsd-core/`. This is **not** a
capability-lifecycle Flavor-2 binding, **not** WF1 registry enrollment, and **not** cpp/WF2
delivery: the decision governs only the operator's eligible KleinPerkins fleet and explicitly
excludes cpp. The binding owns only the exact package/commit/integrity pin and lockfile, isolated
XDG installation, doctor, repair, and uninstall. It does not vendor GSD workflow bytes into
`KleinPerkins/dev` or consumer repositories.

This supersedes ADR-0001 only where ADR-0001 treated the local Bash subsystem as the complete
product/runtime boundary. The governance owner remains a sibling `_ops/` subsystem. ADR-0002's
shared-doctrine-not-shared-runtime decision and ADR-0003's local-only/no-cpp boundary remain in
force.

### 2. Pinned GSD strategy

> **Scope note.** Pinning the exact GSD release and installing/qualifying it for **authoring and
> governance context** is retained in-boundary. Using that runtime for **autonomous cross-phase
> dispatch/execution** is deferred to [ADR 0010](0010-agentic-execution-safety-layer-deferred.md);
> the pin here is a dependency for authoring/context, not an autonomous execution API.

The v2 installer and runtime adapter must:

- require the exact package version, Git commit, and npm integrity above;
- install into an isolated, non-editable XDG release directory and promote a stable local shim
  only after integrity and doctor checks pass;
- record the package license and upstream URLs;
- refuse moving tags, `main`, `next`, `latest`, version ranges, integrity mismatches, and a
  package whose `gitHead` does not match the selected commit;
- keep the pristine vendor clone reference-only;
- support offline execution after installation;
- perform the live install as a **bounded, reversible, blast-radius-contained** step: an
  isolated-home canary precedes any real-HOME change, a dry-run preview writes nothing, install is
  manifest-owned and additive with an explicit
  real-HOME rollback and install→uninstall idempotence back to captured sentinels, and any global
  **blocking** Cursor hook doc-warden introduces or touches is `failClosed: false` (a global fail-closed
  hook once bricked the shell across every workspace);
- preserve unrelated hooks and restore the exact previous installed state on rollback.

The initial local configuration disables GSD-owned worktree creation and merge/tag behavior. AWA or
each repository's own policy remains the only worktree authority. All implementation PRs start as
drafts; neither GSD, doc-warden, a plan, a skill, nor an agent may arm native auto-merge.

### 3. Ownership and authority model

| Surface | Canonical owner | Mutability | Writer |
|---|---|---|---|
| Pinned GSD runtime bytes | upstream package at the exact pin | immutable per installed release | local package binding |
| GSD workflow behavior | pinned upstream release | immutable per pin | upstream; local adapter config only |
| Doc-warden policy and schemas | `KleinPerkins/dev` | successor/version controlled | governed `~/dev` change |
| Repository roadmap | the repository containing `.planning/ROADMAP.md` | mutable authority | doc-warden CLI after schema validation, or reviewed authoring output imported through that CLI |
| PRD, approved requirements, approved design behavior, ADR, accepted plan | owning repository | frozen after approval; successor only | semantic authoring flow |
| Authoring state, progress, dependency observations, indexes | owning repository or machine-local projection as declared by schema | mutable | doc-warden engine |
| Fleet roadmap/dashboard | generated from repositories | replaceable projection | doc-warden renderer |
| Save-Game checkpoint | Save-Game private store | immutable checkpoint/index, not authority | Save-Game |
| Figma/Quickhost asset | external owner at immutable revision | immutable referenced revision | external system; local record is a pointer |

No skill, router, hook, Canvas, local job, or GSD extension may reimplement governance decisions.
They call the same doc-warden engine or render its deterministic output.

GSD may produce authoring/context output, but those bytes do not become governed authority until the
doc-warden CLI validates and imports them through the same schema and freeze rules as direct
authoring. This is an integration contract, not an execution sandbox or hard-enforcement boundary.

### 4. Artifact and authority model

Every v2 artifact has:

- a stable, repository-scoped ID;
- a type and schema version;
- canonical owner and repository identity;
- lifecycle state;
- explicit mutability class (`frozen`, `append-only`, `mutable-authority`, or
  `generated-projection`);
- active version and successor/predecessor relations;
- provenance and approval evidence;
- typed relations to requirements, designs, plans, defects, code anchors, tests, commits, PRs,
  releases, repositories, and external assets;
- validation rules and conflict behavior.

Canonical machine metadata lives in a closed JSON block inside the owning Markdown artifact or in
a complementary JSON record when the artifact is not Markdown. Human-readable prose and metadata
are complementary parts of one artifact; they are not duplicate authorities. Derived indexes and
graphs are regenerated from those records.

Approved PRDs, requirements, design behavior, ADRs, and plans freeze. A semantic change creates a
successor with a new version and explicit supersession. Roadmaps, indexes, dependency projections,
execution state, progress, rollups, and freshness remain mutable.

GSD's `.planning/` names and layout are the default. Local deviations are allowed only where an
existing invariant requires them:

- ADRs remain in `docs/adr/` (or the repository's declared ADR override) because GSD has no
  equivalent durable ADR authority.
- Existing frozen plans remain at their current governed paths forever.
- New executable phase plans use GSD's `.planning/phases/` layout and carry doc-warden IDs and
  freeze metadata; a generated GSD execution view may point to a frozen canonical plan but may
  never become a separately editable copy.
- `.planning/PROJECT.md` and `.planning/REQUIREMENTS.md` are current projections over approved
  project/PRD/requirement records; they are not permitted to overwrite frozen source semantics.

### 5. Dynamic rigor

V2 governance is authored **inactive** and turned on by one atomic **central activation** transaction
only after M1 establishes minimal trigger authority — a typed, versioned trigger catalog with
validated catalog/runtime parity. Policy is never activated before the trigger runtime can honor it.
**Central activation** makes v2 policy / governance-evaluation active fleet-wide; it does **not**
write-enable any repository. **Per-repo write-enablement** — a repository's v2 artifact/authority
writes becoming permitted — is repository-scoped, starts off, and is granted only by that repository's
approved migration transaction or a born-v2 new-repo transaction. Governance-evaluation active means
the engine evaluates every work item; it does not mean every item receives every artifact, and it
never by itself write-enables a repository. A v2 authority write requires **both** gates: central
activation must be active and the target repository must be write-enabled. A repository may be
scaffolded or marked born-v2 before central activation, but its v2 mutation path remains dormant until
central activation completes.

Artifact requirements are selected by a deterministic rules matrix using explicit signals such
as change kind, affected repositories/components, user-visible behavior, UI/visual scope,
sensitive data/security/privacy/money movement, reversibility, and execution duration. The engine
uses closed rules, not opaque LLM scoring. Unknown or conflicting signals promote rigor or
escalate; they never silently waive an artifact.

Any UI/visual work always requires UX requirements, an approved design contract, visual artifacts,
complete state/accessibility/responsive coverage, prototypes when behavior is unresolved, approval
before implementation planning, and visual verification/UAT.

A narrow hotfix/defect may use a detailed defect record instead of a PRD only while it restores
previously approved behavior, has bounded scope, and carries intent, evidence, acceptance, and
verification. Scope growth automatically promotes it to the appropriate feature path.

### 6. Roadmaps and rollup

Each repository's `.planning/ROADMAP.md` is its one canonical roadmap. It distinguishes:

- priority from sequence/wave;
- outcome from implementation;
- product work from defects;
- planned dependencies from observed dependencies;
- active from deferred;
- complete from cancelled or superseded.

Each roadmap item resolves to stable IDs, outcome, priority, sequence/wave, status, dependencies,
required artifact set, current versions, active plan, blockers, next action, completion evidence,
and freshness.

The fleet rollup contains canonical repository ID, source revision, generation time, and freshness
for every source row. Direct edits are refused. A stale or unavailable repository remains visible
with an explicit reason; it is never silently dropped.

### 7. Dependency graph and reconciliation

The graph spans artifacts, code anchors, repositories, plans, roadmaps, external assets, and
releases. Planned relations originate in canonical artifact records. Observed relations are
derived from exact repository/code/design evidence and remain labeled as observations.

Reconciliation runs during natural usage, before execution, after relevant code/design/requirement
changes, at task and milestone boundaries, after merges/releases, and through read-only routine
maintenance. It detects dangling, stale, missing, unmapped, cyclic, added, removed, superseded,
inconsistent, and assumption-invalidating dependencies.

Results use these classes:

- safe projection update;
- safe structural repair;
- review recommended;
- plan refinement required;
- operator decision required;
- contradictory authority;
- unverifiable.

Automatic reconciliation may update only mutable/generated projections, references, freshness
metadata, derived status, and exact dependency observations. It may never change product behavior,
acceptance criteria, approved design, architecture, or plan semantics.

Every in-boundary mutation follows `preview -> confirm -> apply -> verify -> receipt`. Preview carries
a UUID `operation_id`, repository key, canonical root, source revision, preimage digests, proposed
output, and an action/output digest. Confirmation is explicit and bound to that preview, but it is an
operator-experience guardrail rather than an unforgeable security primitive.

Apply revalidates the root, revision, preimages, schema, and operation identity, writes through a
same-directory temporary file plus atomic rename, and regenerates only mutable projections.
Idempotent retries reuse the same `operation_id`; a conflicting or unverifiable authority writes
nothing. Receipts and conventional event records provide auditability and interruption diagnosis,
but make no tamper-evidence claim against the same-user agent. Exclusive native-execution leases,
OS/host-enforced consent, a write-ahead event chain and protected head anchor, and a delivery
chokepoint are deferred to ADR 0010.

### 8. Operator experience

The primary experience is NLP-first: ordinary phrases route to one thin `doc-warden` skill and
one authoritative engine. Explicit equivalents use these verbs:

`view`, `draft`, `log`, `update`, `prioritize`, `sequence`, `reconcile`, `doctor`, `run`, `pause`,
`resume`, and `verify`.

The skill, CLI, and Canvas expose the same intent model. Destructive or semantic actions show a
plain-language preview and require the consequence-appropriate confirmation. Routine read-only
views do not nag. Failures name what was checked, what remains uncertain, and the exact next
action.

No MCP server is part of the v2 decision. The CLI, thin skill, agent routing, and Cursor Canvas
cover the complete local experience without another protocol/runtime. A future MCP requires a
successor decision proving a unique capability that cannot be supplied by those surfaces.

### 9. Authoring continuity and deferred execution

Autonomous GSD execution and its proposed enforcement machinery are out of scope and live only in
[ADR 0010](0010-agentic-execution-safety-layer-deferred.md). V2 does not dispatch implementation,
chain phases, claim command/call-graph containment, mint delivery permits, or interpose on PR
delivery.

An accepted plan is immutable. GSD authoring/context output may be imported only after doc-warden
schema and authority validation. Every implementation task authored for later operator-led delivery
is zero-context and names exact files/code anchors, required reading, interfaces, dependencies,
requirement/design IDs, actions, tests, expected outcomes, acceptance, rollback, evidence, and
escalation conditions.

Save-Game integration is an optional stable adapter for authoring checkpoints, external waits,
handoffs, and authoring resume/reconciliation. Save-Game remains independently usable and owns its
private checkpoints. Doc-warden stores only the closed
`doc-warden/save-game-pointer/v1` projection — bounded `checkpoint_id`, `checkpoint_digest`, and
`status` plus artifact IDs, next-action code, blocker IDs, and authority pointers — never Save-Game
payloads, raw transcripts, source, secrets, or customer data, enforced by schema allow-list tests.
Absence or failure is reported honestly and does not corrupt or block ordinary local authoring.

### 10. Triggers and maintenance

The trigger catalog becomes a typed, versioned contract whose detectors, actions, templates,
targets, verifiers, and runtime handlers are validated for one-to-one parity. Arbitrary shell in
catalog data is prohibited. M1 lands this typed catalog with minimal trigger authority first; v2
policy activation is the single atomic transaction described in §5, gated on validated
catalog/runtime parity.

Cursor hooks are advisory entry points only:

- global blocking hooks remain fail-open;
- `afterFileEdit` and `stop` are observation/follow-up surfaces, not enforcement;
- user hooks do not cover cloud agents;
- cloud behavior can rely only on committed project command hooks for supported events.

Commit-time checks and runnerless PR verification are the enforcement surfaces. Local-jobs may run
read-only maintenance and regenerate projections; it never repairs, commits, pushes, or changes
semantic authority unattended.

### 11. New repositories and migration

`dev-new-repo` creates eligible repositories **born v2 write-enabled** — the new-repo transaction is
itself the per-repo write-enablement grant of §5 — with baseline controls, identity/data/session
guards, worktree policy, AGENTS context, an initial project record, canonical roadmap, mutable
state, dynamic rigor profile, skill discovery, verification receipts, maintenance enrollment, and
inert runnerless PR contracts. The starting state is conformant without heavyweight feature
artifacts. Central activation of v2 governance-evaluation (§5) is a separate fleet-wide event and does
not by itself write-enable any existing repository; before central activation, a born-v2
repository's write-enabled flag is dormant and no v2 authority mutation is permitted.

Migration is identity-deduplicated, inventory-first, dry-run-first, canary-paced, cohort-based, and
receipt-backed. It records v1 receipt/freeze bindings, policy/catalog/template digests, existing
plans/ADRs/roadmaps/requirements/designs/prototypes/incidents/defects, branches/dirty/exclusion
state, cross-repository references, and delivery constraints. Each step uses a stable operation ID,
is idempotent, and records conventional progress/receipt evidence so interruption can be diagnosed
and retried without rewriting history. An existing repository's approved migration operation is its
per-repo write-enablement grant (§5); central activation alone never write-enables it. Existing
frozen artifacts are never rewritten. Every governed logical repository reaches v2 or has a tracked
reason, owner, and next action.

`chaos-scheduler` keeps ADR-0008's exact boundary: documentation governance is ON, but baseline,
runnerless fleet automation, local fleet mutation, and GSD roadmap execution remain excluded.
Checks run against its PR branch or another clean, current checkout through its own governance
path.

### 12. Security, provenance, and delivery boundaries

> The runnerless-consume-not-own boundary, no-paid-Actions rule, external Figma/Quickhost
> **provenance** (revision/source-commit/export-digest), and writable-path containment for authoring
> outputs are retained in-boundary. Autonomous-execution egress containment and a credential-owning
> delivery chokepoint are deferred to [ADR 0010](0010-agentic-execution-safety-layer-deferred.md).

- No paid GitHub Actions runners or committed CI workflows.
- No agent or plan arms native auto-merge; the reviewer App alone owns that action in enrolled
  repositories.
- Doc-warden consumes the separately governed runnerless PR-automation v3 outcome; it does not own,
  choose, implement, or arm the runnerless custom-job lane, and it waits on that control plane's
  accepted result rather than claiming its authority.
- The live (real-HOME) install of the GSD descriptor is **bounded, reversible, and
  blast-radius-contained**: isolated-home qualification precedes any real-HOME change, the preview
  writes nothing, install→uninstall is idempotent back to captured real-HOME sentinels, and any global
  blocking Cursor hook doc-warden introduces or touches is `failClosed: false`.
- No raw transcripts, credentials, tokens, customer data, unnecessary PII, or live auth state in
  artifacts, receipts, checkpoints, rollups, or dashboards.
- A local visual/design asset records path, source commit, and export SHA-256.
- An external Figma/Quickhost asset records immutable revision/version, source commit when code
  produced it, export digest, capture time, canonical owner, and URL. A moving URL without immutable
  provenance is `unverifiable` and cannot satisfy an approval gate.
- External content is evidence, never silently imported semantic authority.
- Cross-repository changes use one writer per tree and each repository's own worktree, branch, PR,
  verification, and merge path.
- Future implementation is delivered as coherent draft PRs, locally verified and reviewed with
  Bugbot until clean. Agents do not mark protected work ready or merge it outside the governed
  path.

## Why

### Alternatives considered

#### A. Continue the v1 local selected-contract implementation

Rejected as the end state. It preserves the smallest dependency surface but requires doc-warden to
recreate phase execution, plan checking, dependency waves, state routing, UAT, debugging,
handoffs, UI review, and multi-client installation already present in GSD. The current receipt and
trigger defects show the maintenance cost of parallel declarative and runtime contracts even at
v1's smaller scope.

V1 remains a compatibility/migration reader until every governed repository has an explicit v2
outcome.

#### B. Build a standalone `doc-warden` system package with its own runtime

Rejected. A new SSP would need to wrap or duplicate GSD and would create a KleinPerkins-owned
runtime release lifecycle without a second independent consumer requiring it. The local governance
overlay does not justify another product package.

#### C. Vendor or bind selected GSD workflow files through the capability lifecycle

Rejected. GSD workflow Markdown depends on its agents, templates, compiled tools, queries,
capability manifests, hooks, installer transforms, and generated registries. Selected files would
be inert or become a fork. The dependency-locked `_ops` host-overlay binding (§1) binds only the
complete exact package/commit/integrity pin — it is not a capability-lifecycle Flavor-2 binding, not
WF1 registry enrollment, and not cpp/WF2 delivery — and it never copies workflow bytes.

#### D. Reimplement only selected GSD contracts locally

Rejected as the runtime strategy. Local schemas for unique doc-warden governance are necessary,
but rebuilding GSD's execution semantics would duplicate a cohesive upstream system. The overlay
adapts interfaces and authority; it does not reproduce workflows.

#### E. Use the pinned GSD runtime without a doc-warden overlay

Rejected. GSD does not know the fleet's frozen semantic authorities, runnerless delivery,
documentation-only carve-out, external design provenance, dynamic rigor, logical fleet
deduplication, or preview-bound cross-repository reconciliation. Using it alone would leave the
mission's governance requirements ownerless.

#### F. Pinned GSD runtime plus local overlay, with per-repo execution and fleet orchestration

Chosen. It maximizes alignment with a maintained upstream execution system while retaining only
the local governance that is genuinely unique. The boundary is one-way and testable: GSD executes;
doc-warden governs and projects.

### GSD Copy / Adapt / Reject ledger

| GSD default | Decision | Blocking local constraint | Local adaptation | Compatibility / maintenance cost |
|---|---|---|---|---|
| Install current runtime through upstream installer | **Adapt** | Moving installs are not reproducible governance | Dependency-locked `_ops` host-overlay binding pins version, commit, integrity, lock, license; isolated XDG release; isolated-home canary; not WF1/registry, not cpp/WF2 | Small binding and pin-update qualification per release |
| GSD authoring/context workflows | **Adapt** | Governed authority still requires local schema, provenance, freeze, and repository ownership | Exact-pin authoring output is imported only after doc-warden validation; no autonomous implementation dispatch or hard containment claim | Upstream release qualification plus import-boundary tests |
| Native autonomous/cross-phase execution and transitive sub-dispatch | **Defer** | A same-user in-repo tool cannot enforce the proposed sandbox or delivery guarantees against itself | No v2 execution API; decision and any future implementation live under ADR 0010 | No in-boundary implementation cost |
| `PROJECT.md` as living project identity | **Adapt** | Approved product semantics freeze via successors | Current `PROJECT.md` is a projection over versioned project/PRD authorities | Projection adapter and parity tests |
| `REQUIREMENTS.md` with stable IDs and traceability | **Adapt** | Canonical nontechnical PRD must precede technical planning | Generate active requirements view from approved PRD/requirement records; preserve IDs | Mapping/schema tests |
| `SPEC.md` as falsifiable technical contract | **Copy + extend** | Needs explicit PRD/design traceability and semantic freeze | Add doc-warden metadata, PRD IDs, design IDs, version/supersession | Low additive schema cost |
| `CONTEXT.md` for implementation discretion and decisions | **Copy** | None | Keep mutable until plan acceptance, then bind relevant decisions | Low |
| `UI-SPEC.md` and post-execution UI review | **Copy + strengthen** | Fleet requires all states, accessibility, responsive coverage, immutable design provenance | Require design asset records, approval before planning, visual verification/UAT | Moderate adapter/checker rules |
| `.planning/ROADMAP.md` | **Copy + extend** | Must separate priority/sequence and serve as canonical repo roadmap | Add stable IDs, artifact set, defect/product distinction, freshness and evidence fields | Moderate schema/rendering cost |
| `.planning/STATE.md` | **Copy** | Must coexist with immutable plans and optional Save-Game | Treat as mutable execution projection with canonical plan digest | Low |
| GSD PLAN/SUMMARY and dependency waves | **Copy + extend** | Current task contract needs requirement/design IDs, rollback, evidence, escalation | Add doc-warden task fields; preserve GSD waves, dependencies, must-haves | Moderate plan adapter/checker tests |
| Checker before execution; verifier after execution | **Copy** | None | Preserve independent contexts; add doc-warden policy checks around them | Low |
| VERIFICATION and conversational UAT | **Copy + extend** | UI/sensitive work needs explicit human gates and immutable evidence | Add rigor-specific verification/UAT requirements and receipts | Moderate |
| DEBUG immutable symptoms, append-only evidence/eliminated, mutable focus/resolution | **Adapt** | Fleet needs a durable defect backlog and lifecycle | One detailed defect record per defect with GSD debug sections plus backlog metadata | Moderate schema and migration cost |
| Authoring HANDOFF/checkpoint + resume | **Adapt** | Save-Game is an existing independent capability | Store only the closed `doc-warden/save-game-pointer/v1` projection for authoring continuity; Save-Game remains optional and independent | Small adapter and schema-negative tests |
| Sketches, spikes, and 999.x backlog | **Copy** | None | Make rigor-triggered, typed artifacts related to roadmap items | Low |
| Capability overlays fail open when absent | **Adapt** | Governance cannot disappear with an optional runtime extension | Overlay improves execution UX; local CLI/commit/runnerless checks remain authoritative | Two integration boundaries, parity-tested |
| Default-on / toggleable network capabilities reachable inside autonomous execution | **Defer** | These belong to the deferred execution boundary, not authoring governance | No autonomous execution API in v2; future treatment belongs to ADR 0010 | No in-boundary implementation cost |
| GSD worktree creation | **Reject** | AWA/repository policy owns isolation; umbrella repo is excluded from AWA relocation | Configure GSD worktrees off; start in the already approved tree | Small config pin |
| Default Ship behavior, tags, and ready PRs | **Reject** | Runnerless reviewer owns merge arming; release gates are explicit | Draft PR only, no tags by default, no merge/auto-merge call | Small config and regression tests |
| Mutable in-place planning documents | **Adapt** | Approved semantic authorities are byte-frozen | Mutability ends at approval; successors carry semantic change; state/projections remain mutable | Moderate lifecycle/checker cost |
| GSD's own roadmap only | **Adapt** | Fleet needs generated cross-repo visibility without second authority | Repo roadmap remains canonical; fleet rollup is read-only and freshness-stamped | Moderate renderer/inventory cost |
| Upstream workflow source copying | **Reject** | Creates attribution and drift burden without benefit | Consume package; preserve MIT notice for any genuinely adapted substantial bytes | Lowest legal/maintenance cost |

## Consequences

### Enables

- A complete idea-to-maintenance lifecycle without locally recreating GSD's execution engine.
- Canonical PRDs, design contracts, technical specs, immutable plans/ADRs, mutable execution state,
  defects, verification, UAT, release evidence, and maintenance in one typed graph.
- Exact-pin GSD authoring/context output imported through a validated adapter to produce governed
  artifacts. Autonomous execution is deferred to ADR 0010.
- One canonical roadmap per repository and a useful fleet view without dual authority.
- Dynamic documentation rigor: governance everywhere, heavyweight artifacts only where explicit
  signals require them.
- Safe optional Save-Game continuity and GSD HANDOFF compatibility.
- Deterministic migration from v1 receipts, including explicit repair of creation-vs-freeze and
  policy/catalog version defects.

### Costs

- The local package binding and adapter must be qualified for every GSD upgrade; upstream releases
  are not consumed automatically.
- The overlay needs strict parity tests so it does not drift from pinned GSD schemas or duplicate
  upstream behavior.
- Authoring continuity must preserve the closed Save-Game pointer projection without copying private
  checkpoint payloads.
- The in-boundary live-install blast-radius contract must re-capture real-HOME sentinels each install
  and keep any doc-warden global blocking Cursor hook `failClosed: false`.
- `.planning/` becomes a governed surface and must be explicitly accommodated by each repository's
  tracking/ignore policy.
- Logical-repository inventory and migration ledgers add state, but they replace ambiguous
  checkout-row counting and prevent silent omissions.
- External design provenance may block approval when a service cannot provide immutable revision
  evidence.

### Invariants

1. One semantic authority per claim; projections are visibly derived.
2. One canonical roadmap per repository; fleet rollup is read-only.
3. Approved semantics change only through successors.
4. Automatic reconciliation never changes behavior, acceptance, approved design, architecture, or
   plan meaning.
5. Every in-boundary governance mutation uses one operation-bound
   `preview -> confirm -> apply -> verify -> receipt` flow with preimage revalidation, schema
   validation, atomic replacement, and idempotent retry. This is an operational correctness contract,
   not a same-user security boundary.
6. Exact-pin GSD output becomes authority only after doc-warden import validation. V2 exposes no
   autonomous implementation, cross-phase execution, delivery permit, or hard command/call-graph
   containment API.
7. Accepted plans remain immutable; mutable authoring state and generated projections never become
   a second semantic authority.
8. Save-Game integration is authoring-only, optional, and limited to the closed pointer projection.
9. Receipts and conventional event records are auditable evidence but make no independent
   tamper-evidence claim; stronger guarantees are deferred to ADR 0010.
10. GSD worktree, merge, auto-merge, and tag operations remain disabled under this overlay.
11. No paid GitHub Actions runners or committed Actions CI workflows are introduced.
12. `chaos-scheduler` remains documentation-only and excluded from fleet mutation/automation.
13. No raw transcripts, secrets, credentials, customer data, or unnecessary PII.
14. Missing GSD or Save-Game degrades visibly; it never fabricates completion or silently weakens
    authoritative checks.
15. The live install of the GSD descriptor is bounded, reversible, and blast-radius-contained:
    isolated-home qualification precedes any real-HOME change, install→uninstall is idempotent to
    captured sentinels, and any global blocking Cursor hook doc-warden introduces or touches sets
    `failClosed: false`.
16. Acceptance of this ADR alone authorizes no implementation. Implementation begins only after
    acceptance of this ADR and the related v2 plan plus a separate operator implementation GO;
    that GO is recorded in the accepted plan status.

## Supersession

This ADR supersedes ADR-0001's statement that the sibling Bash subsystem alone is the
complete product/runtime boundary. ADR-0001 stays byte-identical and remains the historical v1
decision.

ADR-0002 remains authoritative: reconciliation doctrine may be shared, but doc-warden does not
create a generic cross-domain runtime. ADR-0003 remains authoritative: this is local-only and has
no cpp/WF2 delivery. ADR-0008 remains authoritative for `chaos-scheduler`.

## Non-goals

- Implementing v2 in this ADR change.
- Editing the v1 policy, engine, templates, skills, hooks, configurations, receipts, or frozen
  plans/ADRs.
- Forking, patching, or contributing to the pristine GSD reference clone.
- Creating a new MCP server, generic workflow engine, or generic reconciliation service.
- Moving canonical repository roadmaps into `~/dev`.
- Automatically accepting semantic changes, resolving conflicting authorities, releasing,
  merging, or arming auto-merge.
