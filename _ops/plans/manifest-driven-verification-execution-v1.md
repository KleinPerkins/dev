# Manifest-driven verification selector — execution plan

**Version:** v1
**Status:** ACCEPTED — 2026-09-02 (Checkpoint 0). Frozen plan of record; implementation remains
gated — Checkpoint 0 authorizes only the M0-T01 bootstrap contingent on the acceptance commit.
**Date:** 2026-09-02
**Owning repository:** `KleinPerkins/dev` (`~/dev`)
**Plan-type:** agentic-execution
**Review provenance:** Option 2 direction approved; independently reviewed and revised, then
hardened by a proportional swarm pass, against live `origin/main`
`c0a7c0fe0eae1c54e81ec114ad7db05917d28098` (worktree branch `cursor/2b907899`). D2–D5 accepted at
Checkpoint 0 on 2026-09-02; see ADR 0011 changelog for the hardening and acceptance summary.
**Governing decision:** accepted [ADR 0011](../adr/0011-manifest-driven-verification-selector.md)
**Target design:** [`manifest-driven-verification-target-design-v1.md`](manifest-driven-verification-target-design-v1.md)

**Goal:** Deliver a local manifest selector that proves exact candidate bytes, preserves the
existing gate in shadow, closes all launch safeguards, demonstrates at least 3× end-to-end speedup
for each activated common category, and only then enables reversible focused execution.
**Architecture:** Existing Python 3.11, Git plumbing, three closed JSON schemas, one rollout
ledger, a narrow local selector, and an isolated sequential runner. Remote work remains on the
existing runnerless controller through separately governed authority changes.
**Tech stack:** Python stdlib, Bash thin adapters, JSON, Git objects/indexes, stdlib `unittest`,
existing checks, and runnerless PR automation v3.

> **Freeze rule:** Checkpoint 0 explicitly decides D2–D5 and authorizes one documentation
> acceptance merge of the three whole normative artifacts (plus ordinary ADR/plan index-row
> additions). That merge commit freezes the three artifacts; the two index files stay mutable
> projections. M0-T01 subsequently creates the three schemas/ledger and mirrors the immutable
> acceptance; those later bytes are not part of Checkpoint 0. Progress never edits the accepted
> design or plan.

---

## Global Constraints

- No implementation begins before the Checkpoint-0 acceptance merge is immutable; Checkpoint 0
  authorizes that documentation merge and contingent M0 only.
- M0 corrects the already-false no-Python governance prose before selector work.
- M1 is local end-to-end shadow: predict, receipt, then authoritative current full; nothing skips.
- Remote/controller capability cannot block local M1.
- No focused skip before Checkpoint 4 and M4.
- Before each lane's Checkpoint 4: actual target full is exactly once; recursive/double proof is
  removed; universal AWA is real; that lane's invalidation and the fail-closed lane-state reducer
  are durable; that lane's weekly/monthly cadence is active with non-sliding expiry and its first
  proofs pass; D3 and D5 evidence passes for that lane. Local Checkpoint 4 requires only local
  evidence; the controller source/runtime/recipe/lock/fleet gates apply only to the PR lane.
- Every source is explicit. No command silently verifies working-tree bytes or HEAD.
- Pre-commit is offline. V1 has no result cache. No GitHub Actions workflow or paid
  hosted/self-hosted runner.
- Receipts/ledger may contain Appendix-A `path_b64`, which reversibly exposes repository-relative
  Git path bytes. They contain no source body, patch/log/environment value, secret, operator text,
  absolute/external/host/temp path, username/home path, or network ID.
- Use linked worktrees and normal hooks. Never use destructive Git, `--no-verify`, force push,
  hand-edited generated locks, combined recipe/lock phases, or `gh pr merge --auto`.
- The reviewer App alone controls native auto-merge.
- Option 3 remains deferred.
- Do not touch `chaos-scheduler`.

## 0. Authorization, atomic freeze, and checkpoints

### Checkpoint 0 — documentation acceptance merge

The operator must provide one explicit record that:

1. records `accept`, `reject`, or `replace` for D2;
2. records `accept`, `reject`, or `replace` for D3;
3. records `accept`, `reject`, or `replace` for D4;
4. records `accept`, `reject`, or `replace` for D5;
5. approves the three whole artifacts: whole ADR 0011, whole target design v1, and whole execution
   plan v1;
6. authorizes one documentation-only acceptance merge containing exactly those three artifacts plus
   the ordinary ADR-index and plan-index row additions, and records that its immutable commit SHA
   will freeze the three whole artifacts while the index files remain mutable projections;
7. records direct classification of both new plans, or equivalent isolated-staged-index
   classification, because broad doc-warden discovery ignores untracked plans;
8. names the immutable operator-record reference and intended Accepted status values;
9. authorizes that acceptance merge and, only after its exact commit is immutable, M0-T01; and
10. confirms schema/ledger bytes do not yet exist, are not Checkpoint-0 ranges, and later evidence
    never edits accepted artifacts.

No missing response defaults to acceptance. A replacement D2–D5 value must be incorporated into
all three candidate artifacts and re-digested before the operator approves the transaction.

The acceptance merge applies only preapproved documentation plus the ordinary index-row additions.
Its commit freezes the three whole artifacts; the two index files remain mutable projections in the
repository's established convention and carry no frozen-range digest. M0-T01 later creates the three
schemas and ledger and mirrors the already-immutable acceptance in genesis.

### Later checkpoints

| Checkpoint | Required evidence | Authority granted |
|---|---|---|
| **1 — M0 preflight** | Genesis mirrors immutable acceptance commit and three whole-artifact digests; Appendix-A schemas/goldens valid; policy/manual Python wording matches current reality | Authorize M1 local shadow |
| **2 — M1 local shadow** | Exact staged source, byte-safe receipts, guard order, authoritative broad proof, offline/no-cache/no-paid assertions, no residue | Authorize M2 proof |
| **3 — M2 selector proof** | D5 corpus/edges/reverse impact, real-main shadow, paired baseline inventory, exact controller/AWA preflight | Authorize M3 launch safeguards; still no skip |
| **4 — first focused launch GO (per lane)** | For the launching lane: its M3 safeguards; its active cadence and successful first proofs; valid activation proof before the first expiry or latest-required-period evidence thereafter; boundary/invalidation tests; lane graduation; exact activation/rollback generations. Local requires only local evidence; PR additionally requires the controller/recipe/lock/fleet gates | Authorize M4 for that lane's named tags; first authority to skip in that lane |
| **5 — focused stability** | First five focused changes per lane, no mismatch, durable invalidation/rollback drill | Authorize M5 steady-state hardening |

No checkpoint implies another. A changed source adapter, manifest edge, control input, AWA/runtime
binding, controller contract, or safety result invalidates dependent evidence and returns the
affected lane to shadow/full.

## 1. Scope and non-goals

### In scope

- Three schemas only: manifest, receipt, rollout ledger.
- One repository-local manifest and one rollout ledger.
- Exact staged, exact PR, and exact committed source adapters.
- Byte-safe path identities and `--no-renames` delete+add semantics.
- Narrow explicit input ownership/inert classification; forward and reverse closure.
- Sequential runner, sanitation, Git-local receipt retention/import, and cleanup.
- Local shadow before remote work.
- D5 corpus, real-main streak, paired D3 speed/budget evidence.
- Pre-launch doc-warden/AWA decomposition and actual exactly-once full parity.
- Durable local/controller invalidation and governed rollback.
- Existing runnerless recipe/image/source/cadence qualification through serial authority phases.
- Lane-specific focused activation after each lane's Checkpoint 4, then steady-state hardening of
  already-live surveillance. Parallelism is out of v1 scope.

### Non-goals

- General Bash/Python/Make static analysis.
- A fourth schema/store, cache, scheduler, learned classifier, plugin system, or fleet selector.
- Rewriting proof behavior inside the selector.
- Networked pre-commit, Actions workflow, paid runner, second controller, or Mac driver.
- Selector-owned merge/release/remote mutation.
- Any `chaos-scheduler` change.

## 2. Verified baseline and dependency gates

At the authoring base:

