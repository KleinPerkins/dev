# Whole pinned Codex GSD bundle

`personal_gsd_codex_bundle.py` prepares an inert private package for the complete
personal active-v2 authoring frontend. It is a successor dependency to the raw
source-text observer, whose interface and evidence remain unchanged. This is not
a native installer, a complete frontend, or full active-v2 acceptance.

The unchanged owner pin is `@opengsd/gsd-core@1.11.0`, upstream commit
`182f60b4c170785d96f1deb87fea8b108e9b985f`. Before interpreting the archive, the
producer authenticates both the pinned SHA-512 integrity and SHA-256. It reuses
the accepted archive and bounded-process implementations. The new closed contract
also binds its emitter, network profile, qualified Node binary, owner dependency
lock and original authoring-role policy. Neither the original installer nor its
source-machine HOME override is executed.

## Private owner interface

Run the accepted complete source export with Python `-I -B`. The exact public
tarball is provided on stdin once; the CLI does not accept an arbitrary cache,
operation root, repository root, XDG override or Node path:

```sh
python3 -I -B personal_gsd_codex_bundle.py cache < /approved/public/gsd-core-1.11.0.tgz
python3 -I -B personal_gsd_codex_bundle.py prepare --operation-id OPERATION_UUID
python3 -I -B personal_gsd_codex_bundle.py verify --operation-id OPERATION_UUID
```

State is below the account-database operator home's existing mode-0700
`.local/share/personal-portability` directory. The fixed cache is
`gsd-codex-package-cache/gsd-core-1.11.0.tgz`; operation directories are fixed
children of `gsd-codex-bundles`. Cache bytes must match exactly, existing foreign
cache contents are held, and an existing operation is never adopted or rebuilt.
Verification creates no missing directories. Failed preparation stays visible;
it is not automatically removed or resumed under the same UUID.

The Python `prepare_into`/`verify_into` APIs support caller-owned, empty private
fixture directories. They grant no target-root or native publication authority.
Production CLI selection cannot choose a fixture root. Source and test fixtures
preserve real HOME and any existing CODEX_HOME values. A noncanonical CODEX_HOME
is refused as unsupported data; it is never overwritten or probed as a fallback.

## Whole upstream emission

The reference contains all 943 regular package files. The resulting private
bundle contains all original package paths plus the upstream Codex role/config
outputs and explicit project configuration: 979 files in total, including all
556 runtime paths. Runtime modules require package-owned sibling scripts, so a
copy of only `gsd-core/` is not a complete dependency closure.

The producer initializes the exact package's `bin/install.js` as a module and
calls its public `copyWithPathReplacement` and `installCodexConfig` functions.
Installer main, broad install, hooks, migrations and native cleanup are not
invoked. The fresh owned core copy and temporary four-skill staging are the only
private cleanup targets. All package JS/CJS/JSON bytes stay unchanged. The
upstream converter and rewrite walker process exactly the four allowed skills;
the other 57 packaged descriptors remain byte-identical and inert. The complete
runtime's 221 Markdown rewrites use upstream composition and conversion, without
vendoring a smaller selection of workflows or reconstructing intra-phase logic.

The role emitter normally probes home defaults and ancestor project config.
The producer uses its public `withInstallFs` interface to supply an explicit
empty global-default object and an owner preset of `runtime=codex` with
`model_profile=inherit`. The actual home defaults are never read. A project
config in the private emission root stops the ancestor walk. These are explicit
emission inputs, not a claim about an operator repository's configuration.

All 34 role TOMLs are emitted and parsed privately. Sandbox values must match
the upstream map, model and effort pins must be absent, and the nine allowed
authoring roles must be present. Other role data is not exposed to a native
catalog. Light roles can emit `service_tier=flex` and `model_verbosity=low`; TOML
parsing does not establish actual Codex build/account compatibility. The private
config's `[agents].max_depth=1` is also data, not permission to change host config.

The parent independently inventories every output, rejects unexpected paths,
links, special/shared/foreign files, missing companions, changed modules,
nonselected descriptor edits and failed guards. Descriptor-relative no-follow
reads preserve the accepted reader's 1 MiB bound; the exact package's largest
file is below that limit. Sealing restores original executable bits as read-only
mode 0500 and uses mode 0400 otherwise; directories are 0700 and the operation
record is 0600. The record binds implementation bytes, exact inventories and
operation/bundle directory identities. Verification rechecks these bindings,
including permissions and visible drift. This is cooperative owner tooling,
not an unforgeable same-user security boundary.

## Execution and qualification limits

The child receives only the real home values, a fixed PATH/locale and explicit
GSD test mode. Node options, credentials and proxies are not inherited. macOS
`sandbox-exec` denies all network; Node grants read access only to the reference,
emitter and fresh bundle, and write access only to that bundle. Child processes,
workers and addons are not permitted. Package imports stay in the authenticated
reference; unrelated child-process operations throw. Outside-read/write,
source-write, child-call and actual OS network-denial probes must all pass.
The accepted runner enforces 12 seconds, 1 MiB per stream and process-group
cleanup. Other platforms or an unavailable OS fence remain unsupported.

TOML parsing is required when validating actual role/config outputs. It is loaded
at that boundary rather than when importing the source or testing/cache-loading
the contract. A missing standard-library parser returns a closed unavailable
result; it never becomes empty or accepted role data. The actual bundle/runtime
fixtures are qualified on Python 3.12 and 3.13. No parser dependency is downloaded
or substituted to make an unsupported runtime appear qualified.

Saved metadata contains relative file/module paths and hashes, configuration
input identities and explicit incomplete gates; it contains no home values,
raw descriptor bodies, credentials or child stderr. The operation's own absolute
root is machine-local metadata. This command does not launch the GSD CLI or a
model worker. Separate fixture qualification of selected CLI commands must not
be relabeled as complete workflow or dependency-lock qualification.

Before using the full capability, complete the dependency-lock/runtime closure,
personal repository/operation selection and authoring transaction frontend,
current-build native role/model ABI, and precise runtime-path bindings. In
particular, discuss-phase contains dynamic runtime/client/moving-version fallback
instructions: the owner frontend must bind RUNTIME_DIR and forbid those fallback
routes rather than execute or silently strip them. Preserve whole workflow
semantics and the complete lifecycle, Save-Game, trigger, new-repository and
maintenance requirements. Actual native discovery/use and separately reviewed
retained installation need their exact preimage, approval and rollback gates.

No native links, profile adoption, workers, services, controllers or original
migration journals are changed. Source acceptance grants none of those actions.
The personal/Affirm boundary and all protected no-touch components remain intact.

## Verification

```sh
python3 -B test_personal_gsd_codex_bundle.py
```

The direct owner invocation runs in both verification modes and refuses a
missing test file. Its offline fixtures create no real host state and execute
no package download, npm lifecycle, native installer or worker.
