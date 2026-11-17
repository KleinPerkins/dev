# Successor source delivery

This source targets the fresh repository ID `1459458379`. The only reviewed name
phases are `KleinPerkins/dev-temp` and `KleinPerkins/dev`. Live metadata, workflow
event, token scope, PR origin, review tuple and CI identity must agree on the one
current phase. Old ID `1278387789` is never an alias. A rename requires external
writer-OFF fencing, separately released administration and fresh final-name
qualification; the presence of both names in source authorizes none of that.

Eight source shards cover every baseline test module and added delivery tests:
owner contracts, Doc-Warden, scaffold retirement, host-overlay fixtures,
interoperability/portability, context measurement, review admission and CI negative
cases. `.github/test-shards.json` is the single membership manifest using the
existing `dev-test-sharding/v1` schema. `.github/ci-contract.json` binds command
ownership and the 97-module baseline floor. `make verify-ci` runs their full local
union; `--ci-group GROUP` selects the identical group. Installed host state is a
separate verification mode. The worktree command uses `--source-only`: synthetic
overlay lifecycle, binding-refusal, degraded-guard and copy-contract checks still
run, while installed kernel UATs, live engine smoke and sibling-backed proof are
withheld. Runtime roots are disposable and absent; source success cannot qualify
an installed release. Default `worktree-verify.sh` keeps release-binding validation
and host checks, including failure on an invalid installed binding. Standard `macos-15` executes the Darwin synthetic
transport tests; it does not qualify an installed capability or account.

Source workflows use contents-read only, pinned checkout/setup actions, no
credential persistence, full ancestry, bounded standard hosted jobs and a hashed
PyYAML dependency lock. The host-overlay scanner parity lane installs the exact
Ubuntu Noble `ripgrep` package `14.1.0-1` only after verifying its published SHA-256
([package integrity](https://packages.ubuntu.com/noble/amd64/ripgrep/download)); it
does not resolve a mutable package candidate. The always-run `ci-required` aggregator rejects missing,
extra, failed, skipped, cancelled and stale shard evidence. Each receipt binds
repository/name, merge parents, revision, workflow, run/attempt, command inventory,
contract digest, measured case count/ID digest and explicit skips. A green local
run proves neither hosted execution nor installed-host qualification.

The CI workflow also exposes a no-input `workflow_dispatch` for the separately
released first-current-main administrative bootstrap. The accepted seed is
uploaded with Actions OFF. Enabling Actions does not establish a run for that
existing commit; after the publication and Actions-enablement gates, an authorized
administrative agent dispatches the real `CI` workflow at `main`. This is not a
per-PR review, a request for a human technical gate, or permission granted by this
document. Do not make a dummy commit or synthesize a check to obtain bootstrap CI.

For the reviewed `KleinPerkins/dev-temp` phase, the exact API operation is:

```sh
gh api --method POST repos/KleinPerkins/dev-temp/actions/workflows/ci.yml/dispatches --input - <<'JSON'
{"ref":"main"}
JSON
```

Use the `KleinPerkins/dev` endpoint only after the separately released rename and
fresh final-name qualification. Before dispatch, recheck immutable repository ID
`1459458379`, its current reviewed name, default branch `main`, the approved seed
at current main, Actions state and workflow source. The dispatch has no inputs.
GitHub requires the workflow file on the default branch; the dispatched branch or
tag determines `GITHUB_REF` and `GITHUB_SHA` ([event reference](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_dispatch),
[dispatch API](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event)).
Here only `refs/heads/main` is admitted. PR head/base fields must be empty,
checkout and workflow SHA must equal the actual tested revision, and the workflow
path/ref/name must agree. A non-main dispatch cannot produce a successful source
receipt; the always-run aggregate still refuses it. Contents-read permissions,
pinned actions, standard hosted runners, all eight closed shards and exact-run
aggregation are identical for this event.

API acceptance is not completion evidence. Observe the actual run/attempt for the
approved current-main SHA, all nine successful jobs and their Actions check-suite
bindings, and the unique real aggregate record before claiming hosted CI.
Current-main read-only App qualification accepts `push` or `workflow_dispatch`
only with that exact current SHA, main branch, repository/workflow and contract
bindings. It considers the newest returned current-main run and refuses a failed
newer run. Recheck current main and controls around qualification. A dispatched
main run cannot substitute for PR CI: ordinary admission still requires a
`pull_request` run with the exact PR/base/head/merge tuple. App readiness, first
ordinary admission, independent review and App-owned native squash merge remain
separate gates.

The privileged Reviewer App workflow checks out only its trusted workflow SHA
and current-main policy. Candidate code is never executed there. It verifies
App `4217367`, bot `299927791`, repository-scoped token, originating-account
creation witness, fresh passing local review, strict `ci-required` from Actions
`15368`, every exact-run CI job/check-suite and the unique aggregate log record.
The aggregate contract digest is checked against raw contract files from the
actual tested revision. Retired `pr-automation /` blockers are rejected from the
first successor qualification; there is no legacy-bootstrap mode.

The separate Reviewer App `workflow_dispatch` is read-only (`receipt` or `app-current`). Live App
qualification requires `REVIEWER_APP_QUALIFY=true` and the writer flag OFF.
Ordinary App writes require both trusted enrollment enabled and the separately
released external `REVIEWER_APP_ENABLED=true`. The App rechecks mutable gates
before and after approval. It alone requests native squash for an observed
merge-ready PR or arms native squash auto-merge for an eligible blocked PR.
Failure/ambiguity never authorizes a fallback merge or blind retry.

The initial disabled empty enrollment registry intentionally blocks ordinary
admission. It must contain both genuinely qualified producers before the exact
seed is frozen. Canary account receipts, GitHub installations and old controller
checks do not transfer. Initial full-tree review uses the separate bootstrap
capture described in `bootstrap-review.md`; it is never an ordinary PR receipt.
No source upload, publication, settings change, activation, host installation or
rename is authorized by these source files.

## Evidence ladder and the ordinary delivery trigger

Use the smallest claim supported by the observed operation:

| Observation | Claim supported | Still required |
|---|---|---|
| Exact current-main CI run and aggregate pass | That main revision passed source CI | Actual PR CI, creation/review admission and ordinary delivery |
| Successful read-only `receipt` dispatch for an actual PR | The observed PR tuple passed receipt/CI/control admission | A permitted ordinary event and actual App-owned merge |
| `REVIEWER_APP_ENABLED=true` read back | Ordinary writer configuration is enabled | A triggering event, fresh mutable gates and observed merge outcome |
| Actual App review and native squash merge observed | That specific PR was delivered | Fresh qualification for later changed tuples |

A variable update is not an event subscribed to by this workflow. After a
separately authorized writer enablement, the coordinator uses a fresh passing
receipt for the current originating-account/head/base/policy tuple and publishes
its unedited authenticated receipt comment. That `issue_comment:created` event
is an explicit ordinary trigger; a later successful PR CI `workflow_run` can
also trigger admission. `workflow_dispatch` remains read-only even when the
writer variable is true. Never replay the unique creation witness or operate
auto-merge to compensate for a missing ordinary trigger.

Turning the writer OFF inhibits the later write path; it is not cancellation
or proof that already queued/in-flight App work and native merge requests have
settled. Any separately released rename or host transition must observe that
settlement under its owner procedure before proceeding.