- current verification already invokes multiple Python helpers/suites;
- policy/manual “dependency-light/no Python” wording is stale;
- pre-commit runs session-lock → data-guard → broad repo verification;
- six doc-warden setup failures recursively invoke the broad verifier;
- AWA kernel proof may run twice through copy honesty;
- Dev recipe/lock custom-job environments are empty;
- recipe `source_ref.base_sha` is recipe provenance, not PR base;
- no checked-in Dev contract exposes immutable PR base/head values to the custom command;
- Dev uses no-network `stdlib-shell.v1` with a 300-second cap;
- Dev's historical custom qualification is `canned_only`;
- an AWA image is digest-pinned for the AWA repository profile, not qualified for Dev; and
- v3 exposes serial `recipe|lock|assignment|relock` planning/sync phases.

Consequences:

- local M1 proceeds independently;
- PR shadow/focus waits for separately proven controller argument injection;
- PR focus waits for Dev-qualified real AWA core proof under D4;
- periodic and durable runnerless invalidation wait for controller capability proof;
- a Dev recipe-only change normally plans Dev recipe then Dev lock, but controller/profile/catalog/
  assignment changes may affect more locks; the authoritative planner decides the affected set.

Before each task, re-read `AGENTS.md`, `_ops/POLICY.md`, doc-warden policy, frozen artifacts, and
current runnerless-v3 README; prove linked-worktree status, exact HEAD/upstream/origin main, staged/
unstaged paths, and previous-task evidence. Stop on unrelated changes or stale accepted digests.

## 3. Target files and interfaces

### New subsystem

| Path | Role |
|---|---|
| `_ops/verification/verification-manifest.schema.json` | Closed manifest schema |
| `_ops/verification/verification-receipt.schema.json` | Closed receipt schema |
| `_ops/verification/verification-rollout-ledger.schema.json` | Closed event-chain schema |
| `_ops/verification/verification-manifest.json` | Sole input/obligation/dependency/activation authority |
| `_ops/verification/verification-rollout-ledger.json` | Sole authority/acceptance/observation/graduation/invalidation/rollback/restoration evidence |
| `_ops/verification/contracts.py` | Appendix-A canonical JSON, identity derivation, and closed validators |
| `_ops/verification/selector.py` | Exact-source normalization, ownership, closure, fallback |
| `_ops/verification/runner.py` | Snapshot execution, receipts, receipt import, cleanup |
| `_ops/verification/test_contracts.py` | Canonical bytes/IDs/unknown fields/order/hash-chain goldens |
| `_ops/verification/test_selector.py` | Source/grammar/closure/self-protection corpus |
| `_ops/verification/test_runner.py` | Receipt/process/storage/performance/rollback corpus |
| `_ops/verification/fixtures/` | Closed cases |
| `_ops/checks/verify-changes.sh` | Thin fixed-argument adapter |

### Exact interfaces

```python
@dataclass(frozen=True)
class PathIdentity:
    path_b64: str
    path_utf8: str | None

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

def staged_source(repo: Path, index_file: Path) -> tuple[SourceBinding, tuple["Change", ...]]: ...
def pr_source(repo: Path, base_sha: str, head_sha: str) -> tuple[SourceBinding, tuple["Change", ...]]: ...
def commit_source(repo: Path, source_sha: str) -> SourceBinding: ...
def select(manifest: "Manifest", source: SourceBinding, changes: tuple["Change", ...],
           lane: str, requested_mode: str) -> "Selection": ...
def execute(selection: "Selection", manifest: "Manifest", receipt_root: Path) -> dict[str, object]: ...
def import_receipt(receipt: Path, ledger: Path) -> str: ...
```

```text
verify-changes.sh pre-commit --index-file <absolute-index> --shadow
verify-changes.sh focused-local --index-file <absolute-index>
verify-changes.sh focused-pr --base-sha <40-hex> --head-sha <40-hex>
verify-changes.sh full (--index-file <absolute-index> | --source-sha <40-hex>)
verify-changes.sh full-release --source-sha <40-hex>
verify-changes.sh deep-periodic --source-sha <40-hex>
verify-changes.sh rollout-import --receipt <git-local-receipt>
```

No source argument may default to HEAD when the working tree/index is dirty or ambiguous.

Receipt rows use scalar `focused_disposition` and `execution_disposition` values from
`run|skip|blocked|not_applicable`. Sorted `selection_causes` use only `universal`, `direct`,
`dependency`, `reverse_impact`, `fallback`, `self_protection`, `full_mode`, `deep_mode`,
`inert`, and `not_applicable`. Precedence is blocked, not-applicable, effective
full/deep/self-protection/fallback run, other selected run, then skip.
Appendix A.6 is the sole shadow exception: predicted logical rows are
not-applicable/not-observed with null exit/duration and link an identical-source authoritative full
receipt whose aggregate is run/observed with causes exactly `["full_mode"]`.

## 4. Milestone roadmap

| Milestone | Production step-forward | No-skip invariant |
|---|---|---|
| **M0 — authority and truth** | Accepted contract is digest-bound; all three schemas/ledger bootstrap exist; stale Python prose is corrected | No selector |
| **M1 — local shadow** | Exact staged selection/receipts run in pre-commit while current full stays authoritative | Every current proof runs |
| **M2 — selector/evidence proof** | Narrow grammar, corpus, edge/reverse closure, paired baseline, and remote preflight are proven | Every current proof runs |
| **M3 — launch safeguards** | Recursion/duplication removed; target full exactly once; AWA, invalidation, cadence, remote contract, D3/D5 all qualified | Every current proof runs |
| **M4 — focused activation** | Only Checkpoint-4 lane/tags may omit unrelated obligations; rollback is exercised | Ungraduated/uncertain remains full |
| **M5 — steady-state hardening** | Already-live weekly full/monthly deep controls are measured and hardened | Missing/expired-window/mismatch invalidates focus |

## 5. Work items

### Milestone 0 — authority, closed schemas, and baseline truth

#### Task M0-T01: Bootstrap all closed schemas and the rollout ledger

**Files:**
- Create the three schema files in §3.
- Create `_ops/verification/verification-rollout-ledger.json`.
- Create `_ops/verification/contracts.py`.
- Create `_ops/verification/test_contracts.py`.
- Create `_ops/verification/fixtures/wire-goldens-v1.json`.
- Create `_ops/verification/README.md`.
- Add schema/ledger presence to `_ops/checks/verify-operating-model.sh`.

**Interfaces:**
**Consumes:** Immutable documentation-acceptance merge and target-design Appendix A.
**Produces:** Three closed schemas; dependency-free canonical encoder/validators; exact
`authority_genesis` event; no selector or active gate.
**Prerequisites:** Checkpoint-0 acceptance merge is immutable and contains only the approved five
documentation files/ranges; clean descendant worktree.

- [ ] Recompute the three whole-artifact digests from the immutable acceptance commit; reject any
  mismatch with the operator record. Record no index-range digest; the index files are mutable.
- [ ] Translate Appendix A exactly into the three schemas and `contracts.py`; do not add or choose a
  field, enum, default, matcher, ordering rule, period/grace rule, identity, or coercion.
- [ ] Add exact canonical-byte and ID goldens for manifest (including `full_profile` and
  `baseline_input_rule_ids`), receipt (shadow, enforce, and enforce-fallback), every event variant,
  Unicode/non-UTF-8 paths, strict JSON Pointer classification, shadow/full receipt linkage,
  transitional empty-row full under `preserved_aggregate`, fixed weekly/monthly periods, ledger
  prefix-anchor append, logical credit keys, schema digests, candidate-tree digest, and command
  digest.
- [ ] Add failing cases for duplicate/unknown fields, unknown enums, float/out-of-range integer,
  BOM/invalid UTF-8/unpaired surrogate, noncanonical array/key order, non-conforming string escapes,
  malformed base64/path, empty/duplicate/unsorted/unknown `baseline_input_rule_ids`, identity
  mismatch, genesis predecessor, broken/forked chain, ledger prefix-anchor/tip mismatch or truncated
  rehash, duplicate logical credit key, non-consumer-bound surveillance reference, an empty-row
  receipt under a `decomposed` profile, an enforce-fallback receipt lacking a fallback cause,
  provenance-grammar and other privacy violations, and omitted provenance/source/schema links.
