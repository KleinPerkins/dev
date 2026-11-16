# Manifest-driven verification selector — target design

**Version:** v1
**Status:** ACCEPTED — 2026-09-02 (Checkpoint 0). Frozen normative design; no implementation is
authorized beyond the M0-T01 bootstrap contingent on the acceptance commit.
**Date:** 2026-09-02
**Owning repository:** `KleinPerkins/dev` (`~/dev`)
**Plan-type:** standard
**Review provenance:** Option 2 direction approved; revised after independent review and a
proportional swarm hardening pass against live `origin/main`
`c0a7c0fe0eae1c54e81ec114ad7db05917d28098` (worktree branch `cursor/2b907899`). D2–D5 accepted at
Checkpoint 0 on 2026-09-02; see ADR 0011 changelog for the hardening and acceptance summary.
**Governing decision:** accepted [ADR 0011](../adr/0011-manifest-driven-verification-selector.md)
**Execution plan:** [`manifest-driven-verification-execution-v1.md`](manifest-driven-verification-execution-v1.md)

**Goal:** Define the smallest exact verification-selection contract that can prove meaningful
speed improvement without weakening existing proof.
**Architecture:** Exact staged or committed bytes feed one closed repository-local manifest. A
sequential selector/runner emits sanitized receipts; one closed rollout ledger carries acceptance,
observations, graduation, invalidation, rollback, and restoration evidence. Full remains
authoritative through shadow and becomes exactly-once before focus is enabled.
**Tech stack:** Existing Python 3.11 and Bash verification, Git plumbing, JSON, three closed JSON
schemas, stdlib tests, and existing runnerless PR automation.

---

## Global Constraints

- This design authorizes no implementation.
- Preserve session-lock, exact staged data-guard, full proof, AWA engine-off behavior,
  history-integrity rulesets, and runnerless verifier/reviewer ownership.
- Pre-commit is offline. No result cache exists in v1. No GitHub Actions workflow or paid
  hosted/self-hosted runner may be introduced.
- M1 is local shadow only. Remote capability gaps cannot block it.
- Nothing may skip until decomposition, actual full exactly-once parity, universal AWA proof,
  durable lane invalidation, cadence controls, selector proof, and paired speed proof pass.
- Option 3 remains deferred until a second real repository consumer exists.
- `chaos-scheduler` remains untouched.

## 1. Authority and freeze boundary

The authority flow has exactly two steps.

**Step 1 — Checkpoint 0 and documentation acceptance merge.** The operator explicitly decides each
of D2–D5, approves the three whole normative artifacts, and authorizes one documentation-only
acceptance merge that also refreshes the ADR and plan index rows:

1. the complete ADR 0011 bytes;
2. the complete target-design bytes; and
3. the complete execution-plan bytes.

Checkpoint 0 authorizes one documentation-only acceptance merge containing exactly those three
whole artifacts plus the ordinary ADR-index and plan-index row additions. That merge's immutable
commit SHA freezes the three whole normative artifacts as they exist in that commit. The two index
files remain ordinary mutable status projections in the repository's established convention: they
are not frozen authorities, carry no normalized-range digest, and may be re-sorted or re-styled
later without a successor transaction. The accepted design and plan are never edited for progress; a
material correction requires successor artifacts.

**Step 2 — M0-T01 runtime-contract bootstrap.** Only after the acceptance merge, M0-T01 creates the
three schema files and rollout ledger. The genesis event mirrors the acceptance commit SHA and each
whole-artifact SHA-256/length, plus explicit D2–D5 decisions, the operator-record reference, and
direct-classification evidence. It records no index-range digest. Schema and ledger bytes do not
exist at Checkpoint 0 and are not part of its three approved artifacts.

`doc-warden.sh check .` uses `git ls-files` for plans and therefore does not enumerate new untracked
plans. Checkpoint 0 must additionally call `dwl_classify_plan_file` for both plan paths or validate
them through an isolated staged index. A green broad check without that direct result is
insufficient acceptance evidence.

## 2. Observed baseline

### 2.1 Existing Python is current reality

The selector does **not** introduce Python to a no-Python gate. Current repository verification
already includes:

- Python helpers and the full doc-warden v2 `unittest` suite inside
  `_ops/checks/doc-warden-verify.sh`;
- Python parsing/helpers throughout `_ops/checks/worktree-verify.sh`;
- direct Python `unittest` execution for context measurement in
  `_ops/checks/verify-operating-model.sh`;
- Python profile tooling in runnerless-v3 verification; and
- a Python 3.11.2 tool in the exact runnerless lock inventory.

`_ops/POLICY.md` and `OPERATING-MANUAL.md` nevertheless call the local gate dependency-light and
“no Python.” That wording is stale now. M0 corrects those two documents before selector work and
changes no verification behavior.

### 2.2 Current proof topology

| Surface | Observed behavior | Target implication |
|---|---|---|
| Pre-commit | session-lock → data-guard → `verify-operating-model.sh --ci` | Preserve order; bind data/selection/execution to one staged candidate |
| Repo full | structure, doc-warden, legacy/v3 PR automation, worktree/AWA, snow-kit, context, static invariants | Preserve as shadow authority and parity baseline |
| Local default | repo proof plus installed Cursor/Codex/Claude parity | Model host applicability explicitly |
| Runnerless PR | canned contract + `doc-warden-verify.sh --sandbox` | Different proof; cannot be treated as local full |
| doc-warden | six setup-failure cases recursively call broad verifier | Extract before launch |
| AWA | kernel proof may run directly and through copy honesty | Deduplicate before launch |

### 2.3 Current runnerless capability facts

Read-only evidence in this repository proves:

- `.github/pr-recipe.json` has an empty custom-job `environment`;
- `.github/pr-automation.lock.json` also has an empty runtime environment for Dev's custom job;
- the recipe/lock `source_ref.base_sha` binds protected **recipe provenance**, not a PR base SHA;
- rollout evidence elsewhere proves the controller knows exact PR heads for checks/approval, but no
  repository-local authority here proves that immutable PR base/head values are injected into a
  custom command;
- Dev uses `stdlib-shell.v1`, network `none`, credentials `none`, and a 300-second job cap;
- the qualification ledger classifies Dev's historical custom candidate as `canned_only`;
- a digest-pinned `awa-authoritative-verify.v1` image exists, but its assignment is to
  `KleinPerkins/awa`, not Dev.

Therefore exact PR argument injection, Dev-specific AWA runtime qualification, periodic
current-main/deep operation, and durable remote lane invalidation are dependency gates. They are
not assumed capabilities. Local M1 shadow needs none of them.

## 3. Terms

| Term | Meaning |
|---|---|
| **Candidate tree** | Exact staged or committed repository bytes being verified |
| **Candidate-tree digest** | SHA-256 over canonical path-byte/mode/blob-SHA256 rows |
| **Input** | One explicit manifest ownership rule for tracked path bytes |
| **Inert classification** | Explicit reviewed declaration that a tracked path needs only universal proof |
| **Obligation** | One named proof command with dependencies, cost, and execution constraints |
| **Forward closure** | All prerequisites required by selected obligations |
| **Reverse impacted closure** | All consumers that can be affected when an owned/shared input changes or disappears |
| **Shadow** | Predict focus and emit evidence, but execute authoritative full; no omission |
| **Full** | Every applicable non-deep-only obligation once |
| **Deep** | Full once plus every applicable deep-only obligation once |
| **Rollout ledger** | One closed append-only event log for authority and rollout evidence |

## 4. Minimal component layout

```text
_ops/verification/
  README.md
  verification-manifest.schema.json
  verification-receipt.schema.json
  verification-rollout-ledger.schema.json
  verification-manifest.json
  verification-rollout-ledger.json
  contracts.py
  selector.py
  runner.py
  test_contracts.py
  test_selector.py
  test_runner.py
  fixtures/
_ops/checks/verify-changes.sh
```

There are exactly three new schemas: manifest, receipt, and rollout ledger. There is no separate
acceptance schema, observation store, graduation file, static-analysis product, cache, scheduler,
or second dependency registry.

Data flow:

```text
explicit lane + exact source
  -> candidate tree + SHA-256 digest
  -> byte-safe change rows
  -> closed manifest validation
  -> explicit input ownership/inert match
  -> direct owners + reverse impacted consumers
  -> additive strict JSON Pointer obligations where registered
  -> forward prerequisite closure
  -> fallback/self-protection
  -> deterministic plan
  -> isolated sequential execution
  -> content-addressed sanitized receipt
  -> validated rollout-ledger event
```

