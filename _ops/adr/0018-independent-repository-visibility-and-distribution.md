---
{"approval":{"actor":"KleinPerkins","date":"2026-11-07","review_sha256":"c1807a38103a4ab125461dcbfe0cb91daa61ee44e6a54e1163912294e7d6309b"},"authority":"semantic","github_repository_id":1278387789,"id":"ADR-54aec621-9236-53d2-87b7-9a60ef4ec92e-f508d0be-253c-52f7-ad56-0be8671ffdb5","lifecycle":"approved","mutability":"frozen_after_approval","provenance":[],"relations":[],"repository_key":"54aec621-9236-53d2-87b7-9a60ef4ec92e","schema":"doc-warden/artifact/v2","supersedes":null,"type":"adr","version":1}
---
# ADR 0018: Independent repository visibility and distribution

## Context and scope

The operator approved the provider-neutral v2 policy and rollout direction on 2026-11-07. This decision establishes the shared policy for repositories governed by the dev umbrella and records Sterling as the first migration. It prospectively replaces the silent private-source creation default; source and distribution choices are independent. Existing accepted authorities and historical evidence are preserved.

This acceptance establishes policy direction and requirements. Creation tooling, registry enforcement, provider/capability qualification, Sterling integration and other-repository adoption remain implementation and rollout work. No provider, new capability repository, recipient scheme, host installation, spending or product release is selected by it.

## Decision

### Decisions before creation

Every new repository in this operating model's governed scope requires explicit operator choices for source visibility (`public` or `private`) and product distribution audience (`public`, `private` or explicit `none`) before creation begins. The creation preview records both decisions. Reuse complete direction already supplied by the operator; clarify missing choices. Never infer either choice from a default, name, source license, current provider state or the other choice.

This requirement applies to personal and capability repositories and every supported agent, CLI, legacy, dry-run/no-push and resume entrypoint. Read-only planning may report missing values; mutation may not proceed with them unresolved. A noninteractive invocation must carry both explicit choices and the applicable operation-bound authorization. Source-only flags never authorize product distribution.

Public source may have public or private product distribution. Private source may likewise have public or private distribution where the owning scope allows it. Explicit `none` permits repository creation but authorizes no product publication. Source visibility, product audience, licensing, CI/merge authority, cost approval and product release acceptance are separate decisions.

## Central authority and consumer binding

The umbrella owns the approved repository decision registry and distribution profiles. A record binds immutable repository identity, both choices, declared outputs/channels, policy/profile version and transition evidence. Repository-local configuration is a nonsecret projection of that authority. It cannot authorize new public exposure or broaden an audience by itself.

Shared contracts, adapters, conformance fixtures and operational practices belong to one reusable distribution capability. Repository documentation points to that standard and retains only product configuration, platform adapter obligations and product evidence. Separate umbrellas consume the same capability through isolated owner-controlled overlays, not shared authority or credentials.

Public consumers must receive an explicitly reviewed nonsecret contract/projection without broad access to the private umbrella repository or other consumers' data. Resolve identity, currency and effective approval before activation and publication. Unknown, missing, changed or unqualified bindings deny new publication rather than choosing a default.

## Distribution standard

Private distribution requires authenticated access for every delivery surface and its underlying origin, including product downloads, package/container artifacts, update manifests/feeds, relevant metadata, redirects, caches, HEAD and range requests. Unlisted URLs do not establish private access. Enrollment, credential/session replacement, revocation within a declared qualified window and recovery must be supported. Recipient access and publication authority are separate, scoped by project/product/channel and isolated between consumers.

Protect credential custody and keep secrets out of committed configuration, binaries, manifests, URLs and logs. Verify producer identity and artifact integrity using the applicable platform/package trust mechanism. Access controls do not replace signatures/integrity verification, and code signing does not grant access.

Bind publication to approved policy, source revision, output inventory, version and audience. Published version bytes are immutable. Stage and verify before promotion; reject stale/concurrent transitions; preserve a known working target and provide a qualified recovery procedure. Missing private configuration or failed access must never fall back to public publication. Define first-release failure behavior explicitly.

