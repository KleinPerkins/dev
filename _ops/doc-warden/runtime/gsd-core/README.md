# GSD Core host-overlay binding

This directory binds doc-warden to the exact public package
`@opengsd/gsd-core@1.11.0` at upstream commit
`182f60b4c170785d96f1deb87fea8b108e9b985f`. It does not vendor GSD workflow,
template, skill, or agent source.

The binding is restricted to authoring and governance context. Doc-warden may
prepare and validate results from the allow-listed interfaces in
`runtime-interface.v1.json`; it does not expose GSD's autonomous execution,
shipping, branch, worktree, or tag workflows.

## Operations

```bash
bash install.sh --check
bash install.sh --apply
bash install.sh --doctor
bash install.sh --repair
bash install.sh --uninstall
bash install.sh --print-pin
```

`--apply`, `--repair`, and `--uninstall` act only inside the supplied
`HOME`/XDG roots. The package is installed under
`${XDG_DATA_HOME:-$HOME/.local/share}/gsd-core/releases/<commit>/` with
`npm ci --ignore-scripts`; stable shims live under `$HOME/.local/bin`.
Uninstall removes only binding-owned paths whose recorded identities still
match. Use a test-owned HOME until the separately gated live-install step.

The doc-warden wrapper's `runtime doctor-gsd` command is read-only and emits a
closed live observation. `runtime doctor-gsd --observation <path>` validates a
prior observation and emits an explicit status record: `live_freshness` reports
whether the observation's `source_revision` is current HEAD, while
`evidence_status` reports whether the persisted observation/receipt/event
lineage was verified. Current pre-apply observations with no persisted lineage
are valid but `not_historical`/`not_persisted`; callers that need live-gate
proof must pass `--require-current`. `runtime doctor-gsd --preview`
additionally creates a digest-bound generic-apply preview for the emitted
source-tracked observation; it still writes no repository content until the
separate `apply` command.
Source-tracked v2 receipts intentionally project `canonical_root` as
`$REPOSITORY_ROOT` so durable evidence does not expose a machine-local user or
worktree path. The full resolved root remains bound in the machine-local preview
specification and consent material, and `confirmation_digest` is computed from
that resolved root. Auditors cannot recompute that digest from the projected
tracked receipt alone; they need the original preview/consent material or must
recompute the action digest from an equivalent resolved-root preview.

The M1-T01 qualification binds the complete `runtime-interface.v1.json`
digest, package pin, lock, and installer, but it does not contain expected
per-`SKILL.md` digests. Live doctor therefore resolves every retained skill and
bounded utility, labels each installed digest as a live observation, and
separately labels the qualified interface manifest digest as M1-T01 evidence.
It does not claim those live descriptor digests were individually qualified. A
gate requiring per-descriptor expected digests needs a successor runtime
qualification rather than inferred values.

## Lock changes

Any change to `package-lock.json`, including a Dependabot bump, must be re-qualified in the same
PR. Follow `docs/runbooks/gsd-core-lock-requalification.md`; `doc-warden-verify.sh` fails the PR
until the qualification record matches the lock.

## License and provenance

GSD Core is consumed as an npm package under the MIT License:
Copyright (c) 2026 Open GSD. The complete notice remains inside the installed
package and at the immutable upstream revision linked by `gsd-core-pin.json`.