- [ ] Implement manifest, receipt, and rollout-ledger schemas with
  `additionalProperties:false` at every object.
- [ ] Permit only `authority_genesis`, `acceptance`, `observation`, `graduation`, `invalidation`,
  `rollback`, and `restoration` event variants and exact `previous_event_id` continuity.
- [ ] Bootstrap genesis with acceptance commit, three artifact digests, three schema digests,
  explicit D2–D5 decisions, classifications, and operator reference.
- [ ] Prove unknown/malformed/noncanonical bytes are rejected, never defaulted or silently sorted.
- [ ] Add inert presence/JSON/schema checks only. Do not wire a selector.

**Verification:**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m json.tool \
  _ops/verification/verification-rollout-ledger.json >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v _ops.verification.test_contracts
_ops/bin/doc-warden.sh check .
git diff --check
```

**Acceptance:** `AC-001`–`AC-004`.
**Delivery/rollback:** One contracts/evidence Draft PR. Revert as a unit before M1 if invalid.
**Done:** Appendix A is implemented byte-for-byte and genesis mirrors—not creates—the immutable
documentation authority before selector code.

#### Task M0-T02: Correct existing Python governance drift

**Files:**
- Modify `_ops/POLICY.md` verification dependency wording only.
- Modify `OPERATING-MANUAL.md` matching wording only.
- Append acceptance evidence to the rollout ledger.

**Consumes:** Current verification call inventory.
**Produces:** Factual statement that verification already uses Python while remaining local,
dependency-bounded, offline where required, and runnerless.
**Prerequisites:** M0-T01 merged; no selector code.

- [ ] Record exact existing Python entrypoints in doc-warden, worktree/AWA, context measurement, and
  runnerless-v3 verification.
- [ ] Replace only false no-Python/dependency-light claims; do not claim selector behavior.
- [ ] Add a regression that rejects reintroduction of the false statement.
- [ ] Confirm no check/hook/recipe/config/runtime behavior changed.

**Verification:**

```bash
rg -n 'python3|unittest' _ops/checks _ops/context-measurement
_ops/bin/doc-warden.sh check .
git diff --check
```

**Acceptance:** `AC-005`–`AC-006`.
**Delivery/rollback:** One documentation-only Draft PR before M1.
**Done:** Governance matches current reality before selector implementation.

### Milestone 1 — minimum local end-to-end shadow

#### Task M1-T01: Implement exact staged source and narrow manifest selection

**Files:** Create manifest, selector, selector tests, and staged/classifier/ownership fixtures.
**Consumes:** Target design §§5–9 and normative Appendix A; current tracked-path/proof inventory.
**Produces:** Byte-safe staged `SourceBinding`, candidate-tree SHA-256, manifest loader, ownership,
reverse/forward closure, full fallback, deterministic selection.
**Prerequisites:** Checkpoint 1; M0 merged.

- [ ] Write staged cases for partial staging, unstaged/untracked decoys, add/modify/delete/type,
  mode, non-UTF-8, binary, unborn HEAD, unmerged index, intent-to-add, and index drift.
- [ ] Implement raw NUL-safe plumbing with sanitized Git config/environment, no textconv/external
  diff, and `--no-renames`.
- [ ] Compute path-byte base64 identity and candidate-tree SHA-256 over canonical
  `{path_b64,mode,blob_sha256}` rows exactly as Appendix A.5; exclude the optional `path_utf8`
  display field from every content identity. Base64 remains reversible, not sanitized.
- [ ] Build candidate objects only in an owned temporary object directory with repository objects
  read-only; prove repository object-store bytes do not change.
- [ ] Make `InputRule.owner_obligation_ids` the sole direct ownership authority; remove reciprocal
  obligation ownership and tag-trigger selection. Classification tags are rollout/reporting only.
  Declare every tracked path through exact/prefix/suffix byte matchers as one/many owners or inert
  and reject unmatched/owner-inert overlap.
- [ ] Implement the §7 focus-eligibility predicate as pure logic: derive the change-tag set (union
  of matching InputRule `classification_tags` plus an `inert` token for inert-only changes) and
  return focus-eligible only when it is non-empty and wholly graduated for the lane; empty,
  ambiguous, control, or unmatched forces full. It stays inert in M1 (shadow, no graduated tags).
- [ ] Implement only Appendix-A `json_pointer_changes_v1`: strict UTF-8/no BOM, duplicate-key and
  invalid-number rejection, RFC 6901 escaping, object/scalar/array change and ancestor rules,
  exact/descendant-prefix matching, and frozen 1 MiB/64-depth/100k-node/10k-pointer/
  128-character-number-token limits. Semantic rules may add obligations only.
- [ ] Validate `baseline_input_rule_ids` as a nonempty, duplicate-free, canonical InputRule-ID set;
  run the semantic selector when any referenced rule matches and preserve the union of every
  matching rule's baseline owners before additive pointer obligations.
- [ ] Implement delete/shared reverse impacted closure, then forward prerequisite closure.
- [ ] Reuse M0 canonical validators and reject unknown fields/enums/references/cycles, noncanonical
  order/IDs, unsafe argv/path rules, identity mismatch, and stale command inputs.
- [ ] Prove Markdown/Python/shell remain file-level, and unsupported parser/refusal/limit or an
  unknown relationship never claims narrow completeness: detected failure forces full and blocks
  graduation; undeclared semantics stay covered by shadow/goldens.
- [ ] Keep activation shadow with no graduated tags.

**Verification:**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  _ops.verification.test_contracts _ops.verification.test_selector
git diff --check
```

**Acceptance:** `AC-007`–`AC-013`.
**Delivery/rollback:** One inert selector Draft PR; Bugbot and security review.
**Done:** Pure selection is exact, deterministic, byte-safe, conservative, and cannot skip.

#### Task M1-T02: Implement sequential execution, receipts, Git-local storage, and import

**Files:** Consume the unchanged M0-translated receipt schema; create runner/runner tests/process
fixtures; update README and ledger only. M1-T02 must not edit or redesign the receipt schema.
**Consumes:** M1-T01 selection/manifest and Appendix A.6–A.8.
**Produces:** Sequential exact-snapshot runner; closed receipt rows; content-addressed Git-local
storage; closed ledger import; cleanup proof.
**Prerequisites:** M1-T01 merged.

- [ ] Test `focused_disposition`, scalar `execution_disposition`, lexicographically sorted
  `selection_causes`, outcome constraints, precedence, and multi-cause deduplication exactly as
  Appendix A.6.
- [ ] Pin the sole M1 shadow tuple: each logical row has
  `execution_disposition:not_applicable`, `outcome:not_observed`, null exit/duration, predicted
  focused disposition/causes, and never passed.
- [ ] Write/validate the authoritative full receipt first, then link it by
  `authoritative_receipt_id`; require canonically identical `SourceBinding` and byte-equal
  aggregate full row with `selection_causes:["full_mode"]`. Permit `rows:[]` only when the bound
  manifest generation's `activation.full_profile` is `preserved_aggregate` and the executor is
  `preserved.full`; reject it under a `decomposed` generation and for graduation.
- [ ] Materialize mode-0700 candidate snapshots and run fixed argv/cwd in one process group with
  allowlisted environment, bounded output/resources, and `PYTHONDONTWRITEBYTECODE=1`.
- [ ] Test child/grandchild timeout, INT/TERM/HUP, TERM→KILL→wait/reap, and all owned-path cleanup.
- [ ] Seed source/path/secret/operator/environment/temp/network sentinels through every failure
  channel; prove no receipt/ledger leak.
- [ ] Derive the sole `receipt_id` by canonical bytes excluding only `receipt_id`; prove exact
  golden bytes/ID and absence of any separate receipt digest field.
- [ ] Write mode-0600 receipts under the exact Git-local Appendix-A path with hex digest filename,
  canonical bytes without trailing newline, and atomic rename.
