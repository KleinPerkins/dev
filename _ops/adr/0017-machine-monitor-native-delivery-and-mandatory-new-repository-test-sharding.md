---
{"approval":{"actor":"KleinPerkins","date":"2026-11-06","review_evidence":{"action_digest":"sha256:fa4408f7713b11dcb1cf22e17da036eb6d368d9b158298b83872cab263c1b449","choice":"Approve displayed draft transaction","kind":"operator-confirmed-exact-byte-draft-transaction","operation_id":"98360eef-db38-4205-896b-547713cfb825"},"review_scope":"Exact draft-byte review. Accepted-freeze application requires separate fresh operation-bound consent; draft creation consent is not reused.","review_sha256":"7388bb81ffe431571797952bd1273e82713013f72ef8f16040480327b66cbad7"},"authority":"semantic","github_repository_id":1278387789,"id":"ADR-54aec621-9236-53d2-87b7-9a60ef4ec92e-ca6cb75e-3255-586b-aa7b-045598aab86c","lifecycle":"approved","mutability":"frozen_after_approval","provenance":[],"relations":[],"repository_key":"54aec621-9236-53d2-87b7-9a60ef4ec92e","schema":"doc-warden/artifact/v2","supersedes":null,"type":"adr","version":1}
---
# Machine Monitor native delivery and mandatory new-repository test sharding

## Decision

Authorize an exact repository-specific native delivery exception for
`KleinPerkins/machine-monitor`, a public proprietary macOS application with its
durable checkout under `~/dev/personal/machine-monitor`. Use the existing
born-v2 repository scaffold, local canonical noreply identity, commit guards,
doc-warden governance and baseline history protections.

Only this additional identity may use the native GitHub Actions/reviewer-App
delivery model. Require explicit public visibility and bind settings mutation
to the canonical remote and observed immutable GitHub repository ID. Use free
standard GitHub-hosted runners, pinned actions/dependencies, credential-free
tests, bounded execution and evidence retention, and read-only default workflow
permissions. Paid, larger and self-hosted runners remain forbidden. The
ShadowSync exception and every unrelated repository retain their prior policy.

Machine Monitor owns its required sharded CI and reviewer-App qualification.
Require current-head/base CI, a fail-closed `ci-required` aggregate, stale-review
dismissal, resolved conversations, linear history, squash merging, branch
cleanup, and deletion/force-push protection. Only the repository's reviewer App
may approve an eligible exact ordinary head and arm native squash auto-merge.
Protected automation and governance changes retain their owner/admin path.
Missing credentials or qualification are explicit activation blockers and never
permission to weaken controls.

Every future new repository scaffold must record mandatory test sharding before
its initial guarded commit. A governance-only foundation may be published and
resumed while verification is pending. Verification activation and delivery
readiness require at least two nonempty runnable shards covering all discovered
tests exactly once, with stable shard IDs, declared commands and the
delivery-appropriate aggregate. Deleting current configuration does not erase
the requirement recorded in bootstrap history and resumable operation state.
Existing repositories and pre-existing resumable operations are not retrofitted.

Private repositories remain runnerless by default. Their aggregate remains
`pr-automation / verify`; new sharded targets additionally require a merged,
dev-owned coverage qualification bound to the immutable repository, shard
contract digest, approved profile, validated lock and complete shard set.
Native targets require `ci-required`. Missing, failed, cancelled, skipped,
empty, duplicate or stale shard results must fail aggregation. Neither
onboarding nor sharding validation executes repository-supplied commands or
expands the controller's qualified closed execution modes. Legacy onboarding
cannot be used to bypass the new prerequisite.

## Why

Machine Monitor is a native Mac application whose service, browser interface,
packaging and window lifecycle need independent verification. Public native CI
provides the selected free hosted Mac execution model. A durable sharding
prerequisite makes suite ownership and complete aggregate coverage explicit
before future repositories claim operational verification.

## Validation and limits

Use disposable fixtures to prove exact identity, public visibility, immutable-ID
binding, unchanged non-target classification, bootstrap/resume compatibility,
history-backed requirement persistence, complete shard assignment, aggregate
negative cases, and merged controller-coverage authority. Public application CI
must use synthetic telemetry and isolated ports/directories, without reading
real host process inventories or publishing retained machine data.

Source import uses an explicit reviewed allow-list, portable instructions and
preserved third-party notices. Keep generated environments, app bundles,
archives, screenshots, telemetry, raw logs and private import receipts outside
Git. Preserve the original local artifact and installed application.

Repository creation, source merge, hosted CI and reviewer-App activation are
separate verified outcomes. This decision does not approve a signed release,
notarization, updater, binary publication, replacement of the installed app,
fleet-wide Actions activation, existing-repository retrofit, changes to the
controller execution boundary, or mutation of excluded repositories.