## 5. Closed schema concepts

### 5.1 Manifest: `dev-verification-manifest/v1`

This section is explanatory. Normative field-level wire bytes are frozen in Appendix A.

All objects reject unknown fields. Top-level fields are:

| Field | Contract |
|---|---|
| `schema`, `schema_version` | Literal manifest schema name and integer version |
| `manifest_id`, `manifest_version` | Appendix-A content identity and positive revision |
| `repository_id`, `selector_api_version` | Exact repository/API binding |
| `receipt_contract`, `ledger_contract` | Exact dependent schema names/versions |
| `activation` | Monotonic per-lane shadow/enforce generation; ledger graduation binds exact manifest ID |
| `modes` | `pre_commit`, `focused_local`, `focused_pr`, `full`, `full_release`, `deep_periodic` |
| `input_rules` | Exact/prefix/suffix path-byte ownership rules |
| `inert_rules` | Explicit tracked path rules requiring only universal proof |
| `semantic_selectors` | Additive-only strict JSON Pointer change refinements |
| `obligations` | Closed obligation objects |
| `cause_codes` | Closed selection-cause vocabulary |
| `cost_classes` | Time/resource limits |
| `exclusive_groups` | Non-overlap resource IDs |
| `control_rule_ids` | Fixed selector/manifest/hook/harness/evidence self-protection input IDs |

Every tracked path at the candidate tree must match at least one `input_rules` matcher or exactly
one `inert_rules` matcher. Input-rule matches conservatively union; input/inert overlap or no match
is invalid and forces full. Deleting a path evaluates ownership from the base tree.

Each obligation has:

- stable `id`, operator-safe `description`, fixed argv array, and byte-safe repository-relative cwd;
- direct ownership exists only in `InputRule.owner_obligation_ids`; `depends_on` is the separate
  obligation dependency-edge authority and reverse impact is derived;
- universal modes, eligible modes, and applicability predicates;
- `deep_only`, cost class limits, execution scope, hermeticity, exclusive group, network policy,
  environment allowlist, success exits/sentinel, and bounded-output policy.

`argv` is literal; no shell string, interpolation, command substitution, `eval`, or caller text.
Entrypoint/command dependencies are explicitly declared and fixture-tested. V1 does not parse
general shell, Python, or Make syntax. A small inventory check validates only:

1. manifest-declared command files exist in the candidate tree;
2. configured command references named in the manifest match exact expected argv; and
3. every registered harness entrypoint is owned by a control input.

Unsupported dynamic dispatch inside a registered harness is a control failure and full fallback;
the implementation does not grow an AST analyzer.

### 5.2 Receipt: `dev-verification-receipt/v1`

Every receipt carries:

- `schema`, `schema_version`, `receipt_id`, and `created_at`;
- selector version, `manifest_id`, activation generation, command digests, and source binding;
- exact `SourceBinding`;
- canonical byte-safe changes;
- receipt mode, requested/effective mode, lane, and activation generation;
- sorted logical rows: shadow predicts all applicable obligations; the linked transitional M1 full
  receipt may have no logical rows when broad output cannot attribute them;
- one aggregate execution row and, in shadow, an exact authoritative full-receipt link;
- cleanup/process/temp/object-store proof; and
- monotonic integer timing observation.

`receipt_id` is the sole receipt content identity. Appendix A defines its canonical derivation by
excluding only `receipt_id`; there is no separate `receipt_sha256`.

One obligation row has:

- `obligation_id`;
- scalar `focused_disposition`:
  `run|skip|blocked|not_applicable`;
- sorted unique `selection_causes[]`;
- scalar `execution_disposition` from the same four-value vocabulary;
- `outcome`: `passed|failed|timed_out|cleanup_failed|not_observed|null`;
- command/source digests, exit code or null, duration or null, and fixed diagnostic code.

Cause codes include `universal`, `direct`, `dependency`, `reverse_impact`, `fallback`,
`self_protection`, `full_mode`, `deep_mode`, `inert`, and `not_applicable`.
Precedence is:

1. `blocked`;
2. `not_applicable`;
3. effective full/deep/self-protection/fallback `run`;
4. universal/direct/reverse-impact/dependency `run`;
5. `skip`.

Causes accumulate and sort; precedence chooses one focused scalar. In M1 shadow, every logical row
uses the Appendix-A shadow tuple and links to a separate validated authoritative full receipt over
the identical `SourceBinding`; no unobserved obligation is reported passed.

Receipts include reversible base64 encodings of repository-relative Git path bytes. Base64 is not
sanitization. Receipts exclude source bodies, patches, logs, raw environments, secrets, operator
text, absolute/external paths, usernames/home paths, network identifiers, and temp paths.

### 5.3 Rollout ledger: `dev-verification-rollout-ledger/v1`

The one ledger root has the exact closed shape in Appendix A and an append-only `events[]` chain.
Every event includes:

- closed `event_type`;
- `event_version`;
- one content-addressed `event_id`;
- `previous_event_id`, null only for genesis;
- UTC timestamp;
- exact source commit/tree and candidate-tree digest where applicable;
- manifest/receipt/ledger-schema versions and digests;
- provenance kind plus immutable command, check, PR, or operator-record reference; and
- a closed event payload.

Event variants:

| Event | Payload |
|---|---|
| `authority_genesis` | Immutable acceptance commit, three whole-artifact digests, schema digests, and explicit D2–D5 dispositions |
| `acceptance` | AC ID, milestone, status, exact evidence refs/digests |
| `observation` | Receipt refs, lane/category, paired current/full/focused milliseconds and ratio |
| `graduation` | Lane/tag set, corpus/edge/streak/budget/speed/cadence/invalidation proof digests |
| `invalidation` | Lane, generation, closed reason, detecting receipt/check |
| `rollback` | Lane, from/to generation, local/controller durable-state and manifest rollback refs |
| `restoration` | Prior invalidation, currently required passing period evidence, and governed activation generation |

Unknown event/version/status/provenance is invalid. Events never contain source or raw output.
Rewriting, reordering, or deleting an earlier event breaks the chain.

## 6. Exact source and path semantics

### 6.1 Data types

```python
@dataclass(frozen=True)
class PathIdentity:
    path_b64: str                 # authoritative raw Git path bytes
    path_utf8: str | None         # optional exact decoding; non-authoritative

@dataclass(frozen=True)
class SourceBinding:
    repository_id: Literal["KleinPerkins/dev"]
    source_kind: Literal["staged_index", "pull_request", "commit"]
    candidate_tree_sha256: str
    manifest_id: str
    selector_version: Literal["1"]
    base_commit_sha: str | None
    head_commit_sha: str | None
    merge_base_sha: str | None
    index_tree_sha: str | None
    commit_sha: str | None

@dataclass(frozen=True)
class Change:
    status: Literal["add", "modify", "delete", "type_change"]
    old_path: PathIdentity | None
    new_path: PathIdentity | None
    old_mode: str | None
    new_mode: str | None
    old_blob_sha256: str | None
    new_blob_sha256: str | None
```

`candidate_tree_sha256` hashes canonical rows of path bytes, mode, and content SHA-256 for every
tracked candidate entry. It is present in receipts and every replay/graduation event. Git tree IDs
remain useful object identities but do not replace this digest.

### 6.2 Git diff policy

All change discovery uses raw NUL-delimited plumbing, `--no-renames`, no external diff, no
textconv, fixed configuration, and a sanitized environment. A move is delete plus add. A copy is
add. Direct obligations are the union of old-path reverse impact and new-path ownership. This
deliberately performs extra work instead of trusting similarity scoring.

Paths are never decoded to choose ownership. Manifest path rules operate on canonical path-byte
encodings or rigorously bounded ASCII prefixes. Optional UTF-8 display is diagnostic only.

### 6.3 Entrypoint source matrix

| Entrypoint | Required source | Refusal rule |
|---|---|---|
| pre-commit shadow/focused | Captured staged index, materialized tree, candidate-tree digest | Refuse moving/unmerged/ambiguous index; never use working-tree candidate bytes |
| focused local | Explicit staged `--index-file`, materialized as a candidate tree | No committed/implicit/working-tree source |
| local full | Explicit staged index or exact committed SHA | Bare dirty-working-tree/HEAD default refuses |
| runnerless PR | Literal controller-supplied base/head; exact checkout=head; recorded merge base | No `HEAD^`, branch lookup, local `origin/main`, or execution-VM fetch |
| full-release | Exact committed release SHA/tag object resolved before no-network execution | No moving tag/branch |
| deep-periodic | Exact committed current-main SHA captured by controller | No later re-resolution |