- [ ] Implement bounded retention and `rollout-import`; rederive identity and reject outside-root,
  invalid, altered, noncanonical, privacy-violating, or unsanitized receipts.
- [ ] Implement anchored ledger append (A.7/A.8): capture the base ledger blob digest and tip,
  require the candidate's prior-event prefix to be byte-identical to that anchor, append canonical
  events only, and reject any truncated/rehashed/edited prefix as `ledger_invalid`.
- [ ] Enforce logical credit keys: compute each event's type-specific credit key, credit each key at
  most once, and reject a second conflicting passing credit as `ledger_invalid` (a retry reuses the
  key with a distinct `event_id`).
- [ ] Add a non-schema explanation renderer mapping every closed `diagnostic_code`/invalidation
  reason to one plain cause/consequence/next-action line, identical from the pre-commit path and an
  explicit `verify-changes explain` CLI; it reads only existing codes and never greens a red/full run.
- [ ] Carry candidate-tree digest into receipt and imported observation. Permit real-main replay
  credit only when the committed tree digest matches.
- [ ] Assert no cache file/API/key and no surviving process/index/object/temp/pycache.

**Verification:**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  _ops.verification.test_contracts _ops.verification.test_selector \
  _ops.verification.test_runner
git status --short
```

**Acceptance:** `AC-014`–`AC-016`.
**Delivery/rollback:** One runner Draft PR; Bugbot and security review.
**Done:** Receipts are honest, content-addressed, sanitized, importable, and residue-free.

#### Task M1-T03: Wire local pre-commit shadow without a remote dependency

**Files:** Create shim; modify pre-commit, exact-index data-guard, Makefile, operating-model check,
tests, README, ledger.
**Consumes:** M1-T01/T02; current guard chain and broad command.
**Produces:** Real local shadow receipt followed by source-bound preserved broad proof.
**Prerequisites:** M1-T02 merged. No controller prerequisite.

- [ ] Preserve session-lock first. Capture one private staged source and pass the same candidate to
  exact-index data-guard, selector, runner, and repo-content proof.
- [ ] Preserve data-guard no-argument compatibility, but exact mode must never fall back to
  working-tree bytes.
- [ ] Load shim/manifest/selector/runner/executors from the materialized candidate; unstaged
  control divergence blocks.
- [ ] Emit prediction rows, run existing broad `--ci`, persist its validated full receipt, then
  persist the linked shadow receipt. Missing/mismatched linkage fails shadow evidence; broad full
  remains the only authoritative outcome and no per-obligation pass is inferred.
- [ ] Add explicit-source focused/full/deep commands. Focused local accepts an explicit staged
  index only; local full accepts explicit index or commit; deep/release accepts commit only;
  ambiguous bare dirty defaults refuse.
- [ ] Prove success/failure/ambiguity/interruption leaves no object/index/process/temp/bytecode.
- [ ] Prove pre-commit needs no network, uses no result cache, adds no Actions workflow/runner, and
  cannot skip.
- [ ] Keep all remote files unchanged.

**Verification:**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  _ops.verification.test_contracts _ops.verification.test_selector \
  _ops.verification.test_runner
bash _ops/checks/verify-changes.sh pre-commit \
  --index-file "$FIXTURE_INDEX" --shadow
make verify-ci
git diff --check
```

Use a disposable fixture index; never assume the shell exports the live index.

**Acceptance:** `AC-017`–`AC-020`.
**Delivery/rollback:** One local-shadow Draft PR. Restore prior hook atomically on rollback.
**Done:** Local M1 is end to end, authoritative full remains, and no remote gap blocks it.

### Milestone 2 — closed selector and evidence proof

#### Task M2-T01: Complete narrow completeness, corpus, and edge challenges

**Files:** Expand tests/fixtures; add a narrow inventory checker; update manifest/ledger.
**Consumes:** Live M1 graph and proposed D5 distribution.
**Produces:** ≥100-case corpus, every-edge mutations, tracked-path coverage, reverse impacted proof.
**Prerequisites:** Checkpoint 2; local shadow active.

- [ ] Meet 20 staged, 20 exact-PR model, 20 classifier/fallback, 20 dependency/reverse-impact,
  10 self-protection, and 10 receipt/isolation/cleanup floors.
- [ ] Generate delete/redirect/reverse/cycle mutations for every declared edge; expand beyond 20.
- [ ] Prove deletes and shared inputs select all reverse consumers then prerequisites.
- [ ] Challenge strict JSON Pointer root/escape/add/delete/scalar/type/array/ancestor/exact/
  descendant-prefix cases and every frozen limit; prove semantic selection only adds obligations.
- [ ] Validate only declared literal Bash/Python/Make/JSON argv/config references; unsupported
  dynamic dispatch in a registered harness is a control failure, not an analyzer feature.
- [ ] Add unknown tracked path, inert misclassification, orphan command, phantom command, moved
  entrypoint, missing control input, stale inventory, candidate-control deletion/narrowing, and
  incompatible-base cases.
- [ ] Keep actual gate full.

**Verification:**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  _ops.verification.test_contracts _ops.verification.test_selector \
  _ops.verification.test_runner
PYTHONDONTWRITEBYTECODE=1 python3 _ops/verification/selector.py verify-inventory --repo .
```

**Acceptance:** `AC-021`–`AC-026`.
**Delivery/rollback:** One proof-only Draft PR.
**Done:** Automated proof detects declared omissions/drift without claiming unknown-edge discovery.

#### Task M2-T02: Capture real-main shadow and paired baseline evidence

**Files:** Update runner tests, README, and rollout ledger only.
**Consumes:** M2-T01; exact merged-main candidates.
**Produces:** Real-main streak; per-lane/category paired current/full/focused observations; replay
evidence with candidate-tree digests.
**Prerequisites:** M2-T01 merged; at least 10 real main changes and 20 valid pairs per proposed
category become available.

- [ ] For each observation, require identical candidate-tree, manifest, lane, machine/runner class,
  and resource limits across preserved-current, target-full model, and focused prediction.
- [ ] Alternate execution order; record monotonic end-to-end milliseconds.
- [ ] Compute the human ratio `min(current_ms,full_ms)/focused_ms` and persist Appendix-A integer
  `ratio_millionths=floor(min(current_ms,full_ms)*1000000/focused_ms)`; retain every pair.
- [ ] Accumulate 10 consecutive real-main changes with zero missed obligation and zero
  focused-pass/full-fail mismatch; a miss adds fixture, reruns corpus, resets streak.
- [ ] Collect 20 pairs/category/lane proposed for launch and baseline 19/20 budget evidence, but do
  not claim graduation before M3 actual full.
- [ ] Import only sanitized content-addressed receipts. Require candidate-tree digest equality for
  replay/streak credit.

**Verification:**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 _ops/verification/runner.py \
  validate-ledger _ops/verification/verification-rollout-ledger.json
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  _ops.verification.test_contracts _ops.verification.test_selector \
  _ops.verification.test_runner
```

**Acceptance:** `AC-027`–`AC-031`.
**Delivery/rollback:** Evidence-only Draft PR; failures extend shadow.
**Done:** Same-byte baseline and safety evidence exists, but no category is activated.

#### Task M2-T03: Record runnerless controller and AWA capability preflight

**Files:** Append one acceptance event to rollout ledger; no controller/recipe/lock mutation.
**Consumes:** Current recipe, lock, verification manifest, v3 controller/profile/coverage/
qualification authorities.
**Produces:** Exact capability matrix and external dependency list.
**Prerequisites:** May run in parallel with M2-T01/T02 after M1.

- [ ] Record recipe and lock custom-job environment as empty.
- [ ] Distinguish recipe provenance base from PR base/head.
- [ ] Record which exact controller source, periodic, and durable invalidation interfaces are
  present/absent; do not infer from exact-head Check approval.
- [ ] Record Dev's current stdlib profile/canned-only disposition and AWA image/profile assignment.
- [ ] Run v3 `plan/view/verify-control-plane` read-only; capture exact release/profile/catalog/
  assignment/lock digests.
- [ ] List separately governed controller capability, Dev AWA image, recipe qualification, and
  lock/rebind gates. No remote mutation.

