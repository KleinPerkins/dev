> HISTORICAL CONTROLLER REFERENCE. The installed controller is abandoned; the
> mutation commands described below are retired and must refuse. This material
> supplies compatibility/parser/test provenance, not operational instructions or
> authority to resume a service. Current policy: `_ops/POLICY.md` and
> `_ops/baseline/README.md`. PAC mini actions is planned development.

# PR automation lifecycle

## State and fingerprints

State is written only in the `KleinPerkins/dev` control plane at
`_ops/baseline/profiles/pr-automation/state/<owner>__<repo>.json`. It contains repository identity,
default branch, exact target branch and stage, ruleset generation, exact current/last-deleted
ruleset ids, monotonic owned generations, secret-free settings/ruleset preimages, normalized
postimages, SHA-256 fingerprints, lifecycle/recovery phases, returned-id ownership, exact rollback
proofs, pending settings/retarget transitions, normalized canary-proof digest/summary, operation,
and timestamps. Evidence URLs/API observations, tokens, headers, logs, and PR content are never
stored.

Normalization removes server-generated ruleset fields, recursively sorts object keys, and sorts
set-like rules, bypass actors, status checks, and ref conditions before hashing canonical compact
JSON. Formatting and GitHub response ordering therefore do not create drift; semantic changes do.

## Mutation boundary

- `verify`: local reads only; validates exact managed files, config schema, strict block-style
  aggregator shape, action full-SHA pins, no custom shell, every raw/decoded required-context
  producer, CODEOWNERS coverage, and profile conflict state.
- `status`: local reads plus paginated GitHub GET requests; separately reports active/paused/
  rollback lifecycle, stored-managed-postimage drift (including resource id), active-desired drift,
  and canary proof readiness. It never writes files or calls a mutating API method.
- `apply`: local files only. `--dry-run` writes nothing. It refuses a dirty checkout, a detached
  checkout, a non-KleinPerkins origin, excluded repos, and custom files at profile-owned paths.
- `enforce`: no flag means the actual default branch, preserving existing callers. An explicit
  `--target-branch <exact-head>` permits initial canary creation only after the branch exists,
  is locally checked out with compliant profile files, tracks its same-name origin ref, and exactly
  matches a fresh fetch and GitHub SHA. It persists an `initializing/pre_mutation` state with
  target, captured preimage, and expected
  fingerprints before its first remote reread. A failure there retries only while live id/state
  still match. It then creates/updates only `kleinperkins-pr-automation` and the three managed
  settings. A same-named unowned ruleset is refused.
- `enforce --retarget <exact-head> --canary-proof <json>`: changes only the target condition on the
  stored active ruleset id that was returned by this lifecycle. Proof-gated canaries require the
  exact prior rollback proof, a newer owned generation/id, and a current closed-schema evidence
  bundle. Before PUT it persists the exact normalized preimage and desired postimage, their
  fingerprints, target SHAs, settings fingerprint, and proof digests. Recovery accepts only the
  same-id preimage (retry PUT) or same-id desired postimage (finalize); every third state/id is
  refused. It never creates, adopts, or replaces a ruleset. Retargeting to the default branch
  requires a clean local default-branch checkout at the exact upstream/fetched/GitHub SHA.
- `pause`: keeps the exact active PR/check ruleset in force. It first drift-checks and sets
  `allow_auto_merge=false` while preserving the other settings, then paginates and owner-disarms
  remaining requests through `disablePullRequestAutoMerge`, and finally verifies zero remain.
  GitHub's disable mutation has no expected-head field, so each disarm checks PR node id and head
  SHA immediately before and after and fails closed on change. `settings_pending` and `disarming`
  phases make retries explicit. GitHub documents the repository setting as the gate controlling
  whether people can configure auto-merge; the engine re-verifies it before every disarm and fails
  closed if armed requests do not converge to zero. Direct/manual merges remain subject to the
  active ruleset. This is not a transactional halt: an already-eligible armed PR can merge after
  the repository setting closes but before its per-PR disarm. Successful return guarantees zero
  armed requests; it does not retroactively prevent such a merge.
