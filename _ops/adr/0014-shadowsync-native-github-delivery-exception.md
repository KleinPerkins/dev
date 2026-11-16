---
{"approval":{"actor":"KleinPerkins","date":"2026-11-02","review_sha256":"1e1ffb2a73eb19fc0ed89c6c3dd9ce0dee743ccb9d3658e1f05a69abf7fed92d"},"authority":"semantic","github_repository_id":1278387789,"id":"ADR-54aec621-9236-53d2-87b7-9a60ef4ec92e-36d6d572-cef0-5f2f-8a13-87a5c1f6f46f","lifecycle":"approved","mutability":"frozen_after_approval","provenance":[],"relations":[],"repository_key":"54aec621-9236-53d2-87b7-9a60ef4ec92e","schema":"doc-warden/artifact/v2","supersedes":null,"type":"adr","version":1}
---
# ADR 0014: ShadowSync native GitHub delivery exception

## Decision

Authorize a repository-specific delivery exception for `KleinPerkins/shadow-sync`, the public proprietary macOS product extracted from Skills. The durable checkout is `~/dev/personal/shadow-sync`. Its product name remains ShadowSync; its technical identity is `shadow-sync` / `com.kleinperkins.shadow-sync`.

Only this repository may use the accepted Sterling-style native GitHub Actions/App delivery process under this decision. Use free standard GitHub-hosted runners, read-only default workflow permissions, full action/dependency pins, isolated credential-free PR testing, and bounded retention. No larger or self-hosted runner, paid usage, or fleet-wide Actions activation is authorized.

The repository's reviewer App alone approves eligible exact ordinary heads and arms native squash auto-merge. Required current-head/base CI, stale-approval dismissal, resolved conversations, linear history, force-push/deletion protection and the approved merge mechanism remain mandatory. Agents own ordinary authorized PR delivery through verified merge; no generic operator code-review gate is added. Protected automation changes use their separate owner/admin technical-review path. Product-release environment approval remains separate from ordinary delivery and UAT acceptance.

Dev owns a narrow repository-identity classification so baseline/scaffolding recognizes this native delivery exception and does not stage runnerless contracts or rewrite the repository into a fleet delivery profile. Bootstrap can establish the baseline without enrolling it in the runnerless controller. This classification must match the exact owner/repository and must not use a broad public-repository, path, or owner-wide exemption. Record the immutable GitHub repository ID when it exists; missing identity or ambiguous remotes fail closed for mutation. Verification must prove unrelated repositories retain their prior classification and safeguards.

## Why

The accepted ShadowSync extraction package requires independent macOS runtime CI, Developer ID signing, notarization, protected release approval and Sparkle updates. Standard public-repository hosted CI provides the selected no-paid-usage model. Sterling provides the delivery reference, but its checked-in workflows alone do not prove ShadowSync operation: the new repository must independently exercise exact-head PR review/merge, mandatory runtime coverage, signing, release, installed migration and installed update.

The home baseline currently describes every fleet repository as runnerless. A named exception resolves that conflict without weakening Skills or the existing fleet. Visibility and licensing remain separate: public source is deliberately visible; proprietary licensing does not make it confidential. The sanitized export must pass its publication gate before source is published.

## Consequences

- Scope is this product repository and the minimum dev policy/classification/scaffold changes needed to support it. Skills, the PR automation controller, AWA, ecosystem distribution, existing fleet settings and all excluded repositories retain their current authority and delivery policies.
- The dev policy and baseline documentation must point to this exception. Generic baseline operations must preserve native-delivery controls, never remove required CI or activate runnerless enrollment for ShadowSync. Any operational setting mutation is separately evidenced by exact read-back.
- Repository administration creates the public source only after export review, then applies and verifies the governed configuration. Protected release credentials remain isolated from ordinary CI; secret values are never retrieved or printed during configuration inspection.
- Native CI is operational only after its substantive suites and aggregate negative cases execute successfully. Signing readiness, an artifact, published immutable bytes, clean install, installed update, legacy retirement and explicit UAT acceptance remain separate milestones.
- This decision does not satisfy or bypass the unfinished hard-no-touch dependency chain. Installed activation still requires the governed AWA release/pin/runtime, concrete dev policy, compatible ShadowSync consumer and the named migration/release gates.
- No host installation, application migration, fleet enforcement, instruction installation, credential provisioning, release publication or user-data cleanup occurs merely by accepting or merging this ADR.

## Authority and validation

This decision adopts only the native-delivery exception and associated boundaries already accepted in the 2026-11-02 ShadowSync execution package. The original submitted package SHA-256 is `7b277d2511e41ba4b851c5cb5dab679db0ad9206964c4a427d73d33d6c8084f0`; Skills' canonical acceptance and ownership handoff are tracked by [Skills PR #250](https://github.com/KleinPerkins/skills/pull/250). This dev decision becomes canonical through doc-warden's exact preview/consent transaction and normal governed source delivery.

Before delivery, use disposable fixture repositories to prove exact-identity matching, non-target parity, refusal on mismatched identities, no runnerless enrollment, and preservation of native protection/configuration. Validate the current owner policy and applicable checks. Do not inspect or mutate real excluded repositories.

## Recovery

Before bootstrap, a failed classification or verification leaves repository creation/configuration unapplied. After bootstrap, keep the last verified controls while correcting the exception through a reviewed change; never revert to runnerless enrollment, drop required checks, or make source private as an automatic recovery. A material delivery-model change requires a successor decision. Preserve existing repositories, branches, checkouts and user data.