**Verification:**

```bash
_ops/bin/repo-baseline.sh profile pr-automation v3 view --repo KleinPerkins/dev
_ops/bin/repo-baseline.sh profile pr-automation v3 verify-control-plane
git diff --check
```

**Acceptance:** `AC-032`.
**Delivery/rollback:** Evidence-only Draft PR.
**Done:** M3 starts from proven capabilities and gaps, not assumptions.

### Milestone 3 — decomposition, actual full parity, and launch controls

#### Task M3-T01: Extract doc-warden proof and recursive failure cases

**Files:** Split doc-warden check into independently invocable proof groups; update manifest/tests/
ledger; retain compatibility wrapper.
**Consumes:** Exact pre-change full/sandbox proof and exit inventories.
**Produces:** Named groups; six direct setup-failure invocations; compatibility parity.
**Prerequisites:** Checkpoint 3; full shadow active.

- [ ] Capture pre-change assertion/exit/output inventory.
- [ ] Extract by proof intent without changing assertions.
- [ ] Replace six recursive broad calls with direct isolated setup obligation calls.
- [ ] Prove full/sandbox union parity, no recursive full process, and cleanup.
- [ ] Advance the manifest to a `decomposed` `full_profile` generation as the immutable cutover:
  from it, full/deep require one observed row per applicable obligation and empty-row receipts are
  rejected regardless of lane policy.
- [ ] Force full for the graph/harness change and rerun all affected edge mutations.

**Acceptance:** `AC-033`–`AC-034`.
**Delivery/rollback:** One doc-warden Draft PR; rollback restores wrapper and remains full.
**Done:** Recursive work is removed with exact proof parity.

#### Task M3-T02: Deduplicate AWA/kernel and qualify universal local proof

**Files:** Modify Dev-owned worktree/kernel/copy-honesty adapters, manifest/tests/ledger. Do not
modify AWA product authority.
**Consumes:** Current duplicate call graph and real local AWA runtime.
**Produces:** One kernel executor; copy-honesty result consumption; named simulations.
**Prerequisites:** M3-T01 merged; D4 accepted.

- [ ] Add failing execution-count proof for current duplicate.
- [ ] Make `awa.kernel-core` sole executor and pass its closed digest/result to copy honesty.
- [ ] Split simulations only where commands and cleanup boundaries already exist.
- [ ] Treat missing runtime as blocked, not skip/pass.
- [ ] Prove real engine-off/core and simulation parity, exact once, no residue.

**Acceptance:** `AC-035`–`AC-037`.
**Delivery/rollback:** One AWA-host Draft PR; security review.
**Done:** Local universal AWA is real and duplicate kernel work is gone.

#### Task M3-T03: Make target full/deep actually exactly once

**Files:** Modify broad adapter/Makefile/manifest/runner/tests/ledger.
**Consumes:** Decomposed proof groups and preserved current source-bound command.
**Produces:** Manifest-driven full/deep execution; runtime count recorder; parity evidence.
**Prerequisites:** M3-T01/T02 merged.

- [ ] Dispatch every applicable parent/named obligation through runner once.
- [ ] Compare preserved-current and target-full proof IDs, assertion inventory, exit reduction, and
  candidate-tree digest over structured success/failure fixtures.
- [ ] Prove deep is full once plus deep-only once.
- [ ] Reject duplicate count, omitted assertion, unavailable universal, or ambiguous source.
- [ ] Keep focused lanes shadow.

**Verification:**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  _ops.verification.test_contracts _ops.verification.test_selector \
  _ops.verification.test_runner
