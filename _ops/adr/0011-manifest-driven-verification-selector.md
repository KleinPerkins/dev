# ADR 0011: Use a repository-local manifest to select verification obligations
Status: ACCEPTED — 2026-09-02 (Checkpoint 0). The operator recorded an explicit `accept` for each
of D2, D3, D4, and D5 and approved the three whole normative artifacts (this ADR, its companion
design, and its execution plan). The acceptance commit carrying those three artifacts is the
immutable operator record and freezes their bytes; the two index files remain mutable projections.
This acceptance authorizes only the M0-T01 runtime-contract bootstrap, contingent on that commit;
no selector, schema, ledger, hook, recipe, lock, policy, or verification behavior change is
authorized, and implementation GO for M1 onward remains gated by the later checkpoints.

**Companion design:** [`manifest-driven-verification-target-design-v1.md`](../plans/manifest-driven-verification-target-design-v1.md)

**Execution plan:** [`manifest-driven-verification-execution-v1.md`](../plans/manifest-driven-verification-execution-v1.md)

## Context

`KleinPerkins/dev` has valuable verification, but no shared machine-readable proof graph:

- `_ops/hooks/pre-commit` runs session-lock, data-guard, then
  `_ops/checks/verify-operating-model.sh --ci`.
- That repository gate already invokes substantial Python: doc-warden runs Python helpers and its
  v2 `unittest` suite; worktree/AWA verification uses Python helpers; context measurement runs
  Python `unittest`; and runnerless-v3 verification executes Python tooling.
- Despite that observed implementation, `_ops/POLICY.md` and `OPERATING-MANUAL.md` still describe
  the local gate as “dependency-light” and “no Python.” That documentation is stale today; the
  selector is not what first introduces Python.
- The current runnerless PR recipe runs a canned repository contract and
  `doc-warden-verify.sh --sandbox`. Its checked-in custom-job environment is empty and its lock
  exposes no dynamic PR base/head values to the repository command.
- `doc-warden-verify.sh` recursively invokes its broad verifier in six setup-failure cases.
  `worktree-verify.sh` and copy honesty can execute the kernel proof twice.
- The full suite remains the safety baseline, but broad local work is slow, the PR proof differs,
  and neither lane emits a closed selection receipt.

The desired outcome is not merely a faster command. Common narrow changes must become materially
faster while exact full proof, universal guards, and runnerless authority remain available.

## Decision

### D1 — approved architecture direction: Option 2

Adopt a **repository-local, closed-schema manifest and verification selector**. One local
obligation/dependency map governs staged pre-commit, focused local, focused PR, full, release, and
periodic/deep verification.

The implementation must preserve these properties:

1. **Exact candidate bytes.** Staged modes verify a materialized staged-index tree and bind both
   its Git tree ID and a SHA-256 candidate-tree digest. PR mode binds literal immutable base/head
   commits and their merge base. Full refuses an ambiguous dirty-working-tree default. Deep and
   release bind an exact committed SHA.
2. **Byte-safe paths.** Authoritative path identity is base64-encoded Git path bytes; the optional
   UTF-8 display text is never part of content identity. Base64 is reversible encoding, not
   sanitization; receipts permit only repository-relative path bytes and forbid
   absolute/external/private paths. Git diff uses `--no-renames`: movement is delete plus add and
   copying is an add, so triggering is the coverage-safe union without similarity heuristics.
3. **Closed, narrow grammar.** The manifest declares inputs, explicit inert classifications,
   obligations, command entrypoints, dependencies, reverse-impact ownership, modes, and execution
   constraints. `InputRule.owner_obligation_ids` is the sole direct ownership direction;
   obligation dependencies remain separate. V1's only semantic parser is strict additive JSON
   Pointer change classification for registered tiny-config inputs. Markdown, Python, shell, and
   other files remain exact/prefix/suffix file-mapped. It is not a general analyzer.
4. **Conservative classification.** JSON Pointer rules may only add obligations to file ownership.
   Unsupported parser kinds/bytes, parser or limit errors, unknown paths, stale detected metadata,
   or invalid controls run at least full, fail selector control, and block graduation.
