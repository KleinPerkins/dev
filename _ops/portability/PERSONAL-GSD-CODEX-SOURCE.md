# Exact-pin GSD Codex source-text evidence

This is a source qualification dependency for the complete personal active-v2
Doc Warden workflow. It does not install GSD, replace the existing M1 runtime
qualification, publish a skill, authorize a worker, or accept the full capability.

The unchanged owner pin is `@opengsd/gsd-core@1.11.0`, upstream commit
`182f60b4c170785d96f1deb87fea8b108e9b985f`. The pinned npm SHA-512 and an
additional SHA-256 bind the package before archive interpretation or execution.
The four raw package skills and corresponding command inputs have individual
expected hashes. The actual package's `convertClaudeCommandToCodexSkill` export
produces four further expected hashes. These are raw converted text hashes,
not hashes of a retained personal installation.

Run with Python `-I -B`, an already downloaded package and the actual installed
Node binary; the observer downloads nothing:

```sh
python3 -I -B personal_gsd_codex_source.py \
  --tarball /absolute/path/to/gsd-core-1.11.0.tgz \
  --node /absolute/path/to/node
```

The observer verifies the legacy owner's pin and interface bytes separately.
It creates a private disposable package reference after refusing traversal,
duplicate/ancestor collisions, links, special files and size/count violations.
All 943 regular files are checked again after conversion. Their loaded module
closure is returned with individual source hashes. No npm command, lifecycle
script, package installer, GSD utility or GSD workflow is executed.

The converter runs once under Node's filesystem/process permission model with
read access only to the disposable package and the digest-bound harness. It has
no filesystem-write, child-process, worker, addon or inspector permission.
The harness restricts module imports to package-local files and a small builtin
set. An unrelated conversion dependency imports `child_process`; every operation
on that interface throws. Network module imports throw. The harness probes
outside-read, write, child-call and network-import denial before conversion.
The existing bounded process implementation enforces 12 seconds, 1 MiB per
stream and process-group cleanup. A refused/missing guard, changed output or
unexpected result shape stays unavailable.
Contract and child JSON reject duplicate keys, non-integer/non-finite numbers
and non-UTF-8 input, consistent with the owner record boundary.

The child receives the real `HOME` and preserves an existing `CODEX_HOME` value.
Neither is redirected to a fixture. Node options, proxies, credentials and other
ambient execution settings are not inherited. Saved output contains only the
closed hash/guard projection: no home values, raw environment or descriptor
bodies. The parent validates the bounded converter response before projecting it.
Unit tests check a differing home
identity by mocking the identity lookup, without replacing either environment
variable. The path and import restrictions are appropriate for this reviewed
single converter invocation; they are not a general hostile-JavaScript sandbox.

## What remains before native installation

The legacy binding qualifies Cursor and its real-home guard names the original
source machine. It must not be used as the destination's live installation route.
The pinned upstream Codex installer can use `~/.agents/skills` independently of
an explicit config directory, install agent/config/hook surfaces and clean older
skill paths. This observer never invokes that installer.

Raw converted descriptors still reference runtime locations and broader workflow
instructions. They cannot be published as an authoring-only personal installation
by copying these four files. The successor must bind complete runtime/context
paths, the restricted authoring interface, the personal Doc Warden preview and
transaction boundary, model/agent constraints, immutable preimages and exact
native destination/rollback ownership. It then needs actual current-build
discovery/use and the separate exact retained-installation owner decision.
Any path or instruction overlay changes descriptor hashes and requires its own
qualification; these raw hashes cannot be relabeled as installed hashes.

No original migration requirement is removed or weakened by this dependency.
Existing source pins, profile/receipt state, shared skill roots and all protected
components remain unchanged. The scope is personal-only; it grants no Affirm
access or authority over any controller, service, release or repository writer.