bash _ops/checks/verify-changes.sh full --source-sha "$EXACT_SHA"
bash _ops/checks/verify-changes.sh deep-periodic --source-sha "$EXACT_SHA"
```

**Acceptance:** `AC-038`–`AC-039`.
**Delivery/rollback:** One full-runner Draft PR; restore preserved wrapper on parity failure.
**Done:** Exactly-once is runtime evidence, not only a model assertion.

#### Task M3-T04: Implement durable lane invalidation and rollback

**Files:** Modify manifest/selector/runner/tests/README/ledger; add only repository-owned adapters.
**Consumes:** Activation generation, controller capability matrix, and Appendix A.7 fixed-period/
invalidation/restoration contract.
**Produces:** Fail-closed Git-local lane state; qualified controller invalidation contract;
invalidation/rollback/restoration ledger events; reviewed manifest rollback generation.
**Prerequisites:** M3-T03; separately proven controller capability before remote portion.

- [ ] Persist local lane state atomically under Git-local state; implement the fail-closed
  lane-state reducer so focus requires manifest, ledger, and persisted state to agree on one enforce
  generation with valid consumer-bound evidence; any absence/staleness/disagreement forces
  shadow/full; write enabled state last and persist disablement before returning failure.
- [ ] Any mismatch/invalid receipt/cleanup failure writes a closed local invalidation before
  returning failure.
- [ ] Derive the latest expired fixed weekly/monthly period at focus time with non-sliding expiry
  (`period_end + grace`, completion never extends). Require consumer-bound passing evidence matching
  lane/manifest/schema/generation/source; treat missing, late, malformed, wrong-period/source,
  duplicate-conflicting, cross-bound, or unverifiable evidence and clock failure/regression as
  closed invalidation reasons that force full.
- [ ] Require controller-owned persisted invalidation for PR; absent support blocks PR activation.
- [ ] Import invalidation into ledger and prepare a later manifest generation returning only the
  affected lane to shadow.
- [ ] Require restoration to reference the invalidation, fresh in-window passing evidence for each
  expired schedule (reusing the still-valid evidence of any unexpired schedule), current graduation,
  and a governed activation generation; old/late/cross-bound or merely new evidence never reenables.
- [ ] Drill local and remote detection, immediate lane refusal, ledger import, and durable reviewed
  rollback. Make no cross-machine instant-disable claim.

**Acceptance:** `AC-040`–`AC-042`.
**Delivery/rollback:** Local control PR and separately governed controller dependency; never bundle.
**Done:** Detecting runs fail immediately and each lane has durable disable + reviewed rollback.

#### Task M3-T05: Satisfy controller-owned source, cadence, and invalidation dependencies

**Files in this repo:** Rollout-ledger evidence only.
**External authority:** `KleinPerkins/pr-automation-controller`; exact files require a separately
accepted controller-owned design/plan after inspecting that repository.
**Consumes:** M2-T03 absent/present matrix.
**Produces:** Qualified release contract for immutable PR base/head arguments; qualified recurring
dispatch/deadline interfaces for weekly `full-release` and monthly `deep-periodic`; persisted
per-lane invalidation. Actual Dev schedule activation waits for M3-T07/T08 recipe/lock completion.
**Prerequisites:** Separate operator acceptance for external plan; no authorization is inherited
from this plan.

- [ ] If all interfaces already exist, prove exact API/release digests. Otherwise stop and author
  the controller-owned successor plan.
- [ ] Require base/head values as controller-constructed literal argv or closed environment values;
  execution VM never fetches/resolves them.
- [ ] Require exact current-main SHA capture before each weekly/monthly dispatch.
- [ ] Qualify ISO-week/Monday-end/24-hour-grace and calendar-month/next-month-end/48-hour-grace
  registration, dispatch, exact period/deadline persistence, and missed-run detection using only
  the existing runnerless controller host.
- [ ] Qualify the PR full/deep cadence envelope: because full/deep exceed the 300-second job cap,
  qualify either a longer controller job or exact-source shards whose partial results are atomically
  aggregated, fail-closed, and cover every applicable obligation exactly once — never a paid runner.
  PR focus stays shadow until the envelope is proven.
- [ ] Require persistent remote invalidation that fails closed on stale/missing state.
- [ ] Preserve one controller host, no Actions, no Mac driver, credential-free/no-network execution.
- [ ] Merge/deploy only through controller governance, then record qualified release/digest.

**Acceptance:** `AC-043`–`AC-045`.
**Delivery/rollback:** Entirely separate controller PR/release. This repo records evidence only.
**Done:** Remote source/schedule/invalidation interfaces are qualified authority, ready for actual
M3 activation after the Dev recipe and lock are current.

#### Task M3-T06: Qualify a Dev runtime for universal AWA core proof

**Files:** Qualification evidence/profile/assignment files selected by current v3 planner; rollout
ledger. No hand edits to generated lock.
**Consumes:** Qualified controller release and current AWA image/profile authority.
**Produces:** Dev-applicable digest-pinned runtime that executes real AWA core within lane limits.
**Prerequisites:** M3-T05; D4 accepted; current planner output.

- [ ] Do not reuse the AWA repository assignment by assumption.
- [ ] Qualify the exact Dev command/runtime/image under no-network/non-root/no-host-mount limits.
- [ ] Prove universal AWA core, output/resource/time bounds, and failure behavior.
- [ ] Stage any profile/assignment change through its own owner-GO phase.
- [ ] Record image/profile/assignment/release digests and rollback.

**Acceptance:** `AC-046`.
**Delivery/rollback:** One qualification/assignment Draft PR; separate from recipe and lock.
**Done:** Dev PR can execute real universal AWA proof; otherwise PR focus remains prohibited.

#### Task M3-T07: Qualify the Dev remote recipe

**Files:** Qualification ledger/evidence as governed; `.github/pr-recipe.json` through recipe phase;
rollout ledger. No lock change.
**Consumes:** M3-T03 full command, M3-T05 exact argv, M3-T06 runtime.
**Produces:** Qualified no-network Dev recipe for shadow/full plus weekly/monthly entrypoints.
**Prerequisites:** Exact controller/image contracts merged; qualified compiler/release available;
fresh recipe-phase owner GO.

- [ ] Qualify custom argv and exact base/head injection under the real 300-second/profile limits.
- [ ] Keep all jobs credential-free/no-network; a category whose full/deep cannot fit the qualified
  cadence envelope (a longer job or atomically aggregated exact-source shards) stays shadow, never a
  paid runner.
- [ ] Add PR shadow/full and controller-triggered `full-release`/`deep-periodic` commands.
- [ ] Stage only recipe through v3 plan/sync. Leave Draft/unarmed.
- [ ] After merge, prove exact protected recipe provenance and runtime canary.

**Acceptance:** `AC-047`–`AC-049`.
**Delivery/rollback:** One Dev recipe Draft PR. Revert recipe before lock if qualification fails.
**Done:** Exact remote commands are qualified and merged; lock remains intentionally stale next.

#### Task M3-T08: Recompile lock, rebind, and contain fleet blast radius

**Files:** Generated Dev lock and only planner-identified assignment/relock files; rollout ledger.
**Consumes:** Merged recipe; exact qualified compiler/release; current control-plane planner.
**Produces:** Current lock/rebind and explicit affected-repository set.
**Prerequisites:** M3-T07 merged on default branch; fresh lock/relock owner GO.

- [ ] Run v3 plan for Dev and every lock-governed enrolled repository after any controller/profile/
  catalog/assignment semantic change.
- [ ] If only Dev recipe bytes changed, apply only the Dev lock phase the planner reports.
- [ ] If covered semantics/epoch/assignment changes report other stale locks, create separate
  per-repository relock bodies; do not bundle or assume fleet-wide scope.
- [ ] Never hand-edit lock or combine recipe/lock/assignment/relock.
- [ ] Require mixed-generation backward compatibility while locks are being repaired: keep new
  semantics dormant until every planner-identified lock is current, predeclare a rollback, and
  centrally abort/roll back on any stalled relock or fleet-parity failure.
- [ ] Run local control-plane and read-only remote fleet parity with exact compiler.
- [ ] Record affected set, operation IDs, digests, and rollback refs.

**Acceptance:** `AC-050`.
**Delivery/rollback:** Serial generated-lock/relock Draft PRs; all unarmed.
**Done:** Every planner-reported affected lock is current; no unrelated repository is changed.

#### Task M3-T09: Prove cadence, speed, graduation, and launch readiness

**Files in this repo:** Tests/README/rollout ledger; no focused activation change.
**External operation:** Activate Dev schedules through the separately qualified M3-T05 controller
interface only after M3-T08; do not change controller source here.
**Consumes:** M2 observations plus actual target full, qualified local/remote lanes, invalidation,
and Appendix A.7 surveillance event/period rules.
**Produces:** Per-lane/tag graduation event and Checkpoint-4 evidence packet.
**Prerequisites:** Local lane: M3-T01–T04 complete with recorded local full/deep cadence proofs.
PR lane additionally: M3-T05–T08 complete.

- [ ] Record the local lane's weekly `full-release` and monthly `deep-periodic` as source-bound
  local runs on the current main SHA; local surveillance is expiry-gated and needs no controller or
  scheduler, and a stale/missing local proof safely forces full until refreshed.
- [ ] For the PR lane, register and activate both recurring controller schedules after the exact
  recipe/lock is current; prove they are installed, enabled, and dispatch through the existing
  runnerless controller only.
- [ ] Run one exact weekly `full-release` canary on current main.
- [ ] Run one exact monthly `deep-periodic` canary including mutation/live-environment checks and
  selector/full replay over 20 recent exact changes, or all if fewer.
- [ ] Persist canaries as `bootstrap:true` evidence for each first required fixed period; prove they
  authorize only while `now < deadline_at` and never satisfy elapsed-period evidence.
- [ ] Append passing period events with exact period ID, period end, grace, deadline, completion,
  source SHA, receipt/evidence ID, schema, manifest, and provenance links.
- [ ] Test just-before/at/after grace, period rollover, missed period, late completion, wrong
  period/source, cross-bound evidence, and clock regression. Prove invalid cases durably invalidate
  focused lanes and run full via the fail-closed lane-state reducer, then prove governed restoration
  needs fresh in-window evidence only for the expired schedule (reusing any unexpired schedule's
  valid evidence).
- [ ] Prove exact releases and verification-control changes force full.
- [ ] Recompute 20 paired same-byte observations/category/lane using actual target full.
- [ ] Require median `min(current,full)/focused >= 3.0` for every proposed category/lane.
- [ ] Require 19/20 focused runs within 3/5/12-minute budgets and all within tighter lane cap.
- [ ] Report 5× target met/missed and 10–20× tiny-change aspiration without gating on either.
- [ ] Revalidate ≥100 corpus, every edge, 10 real-main streak, no misses/mismatches, sanitation,
  cleanup, offline/no-cache/no-paid, AWA, full exactly once, active schedules, fixed-period
  invalidation/restoration, and cadence.
- [ ] Append a per-lane immutable graduation event naming exact lane/tags and every evidence digest,
  each referenced surveillance/drill event consumer-bound
  (lane/manifest/schema/generation/source); the local event binds only local evidence.
- [ ] Present exact activation generation and prepared rollback generation at that lane's Checkpoint 4.

**Acceptance:** `AC-051`–`AC-056`.
**Delivery/rollback:** Separately governed controller schedule activation, then evidence-only Dev
Draft PR; failed category/lane stays shadow and schedule rollback does not enable focus.
**Done:** Each lane's Checkpoint 4 can decide only while that lane's schedules each have a valid
pre-first-expiry activation proof or consumer-bound latest-required-period evidence; the local lane
may reach this from M3-T01–T04 and local cadence without the PR-lane controller work.

### Milestone 4 — first focused activation

#### Task M4-T01: Activate only approved local tags

**Files:** Manifest activation, local lane state, tests, ledger.
**Consumes:** Checkpoint-4 local lane/tag list and graduation-event digest.
**Produces:** One local enforce generation; next-generation shadow rollback.
**Prerequisites:** Explicit local Checkpoint 4 (independent of PR-lane controller work); unchanged
evidence-bound bytes.

- [ ] Revalidate all evidence digests; any drift returns to M3.
- [ ] Before activation and every focused invocation, validate the local lane via the fail-closed
  reducer and both non-sliding local surveillance windows (consumer-bound; pre-first-expiry
  activation proof allowed); missing/late/invalid/expired/cross-bound evidence invalidates the lane
  and runs full.
- [ ] Activate exact named tags only; everything else full.
- [ ] Initialize fail-closed Git-local lane state.
- [ ] Drill mismatch→failed run→local invalidation→shadow/full→ledger event→reviewed rollback.

**Acceptance:** `AC-057`–`AC-059`.
**Delivery/rollback:** One local activation Draft PR. Rollback is the predeclared next generation.
**Done:** Only approved local changes skip and durable rollback works.

#### Task M4-T02: Activate only approved runnerless PR tags

**Files:** Manifest, recipe through recipe phase, generated lock through later lock phase, tests,
ledger.
**Consumes:** Checkpoint-4 PR lane/tag list; controller/image/recipe/lock evidence.
**Produces:** One PR enforce generation with controller invalidation.
**Prerequisites:** M4-T01 independent; explicit PR approval; exact authority unchanged.

- [ ] Activate only independently PR-qualified tags; local evidence never transfers.
- [ ] Revalidate both active schedules, fixed-period/canary event chains, and exact grace boundaries
  at activation and every focused invocation; failure durably invalidates PR focus to full.
- [ ] Apply recipe and lock as separate serial phases.
- [ ] Prove unknown/mixed/control/AWA/ungraduated inputs remain full.
- [ ] Drill controller invalidation and reviewed recipe/lock/manifest rollback.

**Acceptance:** `AC-060`–`AC-061`.
**Delivery/rollback:** Separate activation recipe and lock Draft PRs.
**Done:** PR focus is independently evidence-bound and reversible.

#### Task M4-T03: Observe first focused changes and pass Checkpoint 5

**Files:** Rollout ledger only unless a defect requires a normal code fix.
**Consumes:** First five focused merged changes per enforcing lane.
**Produces:** Focused stability evidence or invalidation.
**Prerequisites:** At least one M4 lane active.

- [ ] Compare focused/full on each of the first five exact sources.
- [ ] Require zero missed obligation/safety mismatch, valid receipt, and clean process/storage.
- [ ] On any defect, fail, invalidate only affected lane, add fixture, rerun corpus, reset streak,
  and require fresh graduation.

**Acceptance:** `AC-062`.
**Delivery/rollback:** Evidence-only PR when green; invalidation/rollback first when red.
**Done:** Checkpoint 5 explicitly authorizes or denies M5 steady-state hardening.

### Milestone 5 — steady-state deep/drift hardening

#### Task M5-T01: Measure and harden already-live surveillance

**Files:** Runner/tests/README/ledger; controller/recipe/lock only through separately authorized
serial phases if hardening requires them.
**Consumes:** D2/D5 cadence and active M3 schedules/fixed-period contracts.
**Produces:** Continued surveillance measurements, period-boundary hardening, and bounded retention; no
first schedule activation.
**Prerequisites:** Checkpoint 5.

- [ ] Measure subsequent weekly `full-release` runs on exact current main and detect missing/late/
  wrong ISO-week evidence at exact grace boundaries.
- [ ] Measure subsequent monthly `deep-periodic` runs with mutation/live-environment checks and
  20-change selector/full replay, or all if fewer; test month/year/leap boundaries and late runs.
- [ ] Force a mismatch/invalid receipt/cleanup leak and prove detecting operation fails and
  invalidates the affected lane.
- [ ] Reprove exact release/control-change full, AWA universal, full/deep exactly once, sanitation,
  retention, and process cleanup.
- [ ] Reprove no Actions workflow, paid runner, second controller, Mac driver, cache, Option 3, or
  `chaos-scheduler` change.

**Acceptance:** `AC-063`–`AC-068`.
**Delivery/rollback:** Evidence/hardening Draft PRs; controller and recipe/lock changes stay
separate. Roll back to shadow/full, never disable full.
**Done:** Surveillance that was already live before M4 remains exact, current, observable, and
fail-safe.

## 6. Acceptance ledger

Every criterion is credited through a closed `acceptance` proof bundle keyed by its task or
checkpoint, carrying a sorted per-criterion `{ac_id,status,evidence_ids}` mapping with exact source,
manifest, schema, receipt/event, command/check, and controller/image digests where applicable. Each
`ac_id` is one logical credit key credited exactly once, so a single bundle may satisfy several rows
without double-counting.

| ID | Acceptance condition | Milestone |
|---|---|---|
| `AC-001` | Immutable documentation-acceptance commit contains and freezes exactly three whole artifacts; index files stay mutable projections | M0 |
| `AC-002` | D2, D3, D4, and D5 each have explicit disposition/replacement | M0 |
| `AC-003` | Genesis mirrors acceptance commit, three artifact digests, schema digests, decisions, and classifications, and records no index-range digest | M0 |
| `AC-004` | Three Appendix-A schemas only; canonical IDs/arrays including baseline rule IDs, `full_profile`, enforce-fallback receipt, ledger prefix-anchor, logical credit keys, escape/provenance grammar, parser/shadow/fixed-period goldens, rejection, and chain continuity pass | M0 |
| `AC-005` | Existing Python invocation inventory is exact and reproducible | M0 |
| `AC-006` | Policy/manual match current Python reality before selector work, with no behavior change | M0 |
| `AC-007` | Staged source binds Git tree plus candidate-tree SHA-256 and ignores decoys | M1 |
| `AC-008` | Path identity is reversible padded base64 of relative Git bytes and excludes the optional UTF-8 display from every content identity; forbidden absolute/external/private paths fail | M1 |
| `AC-009` | `--no-renames` treats movement delete+add and copies add, selecting owner union | M1 |
| `AC-010` | Every entrypoint requires exact staged/base-head/commit source and refuses ambiguity | M1 |
| `AC-011` | InputRule owner IDs are sole ownership; canonical nonempty baseline IDs use any-match activation and JSON Pointer semantics only add obligations | M1 |
| `AC-012` | Delete/shared reverse consumers and forward prerequisites close deterministically | M1 |
| `AC-013` | Invalid baseline IDs, unsupported parser, JSON refusal/limit, malformed bytes, or invalid controls force full, remain red, and block graduation | M1 |
| `AC-014` | Every M1 shadow logical row uses not-applicable/not-observed/null exit-duration with predicted causes and never claims pass | M1 |
| `AC-015` | Shadow links a same-SourceBinding validated full receipt/aggregate; sole IDs, canonical storage, privacy, import, and replay pass | M1 |
| `AC-016` | Timeout/interruption/cleanup leaves no process/index/object/temp/bytecode residue | M1 |
| `AC-017` | Guard order and exact-index data-guard remain authoritative prerequisites | M1 |
| `AC-018` | Local shadow predicts then runs source-bound preserved broad proof | M1 |
| `AC-019` | M1 pre-commit is offline, uncached, no-paid-runner, and remote-independent | M1 |
| `AC-020` | No current proof can be skipped in M1 | M1 |
| `AC-021` | Corpus meets 20/20/20/20/10/10 and ≥100 total | M2 |
| `AC-022` | Every declared edge has a failing mutation challenge | M2 |
| `AC-023` | Delete/shared reverse impacted closure selects all consumers/prerequisites | M2 |
| `AC-024` | Narrow inventory rejects unsupported dynamic dispatch without becoming an analyzer | M2 |
| `AC-025` | Unknown/inert/orphan/phantom/moved/stale cases, and any empty/ungraduated/ambiguous change-tag set, force full/control failure | M2 |
| `AC-026` | Base/candidate self-protection covers all critical controls/evidence | M2 |
| `AC-027` | Real-main focused/full observations bind identical candidate-tree digests | M2 |
| `AC-028` | Ten consecutive real-main changes have zero miss/safety mismatch | M2 |
| `AC-029` | A miss adds a fixture, reruns corpus, and resets streak | M2 |
| `AC-030` | Twenty same-byte current/full/focused pairs exist per proposed category/lane | M2 |
| `AC-031` | Imported/replay events carry Appendix-A schema/manifest/source/provenance links, candidate digest, sole event ID, a byte-identical base-anchored prior-event prefix, and once-only logical credit keys | M2 |
| `AC-032` | Controller/AWA preflight records exact present/absent capabilities and digests read-only | M2 |
| `AC-033` | Named doc-warden groups preserve current full/sandbox proof union | M3 |
| `AC-034` | Six setup-failure cases no longer recursively invoke broad full | M3 |
| `AC-035` | AWA kernel core is sole executor and copy honesty consumes its result | M3 |
| `AC-036` | Real local AWA core is universal; missing runtime blocks | M3 |
| `AC-037` | AWA simulation parity and cleanup remain | M3 |
| `AC-038` | Actual target full/deep executes each applicable ID exactly once | M3 |
| `AC-039` | Preserved-current and target-full proof/outcome parity passes on exact sources | M3 |
| `AC-040` | Git-local lane state durably invalidates local focus fail-closed via the lane-state reducer requiring manifest/ledger/state agreement | M3 |
| `AC-041` | Controller state durably invalidates PR focus fail-closed | M3 |
| `AC-042` | Ledger invalidation, reviewed rollback generation, and governed expired-schedule-only restoration are proven | M3 |
| `AC-043` | Qualified controller supplies immutable PR base/head to repository command | M3 |
| `AC-044` | Controller supports ISO-week+24h and calendar-month+48h periods with non-sliding expiry, exact source/deadlines, and missed-period invalidation | M3 |
| `AC-045` | Controller change is separately authorized and preserves runnerless/no-Actions constraints | M3 |
| `AC-046` | Dev-qualified pinned runtime executes real universal AWA proof in remote lane | M3 |
| `AC-047` | Dev custom recipe is qualified under actual image/resource/no-network limits, and full/deep fit a qualified cadence envelope (longer job or atomically aggregated exact-source shards) with no paid runner | M3 |
| `AC-048` | Remote PR/full-release/deep-periodic commands bind exact sources | M3 |
| `AC-049` | Recipe phase is merged and proven before lock phase | M3 |
| `AC-050` | Planner-defined lock/rebind affected set is complete; mixed generations stay backward-compatible with a predeclared central abort/rollback; no unrelated relock occurs | M3 |
| `AC-051` | Each lane's cadence is active (local expiry-gated, PR controller); pre-first-expiry activation proof gates only before first expiry; consumer-bound latest-required-period evidence gates focus thereafter | M3 |
| `AC-052` | Boundary/missed/late/wrong-period/expired/cross-bound evidence invalidates focus to full via the reducer; expired-schedule-only governed restoration and control-change full pass | M3 |
| `AC-053` | Every proposed category/lane has category speedup ≥3.0× | M3 |
| `AC-054` | 5× target and 10–20× aspiration are reported without becoming safety gates | M3 |
| `AC-055` | Every proposed category/lane has 19/20 focused runs within 3/5/12 and tighter cap | M3 |
| `AC-056` | Per-lane graduation binds corpus/streak/parity/AWA/speed plus consumer-bound activation-or-required-period event IDs and invalidation drills; the local event binds only local evidence | M3 |
| `AC-057` | Local focus runs only approved tags while both non-sliding local surveillance windows validate through the reducer | M4 |
| `AC-058` | Local uncertain/ungraduated/control changes remain full (a valid enforce-fallback receipt with observed full rows and fallback cause), and a non-schema renderer explains every fallback/invalidation code identically from pre-commit and an explicit CLI | M4 |
| `AC-059` | Local detecting failure invalidates immediately and durable rollback passes | M4 |
| `AC-060` | PR focus runs only independently approved tags while both non-sliding controller surveillance windows validate | M4 |
| `AC-061` | PR detecting failure and serial recipe/lock/manifest rollback pass | M4 |
| `AC-062` | First five focused changes per lane have zero miss/mismatch/residue | M4 |
| `AC-063` | Subsequent ISO-week evidence binds exact period/source and completes by Monday-end plus 24-hour grace | M5 |
| `AC-064` | Subsequent calendar-month evidence completes by 48-hour grace and replays 20 exact changes or all if fewer | M5 |
| `AC-065` | Just-before/at/after grace, missed/late/invalid/expired period, rollover, and clock fixtures remain fail-closed | M5 |
| `AC-066` | Full/deep/AWA/source-binding/sanitation remain green | M5 |
| `AC-067` | Receipt/ledger retention remains bounded and content-safe | M5 |
| `AC-068` | No Actions, paid runner, second controller, Mac driver, cache, Option 3, or chaos-scheduler change | M5 |

Task-to-AC ranges are exhaustive above. No AC is orphaned, and no task may claim Done while one of
its named AC credits is absent or non-passing in its acceptance bundle.

## 7. Governed delivery cadence

For each future coherent body:

1. work in one linked worktree from exact merged prerequisite state;
2. run task-focused tests and verification-before-completion;
3. commit only under the task's explicit authorization;
4. open a Draft PR and leave it unarmed;
5. run Bugbot; run security review for source/runner/receipt/hook/AWA/controller bodies;
6. wait for the named checkpoint where required;
7. never call `gh pr merge --auto`;
8. after merge, rebind exact main and append evidence in a separate governed body.

Recipe, lock, assignment, and relock are always serial phases with fresh operation IDs and matching
owner-GO. This plan never authorizes controller-repository mutation by implication.

## 8. Standard verification layers

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  _ops.verification.test_contracts _ops.verification.test_selector \
  _ops.verification.test_runner
PYTHONDONTWRITEBYTECODE=1 python3 _ops/verification/runner.py \
  validate-ledger _ops/verification/verification-rollout-ledger.json
git diff --check
```

