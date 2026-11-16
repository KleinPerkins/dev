---
{"approval":{"actor":"Codex under explicit owner-delegated execution authority; reviewed dev host-policy adoption only, not operator personal hash inspection","date":"2026-11-02","review_sha256":"81d2e1b992d41c893eb959cb75607892648990ea443b73de8cb32653c92aaa24"},"authority":"semantic","github_repository_id":1278387789,"id":"ADR-54aec621-9236-53d2-87b7-9a60ef4ec92e-387ed704-6609-5ee5-9621-93219fda53d0","lifecycle":"approved","mutability":"frozen_after_approval","provenance":[],"relations":[],"repository_key":"54aec621-9236-53d2-87b7-9a60ef4ec92e","schema":"doc-warden/artifact/v2","supersedes":null,"type":"adr","version":1}
---
# Context

ShadowSync is moving from the private Skills tool subtree to a standalone application under the accepted extraction plan and dev ADR 0014. The application must consume concrete host policy without embedding host layout, scraping installer shell text, or copying AWA matching semantics. AWA v1.8.2 at `cfe9437739d2928014c2156532d1986a8511fd30` contains the lexical hard-no-touch contract. AWA owns that generic contract; dev owns this host's concrete policy and deployment binding. Source extraction and fixture qualification are not installed operation authority.

# Decision

## Authority and source data

Keep `_ops/policy/worktree-policy.yml` as the original concrete AWA policy authority. Add the already authorized two exact protected roots and two managed namespace prefixes there. Treat those values as lexical policy data: never inspect their targets to verify this decision. No protected names move into public application source.

`_ops/policy/shadow-sync-host-overlay.json` owns the remaining concrete application roles: the governed repository identity, discoverable shelves, explicit writable roles, existing permanent repository-identity exclusions, supported managed locations and optional AWA evidence paths. Its first version preserves the existing Cursor/AWA managed-location scope. It does not broaden support to other workspace managers. The original policy remains authoritative for exclusion, read-only, artifact and foreign-hook dispositions.

Move the existing installer-produced dispatcher bytes into `_ops/hooks/pre-commit-dispatcher`, without changing their behavior. The identity-guard installer copies that canonical file and retains its existing foreign-hook refusal, common-Git-directory routing and prior-hook chaining. This removes the consumer's need to parse a shell heredoc.

## Versioned projection and binding

`_ops/bin/shadow-sync-host-policy.py` supplies `preview`, `apply --expected <action-digest>` and `verify`. Production derives the account home through the account database and accepts no home, runtime, candidate or pin override. Invoke it from the canonical dev checkout. Tests use explicit internal dependencies and disposable fixture homes.

The producer reads only named policy, overlay, dispatcher, release-pointer, installed module and pin-source files. It does not enumerate repositories, invoke Git, import the AWA runtime, call broad policy discovery, or reproduce the generic matching algorithm. It accepts the supported version-1 host serialization and refuses unknown keys, duplicate keys, unsupported overrides and projection ambiguity. AWA remains the validator and matcher for the complete original policy at application admission.

The closed `shadow-sync-host-policy-projection/v1` document binds the complete original policy, host-overlay and dispatcher bytes. It projects root/shelf/path dispositions, identity roles, managed locations, hook data and optional manager evidence. Publish each projection as an immutable content-addressed generation under `Library/Application Support/ShadowSync/projections/`.

The closed `shadow-sync-host-policy-binding/v1` locator at `Library/Application Support/ShadowSync/host-policy-binding.json` references the original policy, one projection generation and the exact installed AWA module/release identity. It contains digests and normalized account-home-relative paths, not a second copy of the concrete policy literals. The v1 producer supports the existing regular-directory installation at `.local/share/awa/current`; it does not follow a symlink or accept alternate runtime locations implicitly. The module digest is `e149896d854254550765aa1f42e78a83bf17b7a2f49f24bacf96425ebc6c0219` for the exact v1.8.2 policy module. These pins come from the dev-owned release-binding checker, without executing that checker during publication.

