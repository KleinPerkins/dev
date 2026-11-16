# Runbook: Re-qualify a GSD Core lock change

**Status:** ACTIVE — 2026-10-20
**Owning repo:** `KleinPerkins/dev`
**Owner:** repo-owner (an agent runs it; the owner merges the protected `_ops` PR)
**Trigger:** the `gsd-core runtime qualification record` check in `doc-warden-verify.sh` fails,
usually on a Dependabot PR that edits `_ops/doc-warden/runtime/gsd-core/package-lock.json`
**Frequency:** on demand, once per lock change
**Estimated duration:** 15 minutes
**Last verified:** 2026-10-20

---

doc-warden pins its GSD Core helper runtime by digest in
`_ops/doc-warden/state/v2/runtime/gsd-core-v1.11.0-qualification.json`. A lock change must land
together with a refreshed record, or `main` fails `runtime_qualification_digest_mismatch`. The
runnerless `repo.dev.m3-verify` job runs the same check on every PR, so an unqualified lock bump
fails its own checks.

## Prerequisites

- A linked worktree of `KleinPerkins/dev` on a new branch from `origin/main`. Never push to a
  Dependabot branch; Dependabot force-pushes its own branches.
- Node and npm at or above the pin's `node_min`/`npm_min`, and network access to
  `registry.npmjs.org`.

## Steps

1. Take the lock from the PR:
   `git fetch origin pull/<N>/head && git checkout FETCH_HEAD -- _ops/doc-warden/runtime/gsd-core/package-lock.json`.
2. Review `git diff origin/main -- _ops/doc-warden/runtime/gsd-core/package-lock.json`. Continue
   only if every item holds; otherwise recommend closing the PR and say which item failed.
   - Only `version`, `resolved`, `integrity`, and harmless metadata such as `funding` change. No
     package is added or removed, and no entry gains `hasInstallScript`.
   - Each `resolved` stays on `https://registry.npmjs.org/`, and each `integrity` equals
     `npm view <name>@<version> dist.integrity`.
   - The publisher (`npm view <name>@<version> _npmUser`) matches the previous version, or is the
     project's own trusted-publishing workflow according to `dist.attestations` provenance.
   - The version adds no lifecycle scripts (`npm view <name>@<version> scripts`), is not
     deprecated, and its changelog explains the change.
3. Run `bash _ops/doc-warden/runtime/gsd-core/tests/verify-binding.sh` and expect
   `verify-binding: PASS`. It installs into a throwaway HOME with `npm ci --ignore-scripts`.
4. Run `PYTHONPATH=_ops/doc-warden/v2 python3 -m doc_warden.runtime_qualification refresh`. It
   regenerates `dependency_licenses` from the lock, recomputes `package_lock_sha256`, sets
   `qualified_at`, and records the node/npm used. It refuses when any other pinned file changed
   (installer, `package.json`, pin, interface, verifier) or a changed package has install scripts
   or a non-registry tarball; those need a full runtime re-qualification instead.
5. Confirm `PYTHONPATH=_ops/doc-warden/v2 python3 -m doc_warden.runtime_qualification check`
   exits 0, and the record diff shows only the reviewed packages, `package_lock_sha256`,
   `qualified_at`, and any `toolchain` change.
6. Commit the lock and the record together. Open a PR that names the Dependabot PR it supersedes
   and lists the step 2 evidence, then close that Dependabot PR or let Dependabot close it once
   the lock lands. `_ops` is protected, so the owner merges.

## Verification

`bash _ops/checks/doc-warden-verify.sh --sandbox` passes locally, and the PR's
`pr-automation / verify` check is green.

## Rollback

Revert the PR. The lock and the record restore together; neither half is valid alone.

## Notes

The check is offline and only compares bytes, so it cannot judge whether a bump is safe. Step 2
is the security review, and it is never skipped.