```bash
bash _ops/checks/verify-changes.sh full --source-sha "$EXACT_SHA"
bash _ops/checks/verify-changes.sh deep-periodic --source-sha "$EXACT_SHA"
```

```bash
_ops/bin/repo-baseline.sh profile pr-automation v3 verify-control-plane
_ops/bin/repo-baseline.sh profile pr-automation v3 verify --repo-root .
```

Commands are not run before their owning task. The known >10-minute full suite is reserved for
implementation/release gates, not planning-only edits.

## 9. Rollback strategy

| Failure | Immediate action | Durable action |
|---|---|---|
| M0 contract mismatch | Stop; do not alter accepted artifact | Successor authority transaction |
| M1/M2 defect | Keep authoritative broad full | Revert inert/shadow body |
| M3 decomposition/parity gap | Run preserved wrapper/full | Revert decomposition; retain evidence |
| Local focused mismatch | Fail and mark Git-local lane invalid | Ledger invalidation + next manifest generation shadow |
| PR focused mismatch | Fail and mark controller lane invalid | Ledger + serial recipe/lock/manifest shadow rollback |
| Cadence issue | Fail the expired-window proof and invalidate the affected lane | Repair local cadence or controller/recipe via own governance |

No cross-machine instant rollback is claimed. Never delete full, rewrite accepted artifacts/
evidence/history, lower thresholds after failure, or bypass hooks.