- `repair`: optimistic drift refusal restores the exact recorded-target ruleset and settings from
  a clean checkout of that target.
- `rollback`: persisted `ruleset_pending` → `ruleset_done` → `settings_pending` → `complete` phases
  restore the captured pre-enforcement settings and ruleset. If enforcement created the ruleset,
  rollback deletes only an id recorded from a successful create response; an already-absent
  task-created ruleset resumes as a completed first phase. Deleting a canary generation persists a
  digest-protected, non-secret proof bound to generation, id, target/SHA, managed pre-fingerprints,
  exact restored preimage/post-fingerprints, and completion time. It uses the recorded
  target/postimage, never an assumed default branch.

`--dry-run` for every mutating verb performs reads and prints the intended methods/endpoints without
writing state or invoking POST, PUT, PATCH, or DELETE.

Before any mutating verb can issue a GitHub write, the local checkout must be clean, on its exact
recorded/requested target, tracking `origin/<target>`, and have one identical full SHA across local
`HEAD`, the upstream ref, a fresh origin fetch, and GitHub's branch API. Behind, ahead, diverged,
stale, detached, non-head, wildcard, missing, or untracked targets fail closed. A changed/missing
GitHub default branch relative to managed state is also refused.

## Canary proof and promotion

The safe lifecycle is explicit:

1. `enforce --target-branch <canary>` creates generation 1 and records its owned id/SHA.
2. Exercise the safety matrix.
3. `rollback` proves the original preimage; for a task-created ruleset this deletes generation 1
   and persists the exact rollback proof.
4. `enforce --target-branch <canary>` creates a new owned id and marks the canary generation
   recreated. Repeat mandatory safety checks as required.
5. Supply a `pr-automation-canary-proof/v1` bundle bound to generation 2, its owned id, current
   canary SHA, exact ruleset/settings fingerprints, context/integration, and destination. The exact
   15-scenario set is required; every result is pass with secret-free URL/API evidence. Direct push,
   red, cancelled, missing, stale, spoof, skipped/neutral, green auto-merge, manual update,
   protected-path self-authorization, history-ruleset unchanged, and pause are mandatory-live.
   Conflict, draft, and rollback may be mocked only because unavailable/unsafe cases are explicitly
   labelled and exact rollback is independently state-proven.
6. Check out the exact default-branch GitHub HEAD and run
   `enforce --retarget <default> --canary-proof <json>`. Only generation 2's verified id is PUT, and
   its id must be unchanged in the postimage.

Rollback never claims a deleted id survived. Generation 2 clears generation-1 evidence. Bundles
older than 24 hours, replayed from another generation/id/SHA/fingerprint, incomplete, or mocking a
mandatory-live scenario are refused. `status` distinguishes `canary`, `canary_rolled_back`,
`canary_recreated`, and `promoted`, alongside lifecycle, generation, and proof readiness.

The central ruleset has no bypass until a later live canary proves GitHub's PR-only admin bypass
cannot authorize direct pushes. `pause` is not a bypass: protected-path changes still require an
eligible CODEOWNER reviewer, and the history and PR/check rulesets remain active throughout.

**Phase B (GitHub-App path).** `fleet.py` provides the separate `phase-b` lifecycle. It owns an
independent merge-safety/review-gate pair, inert controller activation, credential-name metadata,
and digest-bound generation-2 qualification. Pair writes are ordered merge-safety before
review-gate for creation/promotion and reverse-ordered for rollback. Each returned id and normalized
postimage is persisted before the next write; same-name unowned resources and third-state drift are
refused. `pause` closes activation, disables and drains the controller workflow, disables repository
auto-merge, and disarms exact-head requests while retaining both rulesets. The Phase A lifecycle
above remains unchanged for read/rollback compatibility and never adopts Phase B resources.