The consumer verifies the binding, original policy, projection, live source-input hashes and its independently signed AWA contract pin before candidate access, and revalidates at operation admission. Only the AWA result `matched=false`, `kind=none`, `policy_valid=true` can permit later candidate access. A valid generic empty/missing field is not proof that this host's required policy was deployed. The producer requires the explicit nonempty host field; the accepted dev revision and deployment receipt bind the reviewed concrete values.

## Publication and recovery

Open configuration through no-follow descriptors. Require safe ownership/modes, bounded single-link regular files and stable named/opened identities. Never interpret configuration paths as candidate repositories. The publisher retains one coordination lock inode and refuses contention; it never deletes a contended lock.

Preview is read-only and returns an action digest bound to source inputs, proposed output hashes and the prior binding hash. Apply recomputes that preview under the publisher lock. It may create its owner-private output directories and lock before refusing stale inputs; this is not binding publication or application activation.

Write/fsync the immutable projection, preserve a prior valid binding in content-addressed history when changing it, revalidate inputs, then atomically replace/fsync the binding last. Do not unlink the old binding first. Interrupted pre-publication leaves the old binding or no binding; retry reuses the complete identical generation. A corrupt/unknown prior binding, damaged generation, unsafe path, wrong release/module or stale action refuses without reset. Source drift after publication causes consumer refusal; repair forward from reviewed sources. Never remove the hard-no-touch policy to accommodate the legacy application. No user state, saved selections, logs or repository data is part of this publisher's write set.

The existing AWA overlay installer now refuses a missing canonical tracked policy before runtime, mode, hook or job mutation; it no longer reconstructs a weaker fallback policy. Existing modes-file reconciliation stays independently owned and unchanged.

## Delivery and installed gate

This decision changes dev source and the host-policy interface only. Existing runnerless fleet delivery, deployed controller 0.13.0 and all fleet pins remain unchanged. ShadowSync alone retains the native GitHub delivery exception in ADR 0014.

Before a real deployment: verify the exact accepted AWA release and merged Skills binding, preserve external hook ownership and current host settings, drain/stop the legacy application through authenticated lifecycle authority, and preserve backups and user startup intent. Verify the merged dev revision and all producer source hashes. Deploy AWA without inherited live-workspace discovery parameters; verify exact installed release/module identity. Deploy the reviewed host policy and binding through preview/apply/verify, then qualify the compatible signed ShadowSync consumer before enabling repository work. Do not run fixture or inventory commands against protected targets. If source or runtime prerequisites differ, stop and preserve the prior installation.

No source merge, generated binding or credential readiness establishes installation, signed release, installed update, retirement or UAT acceptance. Those remain the distinct gates in the accepted ShadowSync extraction plan. The old 0.9.0 consumer is not compatible with the new policy field and must not be reactivated as a policy workaround.

# Verification

Required source evidence includes the synthetic publisher suite, positive/negative projection parity with the application contract, legacy dispatcher byte equivalence and installer chaining/idempotence/foreign-framework cases, and the existing AWA overlay/integrity fixture suites. Tests cover absent/malformed/duplicate fields, stale previews, wrong pins, symlinks, hard links, FIFO/oversize files, inode replacement, unsafe permissions, lock contention, failed replacement, interruption/retry, preserved prior generations and source drift. All destructive and protected-path scenarios use disposable neutral fixtures.

Run the full dev verification recipe under the prescribed isolated release-bound environment before delivery. Independently review exact source and governance outputs, then use dev's existing protected-path administration route. Record which tests are fixture-level versus native installed evidence; do not manufacture controller execution or acceptance receipts.

# Consequences

Public product code consumes a versioned contract rather than host literals. Host changes become explicit reviewed source plus a separate atomic deployment, with fail-closed drift detection. The initial publisher intentionally refuses unsupported layouts, newer schemas, nonempty policy overrides and ambiguous recovery state. It does not add automatic bootstrap, application installation, fleet enrollment or broad cleanup. Future interface changes require a successor schema/decision and coordinated consumer qualification.