No command may silently verify HEAD instead of the candidate bytes. A compatibility `make verify`
may remain for humans, but selector/full evidence is valid only through an explicit source-bound
entrypoint.

### 6.4 Staged capture

After session-lock:

1. derive the real index;
2. write its tree using a temporary object directory with repository objects as read-only
   alternates;
3. create the candidate-tree SHA-256;
4. reconstruct one private mode-0600 index and mode-0700 source snapshot;
5. run exact-index data-guard, selector, and repo-content proof against that same snapshot;
6. rederive live staged tree/digest before success and refuse drift; and
7. remove all private index/object/source/log roots and reap all children.

Unstaged or untracked decoys cannot alter candidate classification or execution. The thin live
hook contains no classifier or dependency map. Unstaged divergence in a pre-snapshot guard blocks
focus and records control failure.

## 7. Selection and completeness

For a focused request:

1. map each new/modified input to all declared owners;
2. map each deleted/old input to all owners from the base manifest/tree;
3. add strict JSON Pointer obligations for registered JSON inputs without removing file owners;
4. walk reverse impacted closure to every declared consumer;
5. walk forward prerequisite closure;
6. add universal obligations;
7. apply fallback/self-protection; and
8. topologically sort by level then ID and deduplicate.

Focus eligibility is a separate gate evaluated before any skip and never itself selects an
obligation. Derive the complete change-tag set as the union of `classification_tags` from every
matching `InputRule` across all changed paths, adding an explicit `inert` token for each change
whose only match is an `InertRule`. Focus is eligible for a lane only when that change-tag set is
non-empty and every member is present in the lane's active `graduated_tags`. Any ungraduated tag,
any control input, any unmatched path, and any empty or otherwise ambiguous change-tag set force
effective full.

For full, replace the selected set with all applicable non-deep-only IDs. For deep, add all
applicable deep-only IDs. Every ID executes once.

Detected missing/stale metadata includes invalid references, cycles, unmatched tracked paths,
missing command files, stale configured argv, unknown control inputs, incompatible schema/API, or
missing base controls. These force full and leave selector control failed.

An entirely undeclared semantic relationship is not intrinsically detectable. Controls are:

- explicit multi-owner/shared inputs;
- reverse impacted closure for deletes/shared changes;
- fixture tests for every command and declared edge;
- mutation of every declared edge;
- golden changes for shared helpers and generated projections;
- M1–M3 shadow against authoritative full;
- 10 real-main comparisons before launch; and
- weekly `full-release` plus monthly `deep-periodic` selector/full replay activated before launch
  and continued afterward.

## 8. Modes and proposed cadence

| Mode | Meaning |
|---|---|
| `pre_commit` | Local staged lane; shadow until launch, offline always |
| `focused_local` | Explicit staged-index candidate tree; only graduated tags |
| `focused_pr` | Exact PR source; only independently graduated tags |
| `full` | All applicable non-deep-only obligations once |
| `full_release` | Full bound to exact release/current-main committed source |
| `deep_periodic` | Full once plus mutation, adversarial, live-environment, and surveillance obligations |

Under proposed D2:

- exact releases and selector/manifest/hook/harness/control changes force `full`;
- `full_release` runs weekly on an exact current-`main` SHA through existing runnerless
  infrastructure;
- `deep_periodic` runs monthly and includes selector-versus-full replay over 20 recent exact
  changes, or all if fewer; and
- deep remains available locally on demand against an exact committed SHA.

Both recurring schedules become active before their own lane's Checkpoint 4: the local schedules
before local focus, the PR schedules before PR focus. Weekly authority uses fixed ISO week IDs with
Monday 00:00 UTC period ends plus 24-hour grace; monthly authority uses fixed calendar-month IDs
with next-month 00:00 UTC ends plus 48-hour grace. Each period's `deadline_at` (end plus grace) is a
fixed, policy-derived, non-sliding expiry; completion time never extends it. At every focus attempt
each schedule requires a consumer-bound passing proof for its latest expired period, or the
pre-first-expiry activation proof, over the exact current-main SHA. Missing, late, invalid,
wrong-source, or expired evidence and any clock/period failure durably invalidate focused lanes and
force full. Restoration needs fresh in-window proof only for the schedule that expired, reuses the
still-valid proof of any unexpired schedule, and completes through a governed `restoration` event;
old or late evidence never silently reenables focus.

Surveillance runs on independent lane envelopes: the local lane's schedules are source-bound local
runs that gate only local focus, and the runnerless PR lane's schedules run on the existing
controller and gate only PR focus. Neither lane's surveillance is a prerequisite for the other, and
local focus never waits on controller schedule readiness. Appendix A.7 is normative.

This vocabulary is normative. “Weekly deep” and “deep on every control edit” are not D2.

## 9. Universal proof and fallback

Universal requirements:

- session-lock and exact staged data-guard;
- exact input binding and candidate-tree SHA-256;
- manifest/schema/selector/runner integrity;
- repository structure and allow-list;
- real AWA engine-off/core proof under D4;
- receipt/ledger validation and sanitation;
- offline-capable pre-commit;
- no result cache; and
- no GitHub Actions workflow or paid runner.

Control inputs include all three schemas, manifest, selector, runner, shim, hook, Makefile wiring,
registered harnesses, rollout ledger graduation/invalidation events, PR recipe/lock, and accepted
normative artifacts.

Ambiguity, unsupported input, detected stale metadata, or control changes set effective mode to
full. Invalid controls run the preserved broad fallback when safely source-bound and still fail the
overall run. Fallback is never silent and never turns invalid metadata green.

**Operator-facing explanation.** A single non-schema renderer maps every closed `diagnostic_code`
and `invalidation` reason to one plain-language line — cause, safety consequence, and next action —
so a non-technical operator sees why a run fell back to full, blocked, or invalidated a lane. The
same renderer output appears identically from the pre-commit path and an explicit `verify-changes
explain` CLI entrypoint. It reads only existing receipt/ledger codes, adds no new store, schema, or
operator-editable configuration, and never turns a red or full run green.

## 10. Receipt storage, import, and replay

Pre-commit writes receipts outside the working tree under:

```text
$(git rev-parse --git-path verification-selector)/receipts/sha256/<receipt-id-hex>.json
```

The state root is mode 0700; receipts are mode 0600 and written temp-file + fsync + atomic rename.
The filename and receipt ID equal the validated content digest. Failed validation leaves no final
file. Bounded retention removes old successful local receipts after their observation event is
imported; invalidation/failure receipts remain only as sanitized content-addressed evidence.

`verify-changes rollout-import --receipt <path>`:

1. validates schema, digest, sanitation, source binding, and provenance;
2. rejects paths outside the Git-local receipt root;
3. appends only a closed ledger event;
4. records the receipt digest/reference, never its source/log body; and
5. rewrites no earlier event.

A staged receipt becomes replayable graduation evidence only after an exact commit tree has the
same candidate-tree SHA-256. Otherwise it may inform local timing but cannot satisfy real-main
streak or replay requirements.

## 11. Isolation and process cleanup

Each obligation runs sequentially in its own process group with fixed argv/cwd, allowlisted
environment, `PYTHONDONTWRITEBYTECODE=1`, bounded output/files/descriptors/PIDs/time, and an owned
mode-0700 temp root. Timeout/interruption sends TERM, bounded wait, KILL, wait/reap, then verifies
no owned child, path, index, object, worktree, or bytecode remains. Cleanup failure is red.

V1 executes sequentially only; there is no parallel runner, wave scheduler, or DAG scheduling in
scope. The manifest still carries declarative `depends_on`, `exclusive_group`, and cost/resource
bounds, but v1 uses them for ordering, per-obligation limits, and documentation — not concurrent
scheduling. Parallelism is deferred to a separate successor, authored only if measured sequential
results miss an accepted budget; that successor must first prove selection, cause precedence, row
order, and outcome reduction are byte-identical to sequential execution.

## 12. Performance contract

Common narrow categories are:

| Category | Closed definition | Proposed focused budget |
|---|---|---:|
| `change.digest_only` | Only approved schema-valid digest/ref scalar values change; no shape/path/control change | ≤3 minutes |
| `change.docs_ordinary` | Markdown only, outside policy/template/generated/index/authority/executable regions | ≤5 minutes |
| `change.doc_warden_core` | Registered doc-warden core inputs, excluding selector/shared critical harness inputs | ≤12 minutes |

A paired observation uses identical candidate-tree SHA-256, manifest, lane, machine/runner class,
resource limits, and cold setup. It runs:

1. preserved current broad source-bound execution;
2. manifest full; and
3. would-be focused.

Order alternates across pairs. No selector/test result is reused. The implementation does not claim
to flush privileged OS caches.

For pair `i`:

```text
reference_ms_i = min(current_ms_i, full_ms_i)
ratio_i = reference_ms_i / focused_ms_i
category_speedup = median(ratio_1 .. ratio_20)
```

Graduation for each category/lane requires:

- 20 valid paired observations;
- category speedup ≥3.0×;
- 5× target reported as met/missed;
- 10–20× tiny-change aspiration reported but never gated;
- at least 19/20 focused runs within the 3/5/12-minute budget; and
- every focused run within any tighter lane timeout (the current runnerless cap is 300 seconds).

Performance failure delays that category; it never removes proof.

Full and deep are known to exceed ten minutes and do not fit one 300-second runnerless job. The
local lane runs full/deep as source-bound local cadence with no such cap. The PR lane never enables
focus until its full/deep surveillance fits a separately qualified controller envelope — either a
qualified longer job or exact-source shards whose partial results are atomically aggregated,
fail-closed, and cover every applicable obligation exactly once — all with no paid runner. A
category that cannot meet its lane envelope stays shadow in that lane.

## 13. AWA treatment

Under proposed D4:

- `awa.kernel-core` is universal and executes the real engine-off/core contract;
- runtime absence is `blocked`, never passed/not-applicable;
- copy honesty consumes the closed kernel result and never starts the kernel verifier;
- expensive AWA simulations trigger on AWA/shared inputs, uncertainty, full, and deep;
- local focus requires the real local core proof;
- PR focus requires a Dev-qualified pinned AWA image/runtime; and
- AWA product authority remains in `KleinPerkins/awa`.

The current repository proves that the authoritative image exists for the AWA repository, not that
Dev may use it. Dev qualification is a launch gate, not an M1 local-shadow prerequisite.

## 14. Proof inventory

| Current proof intent | Target obligation/group | Inputs/modes | Dependencies | Cost/isolation | Migration |
|---|---|---|---|---|---|
| session ownership | `gate.session-lock` | every staged run | none | host/repo lock | preserve M1 |
| staged secret/PII/size | `gate.staged-data` | every staged run | session lock | exact private index | preserve/strengthen M1 |
| source/manifest/receipt | `verify.input`, `verify.manifest`, `verify.receipt` | universal | explicit | pure | M1 |
| structure/allow-list/rule source | `dev.structure`, `dev.allowlist`, `dev.rule-source` | universal/owned | manifest | pure/temp Git | M1 |
| installed tool parity | `dev.installed-rules` | local applicable | rule source | host exclusive | M1 |
| doc-warden broad proof | `doc.full-compat` → named doc groups | doc inputs/full/deep | structure | temp files/Git | M1 shadow; M3 split |
| six recursive setup failures | `doc.failure-injection` | setup/cross-repo/full/deep | doc contracts | isolated exclusive | M3 extract |
| legacy/v3 PR automation | `pr.legacy`, `pr.v3` | PR-control inputs/full/deep | structure | temp Git | M1 parent |
| runnerless repository contract | `remote.repository-contract` | PR universal | exact PR source | no-network VM | M3 qualify |
| AWA host/core/simulations | `awa.host`, `awa.kernel-core`, `awa.simulations` | universal core; relevant simulations | structure/manifest | host/AWA exclusive | M1 shadow; M3 split |
| copy honesty | `awa.copy-honesty` | copy inputs/full/deep | kernel result | pure/result input | M3 deduplicate |
| snow-kit lifecycle | `snowkit.host-lifecycle` | owned/full/deep | structure | temp HOME | M1 parent |
| context measurement | `context.measurement` | owned/full/deep | structure | temp files | M1 parent |

Every tracked path maps to one or more inputs or explicit inert input. Every target obligation has
declared command fixtures, direct owner references from input rules, forward prerequisites, reverse
consumers, cost, hermeticity, exclusivity, and migration milestone.

## 15. Graduation and launch safeguards

Graduation and Checkpoint 4 are **lane-specific**: local focus and PR focus each graduate on their
own evidence, and the runnerless/controller dependencies gate only the PR lane. M2 proves the
proposed D5 corpus and shadow evidence for both lanes.

**Local-lane launch (independent of controller work).** Before local Checkpoint 4:

- recursive doc-warden setup proof extracted;
- duplicate AWA/kernel execution removed and real universal AWA core qualified for the local lane;
- manifest full and deep actually execute each obligation once;
- preserved-current versus target-full proof sets/outcomes match on exact sources;
- durable Git-local lane invalidation, the fail-closed lane-state reducer, and rollback drill pass;
- the local weekly `full-release` and monthly `deep-periodic` source-bound cadence is active, its
  first proofs pass, non-sliding expiry validates, and missed/late/invalid/expired evidence durably
  invalidates local focus to full until governed restoration;
- offline/no-cache/no-paid-runner assertions pass;
- 100-case corpus, every declared edge mutation, and 10 real-main streak pass;
- paired D3 absolute budgets and ≥3× category speedup pass for the local lane; and
- receipt/ledger sanitation, cleanup, and auditable skip reasons pass.

**PR-lane launch (additionally requires controller work).** Before PR Checkpoint 4, all local-lane
guarantees hold for the PR candidate lane **and** the separately governed controller gates pass:
qualified immutable PR base/head injection, a Dev-qualified AWA runtime, a qualified no-network
recipe/lock within the controller cadence envelope, controller-owned durable invalidation, and the
fleet blast-radius controls of §17. Absent any of these, PR focus stays shadow/full while the local
lane may already be enforcing.

Checkpoint 4 is taken per lane and explicitly approves that lane's activation generation, exact
lane/tag set, graduation event digest, and prepared rollback generation. It is the **first**
authority that may permit a skip in that lane.

Durable invalidation:

- local lane: atomically persisted Git-local lane state outside the working tree; missing,
  malformed, stale, or invalidated state forces shadow/full;
- runnerless lane: controller-owned persisted invalidation state through a separately qualified
  contract; absent support prohibits PR focus;
- rollout ledger: imports the closed invalidation event; and
- checked-in manifest: a reviewed later generation records durable shadow rollback.

“Instant rollback” is not promised across machines. The detecting run fails immediately; local or
controller state disables its lane immediately; cross-surface durability completes through the
governed rollback generation.

**Lane-state reduction.** Three sources describe each lane: the checked-in manifest activation, the
rollout ledger, and the persisted local (or controller) lane state. A single fail-closed safety-meet
reducer decides effective policy: a lane may focus only when all three independently agree on the
same single enforce `activation_generation` and that generation has valid, consumer-bound evidence;
any absence, staleness, malformed state, or disagreement among the three reduces to full. Ordering is
crash-safe: activation writes the ledger graduation and reviewed manifest generation first and the
persisted enabled state last, while invalidation persists the disabled state and ledger invalidation
before the detecting run returns failure, so an interrupted transition can only fail closed to full.

## 16. Migration sequence

1. **M0 — authority and truth.** Mirror the acceptance-merge-frozen authority into genesis, create
   the three inert schemas, then correct the already-false no-Python governance prose.
2. **M1 — local end-to-end shadow.** Exact staged selector/runner/receipt storage runs locally;
   preserved full remains authoritative and nothing skips.
3. **M2 — selector/evidence proof.** Narrow ownership grammar, corpus, edge/reverse-impact tests,
   paired baselines, real-main shadow, and read-only controller/AWA preflight.
4. **M3 — launch safeguards.** Decompose recursion/duplication, prove actual full exactly once,
   qualify universal AWA, durable invalidation, remote source/cadence contracts, and all D3/D5
   launch evidence.
5. **M4 — focused activation.** Only Checkpoint-4-approved lane/tags may skip; exercise reversible
   invalidation and observe first focused changes.
6. **M5 — steady-state hardening.** Measure and harden the already-live weekly
   `full-release`/monthly `deep-periodic` surveillance; M5 is not schedule activation. Parallelism
   is out of v1 scope; if ever needed it is a separate successor, not a milestone here.

Rollback always moves a lane to shadow/full. Never delete the full entrypoint, rewrite history,
rewrite accepted authorities, or discard evidence.

## 17. Risks and controls

