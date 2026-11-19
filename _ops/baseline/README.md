# Uniform repository baseline

This directory owns the shared local-file floor. [_ops/POLICY.md](../POLICY.md)
owns current delivery policy; `delivery-policy.json` records the explicit cohort.
The legacy PR controller is permanently offline. Its repository remains private
with no CI; publication and a new CI/release process belong to PAC Mini Actions
development after migration. Other public targets retain lasting CI/App delivery.

## Local floor

| File | Behavior |
|---|---|
| `README.md` | Create only if missing. |
| `SECURITY.md` | Refresh only the managed marker-delimited form; preserve an unmanaged file. |
| `.github/CODEOWNERS` | Create only if missing; preserve stronger existing ownership. |
| `.gitignore` | Merge only the managed secrets/editor/OS block; preserve other rules. |
| `.github/dependabot.yml` | Managed GitHub Actions dependency updates; preserve repository-specific policy. |

Keep the local canonical noreply identity and session-lock/identity/data guards.
Never bypass hooks or assume their presence protects another machine. The master
umbrella, separately governed work repositories, vendor references and foreign hook
frameworks retain their local mutation exclusions. Source preparation may test
installers only against explicit disposable fixture roots.

## Dispositions and delivery

The exact public CI/App cohort contains 13 KleinPerkins repositories. Six remain
private with no CI; Sterling's retired video project remains excluded. Names route
classification; live mutation must verify the immutable repository ID and approved
name. Unknown repositories remain unenrolled and never default to controller use.
A classification record is not a readiness or publication receipt.

Public targets use meaningful sharded standard-hosted Actions CI and one automatically
initiated independent review from the PR-creation Codex account. Same-account cloud
review is preferred; qualified same-account local review is allowed. No human
technical review is required. The qualified Chaos Scheduler App owns approval and
native squash/auto-merge after the current head, base, policy, origin, review, CI and
GitHub protections agree. Sensitive CI/governance changes use these same gates.
Self-hosted runners remain forbidden. See [Dev delivery](../../docs/github-delivery.md).

Private/no-CI repositories must not be published or enrolled by scaffold defaults.
Existing held work and host services remain unchanged until their accepted gates.
Scheduler's future common-framework convergence preserves its public release process;
this bounded transition does not modify its source or runtime.

## Scaffolding and verification

New scaffolds record `.github/test-sharding-required.json` and a pending
`.github/test-shards.json` before the first guarded commit. A pending foundation can
be created/resumed but cannot claim verification or delivery readiness. Removing a
manifest does not erase the history-recorded requirement. Do not auto-stage retired
controller files on normal, resumed or legacy creation paths. The old explicit
controller-enrollment option refuses.

The closed `dev-test-sharding/v1` contract has state, aggregate, discovery include/
exclude patterns and shards. Runnable configuration partitions discovered test files
exactly once across at least two nonempty shards, with bounded argv commands. Unknown
fields, duplicate membership, missing files, unsafe paths, symlinks, zero tests and
incomplete coverage refuse activation. Read-only interfaces:

```bash
python3 _ops/bin/test-sharding.py view --repo PATH
python3 _ops/bin/test-sharding.py verify --repo PATH --activation
```

These validators do not execute repository-supplied commands. Execution occurs only
inside the repository's separately approved source CI. Dev's own closed CI contract
adds exact-run/attempt provenance and complete aggregate validation. Historical
controller coverage or lock files never qualify successor CI.

## Commands and mutation boundaries

`repo-baseline.sh list` and `verify` observe. `apply` changes local files/guards and
requires appropriate repository scope; it is not read-only. Preserve stronger
repository-owned CI, review, release and history-integrity controls.

Legacy controller profile mutation, activation, repair, rollback, staging and
merge-safety reconciliation are retired, including direct Python entrypoints.
Read-only historical inspection and pure parser/render/refusal tests may remain.
They do not prove a running controller or authorize a restoration. Generic legacy
`enforce` must not weaken successor settings; exact new controls are installed only
through the accepted target-specific administrative transaction.

`dev-doctor` reports observed readiness/drift or UNKNOWN when evidence is unavailable.
It must not recommend reactivating, relocking or restaging the retired controller.
No claimed PASS may come solely from a local cohort name or copied historical state.

## Managed markers and preservation

Managed files retain their existing BEGIN/END markers so stronger hand-authored
content is preserved. Historical controller code remains only where useful to
meaningful compatibility/refusal tests. Historical runtime records and host state
are private preservation material, absent from clean source. They must never be
copied back to make tests green. The replacement's fresh-history adoption record
separates retained policy from old runtime authority.

The new repository framework belongs to the later repo-platform capability. This
baseline transition does not expand that effort or restart paused WIP.