5. **Honest completeness.** Detected missing/stale metadata forces full. An undeclared semantic
   relationship cannot detect itself; ownership declarations, reverse closure, fixture-tested
   command dependencies, mutation/golden cases, shadow parity, and periodic full comparison
   control that residual risk.
6. **Universal floor.** Session-lock, exact staged data-guard, input/manifest/selector integrity,
   repository structure/allow-list, real AWA safety/core proof under D4, offline pre-commit,
   no-cache, and no-paid-runner assertions remain universal.
7. **Unambiguous receipts.** Each obligation has scalar `focused_disposition` and
   `execution_disposition` values from `run|skip|blocked|not_applicable`, plus one sorted
   `selection_causes[]` from a closed vocabulary. Causes never masquerade as disposition or
   outcome.
   The cause vocabulary is `universal`, `direct`, `dependency`, `reverse_impact`, `fallback`,
   `self_protection`, `full_mode`, `deep_mode`, `inert`, and `not_applicable`.
   Scalar precedence is blocked, not-applicable, effective full/deep/self-protection/fallback run,
   other selected run, then skip.
8. **Minimal evidence system.** Only three new closed schemas exist in v1: manifest, receipt, and
   rollout ledger. One append-only rollout ledger carries authority acceptance, acceptance
   evidence, observations, graduation, invalidation, rollback, and restoration events. Every append
   is anchored to the immutable prior-event prefix, and every event carries a once-only logical
   credit key so replay or retry cannot double-count evidence.
9. **Shadow first.** M1 predicts locally while the current full command remains authoritative.
   Unexecuted logical rows use `execution_disposition:not_applicable`,
   `outcome:not_observed`, and null exit/duration, and link a separate validated full receipt over
   the identical source; they never claim pass.
   Nothing can skip until actual full-mode exactly-once parity, recursive/double-run removal,
   universal AWA proof, durable lane invalidation, cadence controls, selector proof, and performance
   evidence all pass.
10. **Full/deep remain.** Full runs every applicable non-deep-only obligation exactly once. Deep
    adds every applicable deep-only obligation once. Focused proof never substitutes at a required
    full, release, or periodic gate.
11. **Correctness before optimization.** Execution is sequential and uncached in v1. Parallelism is
    out of v1 scope and, if ever needed, is a separate successor that must first prove byte-identical
    selection and outcomes versus sequential execution.
12. **Local and runnerless.** Pre-commit has no network dependency. Remote verification stays on
    the existing runnerless controller; no GitHub Actions workflow or paid hosted/self-hosted
    runner is introduced.
13. **One-repository scope.** The implementation remains local to `KleinPerkins/dev`. Option 3
    remains deferred until a second real repository consumer exists.

### Proposed defaults requiring explicit Checkpoint 0 disposition

Checkpoint 0 must record `accept`, `reject`, or `replace` for **each** row. No omission, silence, or
general approval decides one.