A provider or adapter qualifies by proving these outcomes, including authorized access, anonymous/invalid/revoked denial, origin/cross-project isolation, integrity rejection, promotion/recovery and the applicable real product delivery flow. The policy mandates no updater, registry, identity provider, hosting vendor, CI engine or custom service. Use provider-native mechanisms when they satisfy the standard. A tool that cannot meet it is not an excuse to weaken or reinterpret it.

Public distribution retains producer integrity, provenance, immutable version and release approval requirements and must expose only approved output inventory. Private-source/public-distribution must not leak unrelated source, credentials or build material. Distribution `none` refuses product publication.

## Enforcement and operations

The governed creation entrypoint enforces complete decisions before creation. Repository checks and activation preflight enforce the central binding. Effective provider/service permissions enforce private read and publication boundaries. Read-only doctor/drift checks report live disagreement, unavailable observations and out-of-band changes; they do not silently repair visibility, release assets, recipient access or branch protection.

Local hooks, repository configuration and same-user CLI checks are not a security boundary against an owner/admin using another path. Qualify the actual credential and provider boundary; disclose residual broad provider permissions and administrator access. Do not claim enforcement based only on generated documentation or helper-script checks.

Retain existing source CI, exact-head checks, protected automation and repository/controller merge authority. Distribution audience does not authorize a runner-policy change, arbitrary execution in the PR controller, doc-warden release orchestration or bypass of required gates. Existing exclusions and separately governed owners remain effective.

Every active profile has an operating owner, qualified pin/compatibility path, audit/credential rotation, retention/backup, recovery and approved costs. Revocation stops future access within the qualified window; it does not recover previously downloaded files or prevent copying. Shared service use never implies shared signing keys, recipient secrets or account-wide credentials.

## Existing repositories and transitions

Inventory observed source visibility and product surfaces separately from approved intent. Require explicit classification where intent is unknown; never adopt a live state as retrospective approval. New intake applies prospectively; existing repositories migrate through explicit per-repository/cohort records. Preserve source/CI behavior and working client paths unless an approved transition changes them. New or expanded governed publication requires a resolved binding.

Changing source visibility, introducing distribution after `none`, broadening an audience, adding another public channel or changing an incompatible profile requires the applicable fresh preview, decision and qualification before mutation. Resume preserves work and asks for missing decisions without deleting/recreating remotes. Previously public artifacts cannot be made retroactively secret; removal of existing assets is a separate consequential action.

Sterling is the first migration with confirmed public source/private product distribution. Its product release remains gated until the central private profile, repository integration, protected-source delivery and actual install/update proof are complete. Its macOS updater is an adapter choice, not the umbrella's policy definition.

## Consequences and implementation

The supported creation tool must enforce both explicit choices across every entry/resume path. Until the enforcement implementation is delivered, agents must resolve both choices and refuse any legacy route that cannot retain and validate their approved intent. This direction does not authorize an alternative tool to infer choices or bypass the gate.

Dev owns the policy/approved registry and host integration. Reusable distribution runtime and conformance belong to one capability under capabilities; any new repository for it uses the same explicit intake. Consumers retain product configuration/adapters and reference the central policy. Do not scatter a provider-specific implementation through product repositories.

The current native-CI name allowlist is not distribution eligibility. Reconcile Sterling's already-approved native CI with dev's central identity/profile classification without enrolling it runnerless, granting a blanket public-repository runner exception or changing other lanes. Keep source policy, distribution policy and effective provider permissions separate.

Formal technical planning uses the current approved-PRD/typed-plan route and its required checks and independent review. Canonical body acceptance and exact operation-bound consent precede publication; authorized implementation is delivered through verified merge. Doc-warden remains in its existing authoring/governance role and gains no release orchestration or security-grade execution authority.

This is a prose-scoped prospective amendment to the new-repository default described by _ops/POLICY.md, OPERATING-MANUAL.md and dev-new-repo guidance. Their thin projections must be reconciled in the intake implementation body. Existing frozen ADRs/plans are not edited. Runtime/source delivery, host activation and actual product distribution must be reported separately.