| Risk | Control |
|---|---|
| Unknown semantic edge | Explicit ownership/reverse consumers, goldens/mutations, long shadow, periodic full comparison; no self-detection claim |
| Staged verifier reads working tree | Exact snapshot, candidate-tree SHA-256, decoy fixtures, end-of-run index recheck |
| Path decode collision | Base64 path-byte identity; UTF-8 display never authoritative |
| Rename heuristic omits owner | `--no-renames`; delete+add union |
| Full parity is only modeled | M3 execution-count and preserved-current/target-full runtime parity before launch |
| False speed win | Same-byte paired current/full/focused runs; faster reference baseline; ≥3× median |
| Stale activation survives failure | Fail-closed local/controller lane state plus ledger/manifest rollback |
| Remote capability assumed | Read-only preflight and separate owner-repository gate |
| Controller change expands fleet scope | Planner-reported affected-set/relock plan; no assumed global or Dev-only blast radius |
| Evidence leaks content | Closed schemas, content addresses, sentinels, bounded Git-local storage |
| Selector becomes second product | Three schemas, one ledger, explicit narrow grammar, no analyzer/cache/scheduler |

## 18. What not to change

- Do not enable focus before M4/Checkpoint 4.
- Do not claim model-level exactly-once as executed full parity.
- Do not claim unknown undeclared edges detect themselves.
- Do not add a fourth evidence schema/store, general language analyzer, cache, or scheduler.
- Do not infer source from working tree, HEAD, branch names, or recipe provenance fields.
- Do not update remote/controller authority without a separate accepted owner-repository plan.
- Do not hand-edit generated locks, combine recipe/lock phases, or pre-arm auto-merge.
- Do not weaken session-lock, data-guard, AWA core, full/deep, cleanup, or sanitation.
- Do not introduce Actions workflows, paid runners, networked pre-commit, or Option 3.
- Do not touch `chaos-scheduler`.

## 19. Checkpoint 0 decisions

D1 is the approved direction. D2 cadence, D3 speed/budgets, D4 AWA treatment, and D5 graduation are
the exact defaults in ADR 0011; Checkpoint 0 recorded `accept` for each on 2026-09-02 and authorized
the three-artifact documentation acceptance merge in §1. That acceptance commit, followed by M0-T01
genesis mirroring, is the only authority flow. Implementation beyond the contingent M0-T01 bootstrap
remains gated by the later checkpoints.

## Appendix A — normative v1 wire contract

This appendix is normative. M0-T01 translates it into three schema files and golden fixtures; it
does not choose new fields, enums, ordering, identity, matcher, period/grace, or privacy behavior.

### A.1 Restricted canonical JSON profile

All three contracts and every hash input use this dependency-free profile:

1. Input is UTF-8 without BOM. Invalid UTF-8, duplicate object keys, unpaired Unicode surrogates,
   floats, exponent/decimal numbers, NaN/Infinity, and integers outside signed 64-bit range are
   rejected.
2. Strings preserve Unicode scalar values exactly; no NFC/NFD or case normalization occurs. The
   encoder escapes only quote, backslash, and the C0 controls U+0000–U+001F: it uses the short
   escapes `\"`, `\\`, `\b`, `\f`, `\n`, `\r`, `\t` for those exact code points and lowercase
   `\u00xx` for every other C0 control. It never escapes any other scalar (including U+007F and all
   non-ASCII, which emit as literal UTF-8), never emits an uppercase-hex or non-minimal `\u`
   escape, and never `\u`-escapes a code point that has a short escape. Canonical-input validation
   rejects any other escaping.
3. Objects reject unknown keys. Keys serialize in ascending lexicographic order of their UTF-8
   bytes.
4. Integers serialize as minimal base-10; the encoder emits `0`, never `-0`, and canonical-input
   validation rejects lexical `-0` rather than coercing it. Booleans/null use lowercase literals.
5. Separators are exactly `,` and `:` with no surrounding whitespace. Hashed bytes have no BOM and
   no trailing newline.
6. Arrays preserve order only when this appendix says `ordered`; arrays marked `set` must be unique
   and sorted by canonical UTF-8 bytes. Implementations reject noncanonical set order rather than
   silently sorting input.
7. IDs use `sha256:<64 lowercase hex>`. `manifest_id` hashes the canonical manifest object with
   only `manifest_id` omitted. `receipt_id` hashes the canonical receipt object with only
   `receipt_id` omitted. `event_id` hashes the canonical event object with only `event_id` omitted.
   No second digest field exists for those objects.
8. A schema digest hashes the canonical schema JSON bytes under this same profile. A command digest
   hashes canonical `{argv,cwd_b64,environment_allowlist}`. The candidate-tree digest hashes the
   ordered candidate-entry array defined in A.5.

Canonical stored objects include their computed ID and still use this profile. Golden fixtures
must pin exact bytes and IDs for one valid/invalid manifest, staged/PR/commit receipts, genesis plus
each event variant, Unicode paths, and every set-order rejection.

### A.2 Shared scalar and path types

`Sha256Id` is `sha256:<64 lowercase hex>`. `CommitSha` is exactly 40 lowercase hexadecimal
characters for the current Git object format. UTC timestamps are RFC 3339
`YYYY-MM-DDTHH:MM:SSZ`, whole seconds only.
Every field named `*_sha256`, `sha256`, `*_digest`, or `*_id` that this appendix identifies as a
content identity uses `Sha256Id`, unless it is explicitly an obligation/tag/range token.

`PathValue` is a closed object:

| Field | Required | Contract |
|---|---|---|
| `path_b64` | yes | RFC 4648 standard base64 with required padding, decoding to nonempty repository-relative Git path bytes |
| `path_utf8` | no | Exact UTF-8 decoding of those same bytes; omit if bytes are not valid UTF-8 |

Decoded path bytes must contain no NUL, leading `/`, empty component, `.`/`..` component, or
trailing `/`. Base64 is reversible encoding, **not sanitization or redaction**. Receipts and ledger
events may carry only these repository-relative path values; absolute paths, external paths,
usernames, home-directory prefixes, temp paths, and host paths are forbidden.

### A.3 Manifest object

The manifest top-level object has exactly these required fields; no field is optional:

| Field | Type/ordering |
|---|---|
| `schema` | literal `dev-verification-manifest` |
| `schema_version` | literal integer `1` |
| `manifest_id` | `Sha256Id`, derived by A.1 |
| `manifest_version` | positive integer |
| `repository_id` | literal `KleinPerkins/dev` |
| `selector_api_version` | literal `1` |
| `receipt_contract` | closed `{schema:"dev-verification-receipt",schema_version:1}` |
| `ledger_contract` | closed `{schema:"dev-verification-rollout-ledger",schema_version:1}` |
| `modes` | set containing exactly `pre_commit,focused_local,focused_pr,full,full_release,deep_periodic` |
| `cause_codes` | set containing exactly the codes in A.6 |
| `cost_classes` | set of `CostClass` objects sorted by `id` |
| `exclusive_groups` | set of lowercase dot-token strings |
| `input_rules` | set of `InputRule` objects sorted by `id` |
| `inert_rules` | set of `InertRule` objects sorted by `id` |
| `semantic_selectors` | set of `SemanticSelector` objects sorted by `id` |
| `control_rule_ids` | set of input-rule IDs |
| `obligations` | set of `Obligation` objects sorted by `id` |
| `activation` | closed `Activation` object |

IDs are lowercase dot-separated tokens matching `[a-z0-9]+(?:[.-][a-z0-9]+)*`.

`Matcher` has exactly `{kind,value_b64}`. `kind` is `exact|prefix|suffix`; `value_b64` is padded
base64 of raw bytes. Exact bytes are one complete valid repository-relative path. Prefix bytes are
nonempty, contain no forbidden path component, and end in `/`. Suffix bytes are nonempty, begin
with `.`, and contain no `/`. Matching is byte equality, byte prefix, or byte suffix only—no glob,
regex, negation, case folding, path decoding, or executable expression.

`InputRule` has exactly:

```text
{id,matcher,owner_obligation_ids,classification_tags}
```

`owner_obligation_ids` is a nonempty set and is the sole file-to-obligation ownership authority.
`classification_tags` is a set used only for rollout eligibility/reporting and never selects an
obligation. All matching input rules union owners/tags. `InertRule` has exactly
`{id,matcher,reason_code}` where `reason_code` is literal
`inert`. A tracked path must match at least one input rule or exactly one inert rule; matching both
is invalid. Multiple input rules are allowed and conservatively unioned.

`SemanticSelector` has exactly:

```text
{id,baseline_input_rule_ids,parser,limits,pointer_rules}
```

`baseline_input_rule_ids` is a nonempty set represented as a JSON array, with no duplicates, sorted
by InputRule ID using A.1's canonical UTF-8-byte ordering. Every member must reference an existing
`InputRule` in this manifest. For example:

```json
"baseline_input_rule_ids":["config.digest","config.refs"]
```

The semantic selector applies when **any** referenced InputRule matcher matches an applicable
changed path: new path for add, old path for delete, and the union of old/new paths for modify or
type change. Every matching referenced InputRule's baseline owner obligations still apply and
union before semantic pointer additions. Empty/missing, duplicate, unsorted, or unknown IDs
invalidate the manifest, force source-bound full fallback, fail selector control, and block
graduation.

`parser` is the sole v1 literal `json_pointer_changes_v1`. `limits` has exactly:

```text
{max_blob_bytes:1048576,max_depth:64,max_nodes:100000,
 max_changed_pointers:10000,max_number_chars:128}
```

Limits apply independently to each old/new blob before matching. Exceeding any limit forces full,
fails selector control, and blocks graduation; no partial pointer set is used.
`max_blob_bytes` counts raw blob bytes. Root depth is zero and each object/array child increments
depth by one. `max_nodes` counts each decoded JSON value once; object keys are not nodes.
`max_changed_pointers` applies after ancestor closure and deduplication. `max_number_chars` counts
the complete UTF-8 number token including sign, decimal point, and exponent.

Each `pointer_rules` member has exactly
`{pointer,match,add_obligation_ids}`. Rules sort by pointer UTF-8 bytes, then `match`, then canonical
`add_obligation_ids`; the obligation-ID set is nonempty and every ID must exist. `pointer` is an
RFC 6901 JSON Pointer: root is `""`; object tokens escape `~` as `~0` and `/` as `~1`; any other
escape is invalid. `match` is `exact|descendant_prefix`. Exact requires equality.
Descendant-prefix matches the configured pointer itself or a child beginning with the configured
pointer plus `/`; root matches all emitted pointers.

The parser accepts only repository blobs that are strict UTF-8 with no BOM. It rejects duplicate
object keys, parse errors, NaN/Infinity, and number tokens over 128 characters; finite JSON numbers
are parsed with stdlib arbitrary-precision decimal semantics for value comparison. Object
additions, deletions, scalar value/type changes, and container type changes emit that pointer plus
all ancestors through root. Add compares the new blob, delete the old blob, and modify compares
both. Objects recurse over the UTF-8-byte-sorted union of keys. Any array value or shape change
emits only the array pointer plus ancestors—never unstable element indexes. Emitted pointers are
unique and UTF-8-byte sorted.
This repository-blob parser is separate from A.1 canonical contract JSON: finite decimal/exponent
numbers are valid blob values but never valid manifest/receipt/ledger numbers.

Semantic rules only add obligations to the conservative `InputRule.owner_obligation_ids` union.
They cannot remove an obligation/tag, make a path inert, or suppress file-level ownership.
Markdown, Python, shell, and all non-registered JSON paths remain exact/prefix/suffix file-mapped
in v1. A new parser kind requires a manifest schema/version change; until approved it is unknown,
forces full, fails selector control, and blocks graduation.

`Applicability` has exactly:

```text
{lanes,platforms,source_kinds,required_capabilities}
```

All are sets. Enums are lanes `local|runnerless_pr`, platforms `darwin|linux`, source kinds
`staged_index|pull_request|commit`; capabilities are lowercase dot-token IDs. Empty sets mean no
restriction for that dimension. A missing required capability yields `blocked`, never
`not_applicable`.

`CostClass` has exactly:

```text
{id,timeout_seconds,memory_mib,pids,output_bytes}
```

All numeric values are positive integers.

`Obligation` has exactly these required fields:

```text
{id,description,argv,cwd_b64,depends_on,
 universal_in,eligible_in,deep_only,applicability,cost_class,execution_scope,
 hermeticity,exclusive_group,network,environment_allowlist,success_exit_codes,
 stdout_sentinel}
```

`argv` is an ordered nonempty array of strings. `cwd_b64` decodes under the same path constraints.
ID/tag/mode/environment arrays are sets. Every
`InputRule.owner_obligation_ids`/semantic-added obligation ID must resolve here.
`depends_on` is the sole dependency-edge authority; reverse consumers are derived from it.
No obligation contains a reciprocal ownership field. `deep_only` is boolean. Enums are:

- `execution_scope`: `index_snapshot|commit_snapshot|host_read`;
- `hermeticity`: `pure|temp_files|temp_git|host_runtime`;
- `network`: `forbidden|not_required`.

`exclusive_group` and `stdout_sentinel` are required nullable strings. `success_exit_codes` is a
nonempty sorted set of integers. Unknown references, cycles, ineligible dependencies, secret-like
environment names, shell-string argv, or missing candidate entrypoints are invalid.

`Activation` has exactly `{generation,full_profile,lanes}`. `generation` is positive.
`full_profile` is exactly `preserved_aggregate|decomposed` and gates whether transitional empty-row
full receipts are accepted (A.6). `lanes` is an ordered
two-item array, first `local`, then `runnerless_pr`. Each lane record has exactly:

```text
{lane,policy,graduated_tags}
```

`policy` is `shadow|enforce`; `graduated_tags` is a set and must be empty in shadow. Focus
eligibility over `graduated_tags` follows §7's conservative rule: focus only when every derived
change-tag is graduated for the lane, else full. Enforce
requires one valid ledger graduation event whose lane, exact candidate `manifest_id`, tags,
required surveillance event IDs, and generation match, and each of whose referenced surveillance and
drill events is independently consumer-bound per A.7. The manifest does not embed `event_id`, so
manifest/event content identities are not circular.

### A.4 SourceBinding and candidate source variants

`SourceBinding` is closed and every field below is required, using null only as specified:

```text
{repository_id,source_kind,candidate_tree_sha256,manifest_id,selector_version,
 base_commit_sha,head_commit_sha,merge_base_sha,index_tree_sha,commit_sha}
```

Common fields are `repository_id:"KleinPerkins/dev"`, `candidate_tree_sha256:Sha256Id`,
`manifest_id:Sha256Id`, and `selector_version:"1"`.

| `source_kind` | Required non-null | Required null |
|---|---|---|
| `staged_index` | `index_tree_sha`; `base_commit_sha` except unborn repositories | `head_commit_sha`, `merge_base_sha`, `commit_sha` |
| `pull_request` | `base_commit_sha`, `head_commit_sha`, `merge_base_sha` | `index_tree_sha`, `commit_sha` |
| `commit` | `commit_sha` | `base_commit_sha`, `head_commit_sha`, `merge_base_sha`, `index_tree_sha` |

Unborn staged source uses null `base_commit_sha`; this is the only exception. PR merge base must be
an ancestor of head and derived from the supplied immutable base/head. Commit/release/deep binds
the exact commit tree. Source kind, manifest ID, and selector version participate in every receipt
and evidence identity.

### A.5 Candidate entries, changes, and rename/copy policy

The candidate-tree hash input is an ordered array of closed entries
`{path_b64,mode,blob_sha256}` sorted by decoded `path_b64` bytes. `path_b64` is the authoritative
raw Git path-byte base64 string only; the optional `path_utf8` display field never participates in
this array or in any content identity. `mode` is the six-digit Git mode
string; `blob_sha256` hashes exact blob bytes. The array itself uses A.1 canonical JSON and its
SHA-256 becomes `candidate_tree_sha256`. Identical authoritative path bytes therefore always yield
one candidate-tree identity regardless of whether a display decoding is present.

A receipt `Change` has exactly:

```text
{status,old_path,new_path,old_mode,new_mode,old_blob_sha256,new_blob_sha256}
```

Status is `add|modify|delete|type_change`; path/mode/blob fields are required nullable and must
match the status variant. Changes sort by decoded `(new_path or empty,old_path or empty)` bytes,
then status.

Git rename/copy detection is disabled. Movement is delete plus add; a copy is add. Old-path owners
and reverse consumers union with new-path owners and prerequisites. Similarity heuristics never
affect identity or selection.

### A.6 Receipt object

The receipt top level has exactly these required fields:

```text
{schema,schema_version,receipt_id,created_at,repository_id,selector_version,
 manifest_id,lane,mode,requested_mode,effective_mode,activation_generation,
 source,changes,rows,authoritative_receipt_id,aggregate_execution,timing,cleanup}
```