| ID | Proposed default |
|---|---|
| **D2 — Cadence** | Deep remains available locally on demand. Exact releases and selector/manifest/hook/verification-harness changes force `full`. Existing runnerless infrastructure runs `full-release` for each fixed ISO week against exact current `main`, due at Monday 00:00 UTC plus 24-hour grace. It runs `deep-periodic` for each fixed calendar month, due at next-month 00:00 UTC plus 48-hour grace: full plus mutation/live-environment checks and selector-versus-full replay over 20 recent exact changes, or all if fewer. Each period's expiry is policy-derived and non-sliding — completion time never extends it — and restoration needs fresh in-window proof only for the schedule that expired. Local and PR cadence are independent lane envelopes: local runs are source-bound and expiry-gated, and the PR lane runs full/deep only within a qualified controller envelope (a longer job or atomically aggregated exact-source shards) with no paid runner. |
| **D3 — Speed outcomes** | Common narrow categories are `change.digest_only`, `change.docs_ordinary`, and `change.doc_warden_core`. For each category and lane proposed for focus, collect 20 paired cold end-to-end runs over identical candidate bytes under preserved current/full and focused execution. Category speedup is the median of `min(current_ms, full_ms) / focused_ms`; graduation requires ≥3.0×. Report 5× as the target. Report 10–20× for tiny low-surface changes as aspirational only, never a safety gate. Focused absolute budgets remain ≤3/≤5/≤12 minutes respectively, with at least 19 of 20 focused runs inside budget and any tighter lane cap. |
| **D4 — AWA** | Real AWA engine-off safety enforcement and core-contract proof are universal. Expensive simulations run for AWA/shared-input changes, uncertainty, full, and deep. Kernel proof becomes one named executor; copy honesty consumes its closed result instead of rerunning it. |
| **D5 — Graduation** | At least 100 structured cases: 20 staged-source, 20 exact-PR, 20 classifier/fallback, 20 dependency/reverse-impact, 10 self-protection, and 10 receipt/isolation/cleanup cases; every declared edge is challenged. Each lane also needs 10 consecutive real `main` changes with zero missed obligations and zero focused-pass/full-fail mismatch, deterministic sanitized receipts, no residue, durable invalidation/rollback proof, and D3 proof. Before a lane's focus, that lane's schedules must be active with consumer-bound evidence, initial activation proofs must pass, non-sliding expiry evidence must be persisted, and missing/late/invalid/expired/cross-bound latest-required-period evidence must durably invalidate focus to full until governed restoration of only the expired schedule. Activation proofs authorize only until the first expiry. Graduation and Checkpoint 4 are per lane; local graduates on local evidence without the controller. A miss adds a fixture, reruns the corpus, and resets the streak. |

### Two-step acceptance and bootstrap

**Step 1 — Checkpoint 0 and documentation acceptance merge.** Checkpoint 0 approves one versioned
documentation contract or approves nothing. Its operator record must:

1. explicitly decide D2, D3, D4, and D5 one by one;
2. approve the three whole artifacts: the whole ADR, whole target design, and whole execution plan;
3. authorize one documentation-only acceptance merge containing exactly those three artifacts plus
   the ordinary ADR-index and plan-index row additions;
4. name the candidate accepted statuses and one immutable operator-record reference;
5. record that both new plans were direct-classified or classified through an isolated staged
   index, because `doc-warden.sh check .` discovers only tracked plans; and
6. authorize the documentation acceptance merge and, contingent on its exact immutable commit,
   M0 only.

The acceptance merge's immutable commit SHA freezes the three whole normative artifacts as they
exist in that commit. The two index files remain ordinary mutable projections in the repository's
established convention: they carry no frozen-range digest and may be re-sorted or re-styled later
without a successor transaction.

**Step 2 — M0-T01 runtime-contract bootstrap.** Only after that merge, M0-T01 creates the three
schema files and rollout ledger. Its genesis event mirrors the immutable acceptance commit,
per-artifact SHA-256 digests, and explicit D2–D5 decisions, and records no index-range digest.
Schema and ledger bytes do not exist at Checkpoint 0 and are not approved bytes in Step 1.
Later implementation progress never edits the accepted ADR, design, or plan.

## Why

### Alternatives considered

#### Keep the broad suite on every commit

Rejected as the steady state. It preserves proof but cannot explain selection or deliver the
required speed outcome. It remains authoritative throughout shadow and is the parity reference.

#### Path globs only

Rejected. Paths are useful ownership inputs but cannot represent shared consumers or prerequisites
without explicit forward and reverse dependency edges.

#### Option 2 — local manifest and selector

Chosen. There is one repository consumer, existing local checks, Python 3.11 already in both local
verification and the runnerless image, and established JSON conventions. A narrow local grammar
keeps the change reviewable without creating a second fleet verification product.

#### Option 3 — centralized/fleet service

Deferred until a second repository has a real matching need. Generalizing now adds authority,
versioning, and rollout costs without a second consumer.

#### Cache or parallelize first

Rejected. Caching complicates proof identity and invalidation; parallelism complicates process and
resource ownership. Neither proves selector correctness or the required paired speed outcome.

## Consequences

### Enables

- Exact, auditable staged/PR/full/deep decisions.
- At least 3× proven end-to-end improvement for each common category that is activated.
- Removal of recursive and duplicate proof before any omission is allowed.
- One minimal ledger for acceptance, performance, graduation, invalidation, and rollback evidence.
- Weekly `full-release` and monthly `deep-periodic` comparison without paid Actions runners.

