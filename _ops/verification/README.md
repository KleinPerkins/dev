# Verification wire contracts

Successor boundary: `verification-rollout-ledger.json` is retained unchanged as
predecessor provenance and a protocol fixture. Its old genesis and acceptance
events are not current source authority or successor rollout/qualification credit.
The current source relation is recorded in `_ops/policy/dev-successor.json` and
[the successor adoption runbook](../../docs/runbooks/dev-successor-adoption.md).
The import/rollout commands below describe the retained historical contract; they
are not an authorized successor rollout path.

This directory contains the **FROZEN v1 runtime contract**, the M1 inert selector, and the M1
local-shadow runner for manifest-driven verification. The three closed schemas remain unchanged.
The selector binds an exact source and predicts a deterministic plan. The runner materializes that
same candidate, executes the preserved broad verifier sequentially, stores its authoritative full
receipt first, then stores the linked shadow prediction. It does **not** activate focus, skip a
check, change a hook or recipe, use a remote dependency, or add a result cache.

Run the M0 contract, M1 selector, and M1 runner suites from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  _ops.verification.test_contracts _ops.verification.test_selector \
  _ops.verification.test_runner
```

## Local-shadow runner

`runner.execute_local_shadow(source, manifest, selection)` accepts only the selector's explicit
source-bound M1 shadow result. It builds a mode-0700 snapshot from captured candidate blobs, creates
an isolated temporary Git index/object store inside that snapshot, and runs the fixed preserved-full
argv in one process group. Environment names, output, time, CPU, memory observation, file size,
descriptors, and process count are bounded. Interruption or timeout uses TERM, bounded wait, KILL,
wait/reap, and complete owned-tree removal. A cleanup result is never accepted as passing evidence
unless every cleanup flag is true.

Receipts live outside the working tree at:

```text
$(git rev-parse --git-path verification-selector)/receipts/sha256/<receipt-id-hex>.json
```

Every state directory the runner creates is mode 0700 and every receipt is mode 0600. Stored bytes
are canonical JSON without a trailing newline; the filename is the sole `receipt_id` without
`sha256:`. Writes use a same-directory temporary file, `fsync`, and atomic rename. Retention keeps
the latest imported local success and at most 32 imported unsuccessful local events' receipts;
unimported receipts are never silently removed. On startup, only an exact `.receipt-` temporary
name that is a same-owner, single-link, mode-0600 regular file is removed as interrupted owned
work; symlinks, non-regular files, unsafe modes, and unknown names remain untouched and fail closed.

The runner CLI exposes the implementation seams that later hook wiring may call without changing
current hook behavior in this task:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 _ops/verification/runner.py \
  explain selector.lane-shadow receipt_invalid
PYTHONDONTWRITEBYTECODE=1 python3 _ops/verification/runner.py \
  rollout-import --receipt <git-local-receipt>
PYTHONDONTWRITEBYTECODE=1 python3 _ops/verification/runner.py \
  validate-ledger _ops/verification/verification-rollout-ledger.json
```

`render_explanations()` is the same importable renderer intended for the pre-commit interface. It
only explains existing closed selector, receipt, and invalidation codes and cannot alter an outcome.
`rollout-import` accepts only an exact-root, canonical, private receipt; revalidates identity,
manifest, source, candidate digest, linkage, privacy, and committed replay; and atomically appends
one closed observation. The checked-in ledger blob digest and tip anchor the complete immutable
prefix, and the frozen reducer rejects a second conflicting passing logical credit. The durable
ledger append is the import commit boundary: retention runs afterward, cannot remove the newly
credited receipt, and an exact retry returns the existing event while retrying bounded cleanup.

M1 classification tags use schema-valid dot/hyphen tokens such as
`change.docs-ordinary` and `change.doc-warden-core`. Appendix A.3's token grammar excludes
underscores, while target-design §12's performance-category labels use them. The M1 tags are
reporting-only and ungraduated; later graduation must explicitly resolve and bind its accepted tag
literals rather than infer equivalence.

The checked-in `authority_genesis` event mirrors—rather than creates—the immutable authority of
acceptance commit `a99abb4fde94836e6e3f697cda8c520f3c2ae6b7`. Its timestamp is fixed, and its
artifact, schema, operator-record, classification-tool, and event identities are reproducible.

## Documented interpretations

Appendix A governs the wire semantics. These required bytes or validation seams were not otherwise
fully pinned and remain explicit Checkpoint-1 review questions:

- **Operator-record preimage:** canonical
  `{"acceptance_commit_sha":"a99abb4fde94836e6e3f697cda8c520f3c2ae6b7"}`. Its SHA-256 is both
  genesis provenance fields. This is the smallest canonical object that names the immutable
  acceptance commit without importing mutable projections or Git signature formatting.
- **Direct-classification tool preimage:** canonical
  `{"algorithm":"whole-artifact-sha256-equality","version":1}`. The same tool digest is used for
  all three direct classifications because the frozen whole-blob digest comparison is identical;
  Appendix A does not identify an executable or source-file preimage for `tool_sha256`.
- **Genesis time:** `created_at` and `occurred_at` both use the acceptance commit's committer
  second in UTC, `2026-09-02T17:51:34Z`; neither uses the current clock.
- **Schema representation:** each schema uses only draft-2020-12 assertions needed by the frozen
  contract, with no `$id`, title, description, or default annotations. Schema identities hash the
  parsed schema's A.1 canonical bytes, so source indentation is non-authoritative.
- **Observation generation binding:** A.7's observation payload has no generation field.
  Consumer binding therefore resolves the observation's exact `manifest_id` and compares that
  manifest's `activation.generation` with the graduation/restoration generation.
- **Secret-like environment names:** the closed validator accepts uppercase POSIX-style names and
  rejects names containing `TOKEN`, `SECRET`, `PASSWORD`, `PASSWD`, `CREDENTIAL`, or
  `PRIVATE_KEY`, plus names ending in `_KEY`. Appendix A requires rejection but does not freeze the
  lexical list.
