# AWA integrity host wiring

This runbook activates the M1 host triggers only after the source PR is merged and
the exact AWA v1.8.1 Global Capability Binding is available. The source PR itself
is source-only: it must not change the live runtime, Cursor hooks, local-jobs
state, LaunchAgents, Slack configuration, or Keychain.

## Source proof

Run these from a clean `KleinPerkins/dev` checkout:

```bash
_ops/bin/install-dev-awa-overlay.sh --check
_ops/bin/install-dev-awa-overlay.sh --preview
make worktree-verify
```

The preview must report an exact v1.8.1 install, a disabled local-jobs
registration, and seven external-owner hook roles. It must make no host change.

## Gated UAT

Do not continue until the merged source is checked out and the operator gives
explicit **operator GO** for live host activation.

1. Capture the current hook file digest/mode and local-jobs view as the external
   UAT witness.
2. Run `_ops/bin/install-dev-awa-overlay.sh`. This installs the exact release,
   repairs a stale GCB shelf pointer, stages the schedule disabled, captures a
   generation-bound copy of the validated hook preimage, and writes hooks last.
   For the reviewed v1.8.0 -> v1.8.1 upgrade only, an already-current hook
   projection may atomically advance the rollback record's release provenance
   from `60ae49b4b118211d4702d9297e3f479222f45cc0` to
   `ff978ade5ff9c7604f58f4b3810b1cd75ea3287f` after every schema, path,
   generation, source, contract, backup, digest, mode, ownership, link, and
   current-postimage proof passes. The original preimage backup, generation,
   preimage/postimage identities, and hook bytes remain authoritative and
   unchanged. Unknown predecessors or any non-release-only drift refuse.
3. Run `_ops/bin/install-dev-awa-overlay.sh --doctor`. Every required row must
   pass, including the private rollback record and its exact backup.
   `Slack alerts: opted out (default)` is healthy when optional Slack delivery
   is not configured.
4. Inspect local-jobs and confirm `com.kleinperkins.awa-integrity` is present,
   owned by this host overlay, scheduled every 21,600 seconds, and disabled.
5. Compare the hook file with the preimage. Unrelated rows and file mode must be
   unchanged; the effective AWA projection must have seven exact roles.
6. After reconfirming operator GO, run
   `_ops/bin/install-awa-integrity-job.sh --activate`.
7. Run one sweep through the validated local-jobs verb, then confirm the first
   private `status.json` and console artifacts:

```bash
"$HOME/.claude/skills/local-jobs/scripts/local-jobs.sh" run-job --id awa-integrity
"${AWA_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/awa/current}/bin/awa-engine.sh" integrity view
"${AWA_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/awa/current}/bin/awa-engine.sh" integrity console
```

Confirm that native alert delivery was attempted when the transition required
it. Slack remains optional and opted out by default.

## Optional Slack delivery

The private user configuration path is
`${XDG_CONFIG_HOME:-$HOME/.config}/awa/integrity-slack.json`. Do not commit,
copy, print, or attach that file. The fixed Keychain service/account
identifiers are read directly from the released AWA adapter; do not duplicate
their values in host docs or scripts. Use the approved private configuration
workflow rather than pasting credentials or user identifiers into logs,
commits, examples, or terminal history.

Doctor distinguishes three states without exposing identifiers:

- `Slack alerts: opted out (default)` — neither private input is present.
- `Slack alerts: configured` — both private inputs are valid.
- `Slack alerts: misconfigured` or `failed` — inputs disagree, are unsafe, or
  could not be checked.

## Rollback

Preview the order with
`_ops/bin/install-dev-awa-overlay.sh --rollback-preview`. Then run
`_ops/bin/install-dev-awa-overlay.sh --deactivate` while the exact release
binding is still present.

The rollback order is mandatory:

1. Turn host triggers off by disabling the owned local-jobs job.
2. Atomically restore the specifically captured hook preimage, including its
   exact bytes, unrelated row order, and original file mode. Restoration must
   refuse if the private record or backup is missing, malformed, stale,
   generation/path/provenance-mismatched, symlinked, or not privately owned.
   Never select an arbitrary `hooks.json.bak-*` file. The hook installer's
   explicit `--remove` verb remains intentional removal/uninstall behavior and
   is not the failed-activation rollback path.
3. Wait a bounded interval for an in-flight observer; terminate only its exact
   AWA integrity process tree if it does not finish.
4. Remove the owned local-jobs instance and type through local-jobs.
5. Revert the Dev host-wiring source only through the governed Git procedure.
6. Revert the Skills binding and installed runtime only through their owning
   procedures.
7. Remove derived integrity state only if separately operator-approved. Never
   delete or move the AWA v1.8.1 tag.

Re-run doctor/read-only inventory after each rollback boundary and retain the
preimage until the operator accepts the result.