Literals are `schema:"dev-verification-receipt"`, `schema_version:1`, and
`repository_id:"KleinPerkins/dev"`. `receipt_id` derives by A.1 and is the only receipt content
identity. `lane` is `pre_commit|focused_local|runnerless_pr|local_full|release|periodic`;
`mode` is `shadow|enforce|full|full_release|deep_periodic`; requested/effective mode uses the
manifest mode enum. `source` is A.4; `changes` is ordered per A.5; rows sort by `obligation_id`.
Shadow requires requested mode `pre_commit|focused_local|focused_pr` and effective mode `full`.
Enforce with granted focus requires matching requested/effective
`pre_commit|focused_local|focused_pr`. Enforce fallback requires requested mode
`focused_local|focused_pr` with effective mode `full` and is valid only when at least one logical
row carries a `fallback` or `self_protection` cause; its logical rows are observed full rows (never
the shadow tuple), `authoritative_receipt_id` is null, and the aggregate is an observed full
execution with `selection_causes:["full_mode"]` and `diagnostic_code:"full.authoritative"`. This is
the only enforce receipt whose requested and effective modes differ, and it records a real executed
full rather than a skip. Full,
full-release, and deep-periodic require their corresponding requested/effective manifest mode.

Each row has exactly:

```text
{obligation_id,focused_disposition,execution_disposition,selection_causes,
 outcome,command_digest,exit_code,duration_ms,diagnostic_code}
```

Both disposition enums are `run|skip|blocked|not_applicable`. `selection_causes` is a set sorted
lexicographically and limited to:

```text
universal,direct,dependency,reverse_impact,fallback,self_protection,
full_mode,deep_mode,inert,not_applicable
```

Scalar precedence is: `blocked`; `not_applicable`; effective
`full_mode|deep_mode|self_protection|fallback` run;
`universal|direct|reverse_impact|dependency` run; then skip. Multiple causes remain in the sorted
array. Outcome is `passed|failed|timed_out|cleanup_failed|not_observed|null`; non-run rows require
null outcome, exit code, and duration except for the exact shadow tuple below. Run rows require a
nonnegative duration; passed/failed rows require an integer exit code, while timeout/cleanup
failure requires null if no child exit exists. `command_digest` is always `Sha256Id`;
`diagnostic_code` is a closed lowercase dot-token.

`aggregate_execution` has exactly:

```text
{executor_id,execution_disposition,selection_causes,outcome,command_digest,
 exit_code,duration_ms,diagnostic_code}
```

In `mode:"shadow"`, every logical obligation row is a prediction, not an execution:

```text
execution_disposition = not_applicable
outcome = not_observed
exit_code = null
duration_ms = null
diagnostic_code = shadow.unobserved
```

Its `focused_disposition` and sorted `selection_causes` retain the predicted focused decision.
This is the only context where `not_applicable` execution may pair with `not_observed`; it never
means passed.

Every shadow receipt requires non-null `authoritative_receipt_id` linking a separately validated,
content-addressed receipt in the same Git-local receipt store with `mode:"full"`. The linked full
receipt's `SourceBinding` must be canonically byte-identical—including repository, source kind,
candidate-tree digest, manifest ID, selector version, and every variant field—and its
`aggregate_execution` must byte-equal the shadow receipt's aggregate. That aggregate has
`execution_disposition:"run"`, `selection_causes:["full_mode"]` exactly, an observed non-null
outcome and duration, normal exit-code rules, and `diagnostic_code:"full.authoritative"`.

The authoritative full receipt is written and validated first. Missing/invalid linkage, unequal
source, altered ID, non-full mode, aggregate mismatch, or unobserved aggregate rejects the shadow
receipt, blocks graduation, and stores no final shadow receipt. The observed full outcome remains
the hook authority; no per-obligation result is inferred. Shadow/full comparison compares
predicted selected IDs to the full proof inventory and aggregate safety outcome in M1; only after
M3 decomposition may it compare independently observed per-obligation outcomes.

All non-shadow receipts require `authoritative_receipt_id:null`. Their logical rows obey the normal
disposition/outcome rules; full/full-release aggregate selection causes are exactly `["full_mode"]`
and deep-periodic exactly `["deep_mode"]`.
The transitional M1 full receipt linked from shadow has `rows:[]` because only the aggregate broad
executor is observed. Empty full rows are valid only under a named transitional profile, not merely
because a lane is shadow: the receipt's bound `manifest_id` must resolve to a manifest generation
whose `activation.full_profile` is `preserved_aggregate`, and the receipt must carry
`aggregate_execution.executor_id:"preserved.full"`. The immutable M3-T03 decomposition advances the
manifest to a `decomposed` generation; from that generation onward every full/deep receipt requires
one observed row for every applicable obligation, and an empty-row receipt is rejected regardless of
lane policy. Empty full rows never satisfy exactly-once, parity, graduation, or post-decomposition
evidence.

`timing` has exactly
`{snapshot_ms,selection_ms,execution_ms,cleanup_ms,total_ms}`. `cleanup` has exactly
`{children_reaped,temp_removed,index_removed,objects_unchanged,bytecode_absent,diagnostic_code}`.
Durations are nonnegative integers; cleanup flags are booleans.

Receipts contain PathValue objects and therefore expose reversible repository-relative path bytes.
They must contain no file content, raw patch, stdout/stderr body, environment value, secret,
operator text, absolute/external/host/temp path, username/home component, or network identifier.

### A.7 Rollout ledger and events

The ledger root has exactly:

```text
{schema,schema_version,repository_id,acceptance_commit_sha,created_at,events}
```

Literals are `schema:"dev-verification-rollout-ledger"`, `schema_version:1`, and
`repository_id:"KleinPerkins/dev"`. `acceptance_commit_sha` is the immutable Step-1 merge commit.
`events` is ordered append-only; it is never sorted or rewritten.

Every event has exactly:

```text
{event_id,event_type,event_version,previous_event_id,occurred_at,repository_id,
 acceptance_commit_sha,manifest_id,source,receipt_ids,schema_links,provenance,payload}
```

`event_version` is literal `1`; repository/acceptance fields equal the root. `manifest_id` and
`source` are required nullable. `receipt_ids` is a set. `schema_links` has exactly
`{manifest,receipt,ledger}`; each nested object has exactly `{schema,schema_version,sha256}` with
the corresponding literal contract name/version and schema digest. `provenance` has exactly
`{kind,reference,reference_sha256}` where kind is
`operator_record|local_command|runnerless_check|pull_request`. `reference` is a closed per-kind
token, never free text, a URL, an absolute/host path, or a username: for `operator_record` it is
`sha256:<64hex>` over the operator record's canonical bytes; for `local_command` it is the
`sha256:<64hex>` command digest of A.1(8); for `runnerless_check` it is the controller Check
identifier matching `^[A-Za-z0-9._-]{1,128}$`; for `pull_request` it is `pr/<digits>` for this
repository. `reference_sha256` is the `Sha256Id` binding that same immutable referent. Any other
shape is a privacy/validation failure and is rejected.

Genesis is first, has `event_type:"authority_genesis"` and `previous_event_id:null`. Every later
event has `previous_event_id` exactly equal to the immediately preceding `event_id`. `event_id`
derives by A.1 and therefore commits to the complete prior chain link. Missing, duplicate,
reordered, altered, or forked links are invalid.

Closed payloads:

- `authority_genesis`:
  `{artifact_digests,d2_d5_decisions,direct_classifications}`. Artifact entries
  are the three sorted `{path,sha256,byte_length}` values for the whole ADR, target design, and
  execution plan. Decision entries are ordered
  D2,D3,D4,D5 and contain `{id,disposition,replacement_sha256}` with
  `accept|reject|replace`; replacement digest is null unless replaced. Direct classifications are
  sorted `{path,result,tool_sha256}` where result is `conformant|nonconformant`. These authority
  `path` values are the exact three known ASCII repository-relative artifact paths, not arbitrary
  filesystem paths. Genesis records no index-range digest; the two index files are mutable
  projections bound only by the immutable acceptance commit.
- `acceptance`: a task/checkpoint proof bundle `{bundle_scope,milestone,criteria}` where
  `bundle_scope` is the task or checkpoint ID, `milestone` is its milestone, and `criteria` is a
  nonempty array of `{ac_id,status,evidence_ids}` sorted by `ac_id`, each status
  `passed|failed|blocked|superseded` and each `evidence_ids` a set. Each `ac_id` appears at most
  once per ledger and is one logical credit key.