Every mutating command holds a local per-repository file lock. Remote-mutating commands also
atomically create the temporary repository Actions variable `PR_AUTOMATION_FLEET_LOCK`, verify its
unique operation token before deletion, and hold it for the complete operation. This serializes
different machines as well as local processes. A crash can leave the lock behind; the engine does
not auto-steal it. An operator must inspect the recorded operation and live state before explicitly
removing a stale lock. The persistent secret-free `PR_AUTOMATION_FLEET_STATE` variable binds the
latest source-tracked state revision and digest; every state write compares and advances it under
the lock, so a second machine with stale local state cannot continue.

## Best-effort optimistic drift refusal

GitHub does not expose an atomic transaction or compare-and-swap primitive for these resources.
Before every independent write, the engine re-reads the live objects and requires both the exact
stored ruleset id and the normalized semantic fingerprints to equal the expected managed
postimage. After every write it re-reads and requires the exact resource id plus desired postimage.
An unexplained delete/recreate is refused even when semantics match. Creation and task-owned
rollback deletion are the only explicit id transitions. This narrows but cannot eliminate the race
between the final GET and subsequent write; the guarantee is best-effort optimistic drift refusal,
never atomicity.

Ruleset creation has no idempotency key or compare-and-swap. The engine records ownership only
after POST returns a concrete id and persists that id before post-verification. If POST raises or
does not return an id, state becomes `ownership_ambiguous`; an exact matching resource is not
adopted, enforce remains refused, and rollback will never delete it. This deliberately treats both
a committed-but-response-lost create and a failed-create/concurrent-exact-create race as ambiguous.
A failure before the first reread remains `initializing/pre_mutation`; retry reuses that preimage
only while live state still matches.

## Failure and recovery

Each API mutation is independent and its immediate preimage is persisted before the request.
Settings PATCHes also persist exact from/desired values and fingerprints. Enforce and repair retry
only when live settings equal one of those states, so a committed-but-response-lost PATCH can
finalize without rewriting while any third state is drift-refused. Every rollback phase compares
live settings to its stored postimage before writing. `status` shows lifecycle separately from
managed and active-desired comparisons. Ownership-ambiguous create outcomes require explicit
operator investigation rather than automated adoption or deletion. `repair` refuses when stored
id/fingerprints no longer match. Retarget 404/422/5xx or response loss leaves the exact transition
record intact. Recovery reads the same-id live ruleset before freshness checks. Exact persisted
desired postimage means the PUT already applied, so it finalizes using the persisted destination
SHA/proof digest even if the evidence is now older than 24 hours or the destination advanced.
Exact persisted preimage means no PUT effect is visible: retry then requires fresh canary evidence
and exact destination HEAD. While that preimage remains unchanged, a newly validated proof and/or
advanced exact destination may replace the pending binding; the replacement is persisted before
retry. Any third ruleset state or id mismatch refuses.
No verb ever adopts or mutates
`kleinperkins-dev-baseline`, ruleset id `18701139`, or any other ruleset.

GitHub API availability is a hard dependency for remote lifecycle operations. During an outage the
safety posture fails closed: existing required checks/rulesets remain server-side, while lifecycle
commands stop without guessing.

## Operator-attestation trust boundary

Lifecycle state, rollback proof records, and canary evidence are secret-free operator attestations
that prevent accidental stale/replay/binding mistakes; they are not cryptographically tamper-proof
against a malicious local operator. Anyone able to rewrite this state already possesses local
authenticated `gh` authority that can mutate the ruleset directly. A self-signature whose key lives
with the state would add no security, while an external signing authority would add a credential/App
dependency prohibited by Phase A. GitHub's live same-id and semantic fingerprint/postimage reads
remain the security authority. The source/final-report bundle retains evidence URLs and API
observations for operator review, but validation checks their closed schema, safe URL shape, and
binding—not the truth of the linked content.