## 10. Stop conditions

Stop on unrelated dirty files, stale base, missing checkpoint, accepted-artifact mutation,
unqualified controller/compiler/image, unbound candidate source, working-tree/HEAD fallback,
invalid receipt/ledger, missing AWA universal proof, parity omission/duplicate, safety mismatch,
cleanup leak, speed/budget miss for a proposed category, missing/late/expired required window, forbidden network/runner,
unplanned fleet relock, or any `chaos-scheduler` path.

## 11. Completion criteria

Complete only when:

- `AC-001`–`AC-068` all have valid passing ledger events;
- Checkpoints 0–5 are explicit;
- D2–D5 are explicitly accepted/replaced and consistently implemented;
- M1 was local full-authoritative shadow and no skip preceded Checkpoint 4;
- actual full/deep execute each applicable obligation once;
- recursive doc-warden and duplicate AWA/kernel execution are removed with parity;
- exact staged/PR/commit inputs, byte-safe paths, no-rename policy, sanitation, and cleanup remain;
- each activated common category/lane proves ≥3× and 19/20 absolute budget;
- universal AWA and durable invalidation/rollback/restoration remain; weekly `full-release` and
  monthly `deep-periodic` satisfy their non-sliding lane cadence windows;
- sequential execution is the sole runtime and no parallelism is introduced;
- policy/manual describe actual Python behavior; and
- no forbidden runner/cache/controller/Option-3/`chaos-scheduler` change exists.