- `observation`:
  `{observation_kind,lane,category,schedule,schedule_activated_at,period_id,period_end_at,
  grace_seconds,deadline_at,bootstrap,completed_at,outcome,current_ms,full_ms,focused_ms,
  ratio_millionths}`. Observation kind is
  `paired_speed|real_change|full_release_weekly|deep_periodic_monthly`. Lane is
  `local|runnerless_pr`; outcome is `passed|failed|blocked`. Non-surveillance events require null
  schedule/period timestamps/grace and `bootstrap:false`; timings/category are nullable where not
  applicable. For paired-speed events `current_ms`, `full_ms`, and `focused_ms` are positive
  integers with `focused_ms >= 1`. Ratios are nullable outside paired speed and otherwise a
  non-negative integer millionths value, never a float, computed by exact integer arithmetic whose
  intermediate product uses arbitrary-precision integers (never a float or 64-bit truncation) as
  `floor(min(current_ms,full_ms)*1000000/focused_ms)`. A missing or non-positive `focused_ms`, or a
  non-integer timing, invalidates the event rather than yielding a ratio.
- `graduation`:
  `{lane,tags,activation_generation,corpus_digest,edge_digest,streak_digest,budget_digest,
  speed_digest,required_surveillance_event_ids,invalidation_drill_event_ids}`. All ID/tag arrays
  are sets. Each referenced surveillance and drill event must be consumer-bound: its `event_type`,
  `lane`, `manifest_id`, `schema_links`, target `activation_generation`, schedule/control, and exact
  commit `source` must equal this graduation's, so evidence from another lane, manifest, schema, or
  generation can never satisfy it. Each schedule requires one consumer-bound, in-window passing
  expiry proof (A.7 surveillance) at the target generation.
- `invalidation`:
  `{lane,activation_generation,reason,detected_at,detection_evidence_id}`.
  `detection_evidence_id` is a `Sha256Id` for the detecting receipt/check record. Reason is
  `safety_mismatch|receipt_invalid|ledger_invalid|cleanup_failed|surveillance_missed|
  surveillance_invalid|control_drift`.
- `rollback`:
  `{lane,from_generation,to_generation,invalidation_event_id}`; the common `manifest_id` is the
  rollback target.
- `restoration`:
  `{lane,invalidation_event_id,required_period_event_ids,restored_generation,
  graduation_event_id}`. It requires one consumer-bound, in-window passing period event for each
  schedule whose current window has expired, reuses the still-valid in-window event of any schedule
  that has not expired, and binds a valid current graduation and a governed activation generation.
  Old, expired, or cross-binding evidence never restores focus.

**Logical credit keys and reduction.** A content-addressed `event_id` proves byte identity but does
not itself bound how often an outcome is counted. Every non-genesis event therefore has a canonical
type-specific logical credit key, and the ledger reducer credits each key at most once:

- `acceptance`: `{acceptance, ac_id}` for each contained criterion;
- surveillance `observation`: `{schedule, period_id, lane}`; paired/real `observation`:
  `{observation_kind, lane, category, candidate_tree_sha256}`;
- `graduation`: `{graduation, lane, activation_generation}`;
- `invalidation`: `{invalidation, lane, activation_generation, reason, detection_evidence_id}`;
- `rollback`: `{rollback, lane, from_generation, to_generation}`;
- `restoration`: `{restoration, lane, invalidation_event_id}`.

A failed or retried attempt is a distinct event with its own `event_id` and may reuse its logical
key; the reducer keeps the first passing credit per key and treats any second, conflicting passing
credit for the same key as a `ledger_invalid` control failure rather than additional credit. A
task/checkpoint acceptance bundle is therefore safe: each contained `ac_id` is one credit key, so
bundling never double-counts and every criterion keeps an auditable status and evidence set.

For surveillance, `schedule` is `weekly_full|monthly_deep`; `schedule_activated_at`, period fields,
grace, deadline, and completion are non-null. Weekly periods use valid ISO-8601 week IDs
`YYYY-Www`, begin Monday 00:00:00Z, end the next Monday 00:00:00Z, use
`grace_seconds:86400`, and require `deadline_at = period_end_at + 86400 seconds`. Monthly periods
use valid calendar IDs `YYYY-MM`, begin the first day 00:00:00Z, end the next month's first day,
use `grace_seconds:172800`, and require `deadline_at = period_end_at + 172800 seconds`. Period ID,
end, grace, and deadline are rederived and equality-checked; they are never caller-defined
authority, and `deadline_at` is the period's non-sliding expiry that completion time never extends.
The common event `source` must be a commit `SourceBinding` for the exact current-main SHA captured
at dispatch, at least one validated `receipt_id` is required, and `event_id` is the sole period
evidence ID. Every surveillance event is consumer-bound: `schedule`, `lane`, `manifest_id`,
`schema_links`, and target `activation_generation` bind it to the one lane, manifest, schema, and
generation that may consume it, so no other lane/manifest/generation can reuse it.

The first validated bootstrap event fixes `schedule_activated_at` independently for each schedule;
every later event must repeat that exact timestamp. Rewriting it to reset owed periods is
`control_drift`, invalidates focus, and requires controller repair rather than silent reactivation.

The first required period is the fixed period containing `schedule_activated_at`; periods before
activation are not owed. A bootstrap canary has `bootstrap:true`, identifies that first required
period, binds a validated receipt/exact current-main commit source, and permits focus only while
`now < deadline_at`. At `now == deadline_at` it no longer satisfies authority. It is never ordinary
period evidence.

At every focus attempt, for each schedule compute the latest required period at or after its first
period for which derived `deadline_at <= now`. If one exists, require a validated
`bootstrap:false`, `outcome:"passed"` event for that exact period, with completion
`<= deadline_at`, valid receipt/evidence ID, and exact current-main SHA captured at dispatch. If no
period has elapsed, require the valid bootstrap canary. Just-before/at/just-after deadline uses
these strict `<`/`<=` boundaries.

Missing, malformed, late, wrong-period, wrong-source, failed, or duplicate-conflicting evidence;
period/clock derivation failure; and clock regression durably invalidate focused lanes and force
full. A late completion may be retained as failed observation but never satisfies the period.
Restoration requires fresh passing evidence only for each schedule whose current required period has
expired, reuses the still-valid current-period evidence of any schedule that has not expired, and a
governed restoration event referencing the invalidation and those event IDs. Evidence for an older
or late period, or evidence bound to another lane/manifest/generation, never clears invalidation, and
a passing event alone never reenables focus.

### A.8 Storage, import, replay, and validation failure

Shadow receipt storage is:

```text
$(git rev-parse --git-path verification-selector)/receipts/sha256/<64-lowercase-hex>.json
```

The hex filename is `receipt_id` without `sha256:`. Root mode is 0700; file mode is 0600; writes
use same-directory temp file, fsync, atomic rename. Full canonical stored receipt bytes have no
trailing newline. Rows/changes follow A.5/A.6 order.

Import accepts only a file beneath that resolved Git-local root, rederives `receipt_id`, validates
schema/manifest/source/privacy, and appends a new event whose `receipt_ids` links it. Replay earns
graduation credit only when the exact committed candidate-tree digest matches the staged receipt.
Ledger writes are anchored appends: the writer captures the committed base ledger blob's SHA-256 and
its exact tip `event_id`, and the mutation is valid only if the candidate file's entire prior-event
prefix is byte-identical to that anchored base blob and its last event equals the captured tip. The
writer then appends one or more new canonical events whose first `previous_event_id` equals the
captured tip and rewrites, reorders, truncates, or re-hashes no existing event. A prefix that is not
byte-identical to the anchored base, a tip mismatch, or any in-place edit is rejected as a
`ledger_invalid` control failure, so a truncated-and-rehashed replacement can never validate.

Unknown fields, unknown enums, malformed base64/UTF-8, noncanonical ordering/bytes, identity/hash
mismatch, broken chain, invalid source variant, matcher ambiguity, unmatched path, stale schema or
manifest, privacy violation, unsupported parser kind, JSON refusal, or semantic limit failure are
never coerced. The detecting run
uses source-bound preserved full fallback when safe, records/causes `blocked` graduation, and fails
selector control. If focus was active, receipt/ledger/surveillance validation failure also emits or
persists lane invalidation and keeps effective mode full until governed restoration.

### A.9 Version handoff

V1 is closed, but the ledger is permanent history. A successor schema/version dispatches on the
literal `schema_version` of each stored object (manifest, receipt, and ledger): it must read,
validate, and preserve existing v1 receipts and v1 ledger events as immutable prior history under
the v1 rules, never rewriting, re-hashing, or discarding them. A successor may append only its own
higher-version events after the last v1 event, and the A.7 append prefix-anchor binds the unbroken
v1→successor chain. No in-place migration of accepted v1 evidence is permitted.