### Costs and dependencies

- Every tracked path needs explicit manifest ownership or an explicit inert classification.
- Exact snapshots and byte-safe paths require careful Git plumbing and cleanup.
- Local shadow and local focused activation can ship without remote support; only PR focus requires
  the controller. Current repository authority does not expose PR base/head to custom jobs and does
  not qualify the AWA image for Dev.
- Any controller contract change belongs to its owning repository and requires separate
  authorization. Recipe, lock, assignment, and any planner-required fleet relock remain serial.
- The 100-case corpus, real-change streak, paired measurements, active surveillance schedules and
  canaries, and launch rollback proof add deliberate pre-launch time.

### Invariants

- A selector defect may add work; it must not create a false green.
- No focused execution occurs before that lane's explicit launch checkpoint; graduation and
  Checkpoint 4 are per lane, and local focus never waits on controller work.
- Full/deep omit no applicable obligation and execute each obligation exactly once.
- Detected uncertainty runs full; unknown undeclared semantics remain a measured residual risk, not
  a falsely claimed self-detection.
- Staged verification never silently reads working-tree candidate bytes or silently verifies HEAD.
- Focus requires a fail-closed lane-state meet: manifest, ledger, and persisted lane state must
  agree on one enforce generation with valid consumer-bound evidence, or the lane runs full.
- Ledger appends are prefix-anchored and credit each logical key once; surveillance and graduation
  evidence is consumer-bound to its lane, manifest, schema, generation, schedule, and source.
- Focus is eligible only when every derived change tag is graduated for the lane; an empty,
  ambiguous, control, or unmatched change forces full.
- An enforce-time fallback to full is representable and honest: it emits a full-execution receipt
  with an explicit fallback cause, never a skip.
- Pre-commit remains offline; v1 has no result cache; no paid runner is introduced.
- Receipts and ledger events contain no source body, raw diff/log/environment, secret, operator
  text, private absolute path, or temp path.
- Existing session-lock, data-guard, history integrity, runnerless verifier/reviewer ownership, and
  AWA engine-off guarantees remain.
- Neither the selector nor this plan calls or recommends `gh pr merge --auto`.
- `chaos-scheduler` remains untouched.

## Post-acceptance boundary

Checkpoint 0 approved the documentation acceptance merge on 2026-09-02:

- D2–D5 are accepted;
- the ADR, design, and execution plan are Accepted and frozen by the acceptance commit; the two
  index files remain mutable projections;
- no selector, manifest runtime, schema, ledger, test, hook, recipe, lock, policy, or verification
  behavior change is yet authorized; schema/ledger creation begins only in Step 2/M0-T01, contingent
  on the immutable acceptance commit; and
- the current verification behavior remains authoritative until a lane's later checkpoint GO.

## Changelog

- 2026-09-02 — Checkpoint 0 acceptance. The operator recorded `accept` for D2, D3, D4, and D5,
  approved the three whole artifacts, authorized the documentation-only acceptance merge (exactly
  the three artifacts plus the ordinary ADR/plan index rows), and direct-classified both new plans.
  The acceptance commit is the immutable operator record and freezes the three artifacts; ADR,
  design, and plan status move to Accepted. M0-T01 is authorized contingent on that commit; no other
  implementation is authorized.
- 2026-09-02 — Draft hardening pass (pre-Checkpoint-0), from a proportional swarm review of the full
  body of work. Tightened: lane-specific graduation/Checkpoint 4 with the local lane independent of
  the controller; non-sliding, policy-derived surveillance expiry with consumer-bound evidence and
  once-only credit keys; prefix-anchored ledger appends; a fail-closed lane-state reducer; a durable
  `decomposed` full-profile cutover; task/checkpoint acceptance proof bundles; an enforce-time
  fallback receipt; an operator-facing explanation surface; and PR cadence lane envelopes. Removed:
  the speculative parallelism milestone and the separate index-range freeze (the two index files are
  mutable projections). At the time of that entry no implementation was authorized and all artifacts
  remained PROPOSED/DRAFT pending Checkpoint 0, which subsequently accepted them (see the entry above).
